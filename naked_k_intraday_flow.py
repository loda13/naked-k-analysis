"""
分钟线聚合的 trade flow 替代方案。

东财逐笔接口（push2.eastmoney.com/api/qt/stock/details/get）已对本机失效，
本模块用 1 分钟 K 线的成交量分布 / VWAP / 时段结构提取当日资金流代理特征。

重要口径说明：
- 这不是逐笔成交，没有真实主动买卖方向，只有"分钟收阳/收阴"的代理；
- 因此证据质量最高只能标 PROXY，绝不能与真实 tape 证据同级；
- 与日线 OHLCV Volume 同源，按设计文档 §8.5 属同一依赖组，不构成独立双源。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

import pandas as pd

SCHEMA_VERSION = "intraday-flow.v1"

# 港股连续交易时段（Asia/Hong_Kong）
MORNING_START = (9, 30)
MORNING_END = (12, 0)
AFTERNOON_START = (13, 0)
AFTERNOON_END = (16, 0)

# 最少需要的分钟 bar 数，低于此值只给 PARTIAL
MIN_BARS_FOR_VALID = 60


@dataclass(frozen=True)
class IntradayFlowSnapshot:
    """分钟线聚合的当日资金流快照。"""

    schema_version: str
    ticker: str
    session_date: str
    provider: str
    status: str            # OK / PARTIAL / UNAVAILABLE
    quality: str           # PROXY / PARTIAL / UNAVAILABLE
    retrieved_at: datetime
    bar_count: int
    total_volume: float
    vwap: float
    last_close: float
    close_vs_vwap: float           # (close - vwap) / vwap
    uptick_volume_ratio: float     # 收阳分钟成交占比
    large_bar_volume_ratio: float  # 成交量 > Q3 的分钟占比
    large_bar_uptick_ratio: float  # 大量分钟里收阳的成交占比
    volume_q1: float
    volume_q2: float
    volume_q3: float
    volume_max: float
    morning_volume_ratio: float
    afternoon_volume_ratio: float
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["retrieved_at"] = self.retrieved_at.isoformat()
        d["limitations"] = list(self.limitations)
        return d


def _unavailable(ticker: str, session_date: str, reason: str) -> IntradayFlowSnapshot:
    return IntradayFlowSnapshot(
        schema_version=SCHEMA_VERSION,
        ticker=ticker,
        session_date=session_date,
        provider="intraday_ohlcv",
        status="UNAVAILABLE",
        quality="UNAVAILABLE",
        retrieved_at=datetime.now(timezone.utc),
        bar_count=0,
        total_volume=0.0,
        vwap=0.0,
        last_close=0.0,
        close_vs_vwap=0.0,
        uptick_volume_ratio=0.0,
        large_bar_volume_ratio=0.0,
        large_bar_uptick_ratio=0.0,
        volume_q1=0.0,
        volume_q2=0.0,
        volume_q3=0.0,
        volume_max=0.0,
        morning_volume_ratio=0.0,
        afternoon_volume_ratio=0.0,
        limitations=(reason,),
    )


def _in_window(idx: pd.DatetimeIndex, start: tuple[int, int], end: tuple[int, int]) -> pd.Series:
    minutes = idx.hour * 60 + idx.minute
    return (minutes >= start[0] * 60 + start[1]) & (minutes < end[0] * 60 + end[1])


def build_intraday_flow(
    ticker: str,
    session_date: str,
    intraday: pd.DataFrame | None,
) -> IntradayFlowSnapshot:
    """
    从已加载的分钟线 DataFrame 计算当日资金流代理特征。

    纯计算，不做网络 I/O —— 调用方负责取数（与设计文档 §10.4 一致）。
    """
    if intraday is None or intraday.empty:
        return _unavailable(ticker, session_date, "no_intraday_data")

    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(intraday.columns):
        return _unavailable(ticker, session_date, "missing_ohlcv_columns")

    df = intraday.dropna(subset=["Close", "Volume"]).copy()
    df = df[df["Volume"] > 0]
    if df.empty:
        return _unavailable(ticker, session_date, "no_positive_volume_bars")

    total_volume = float(df["Volume"].sum())
    if total_volume <= 0:
        return _unavailable(ticker, session_date, "zero_total_volume")

    limitations: list[str] = ["proxy_not_real_tape", "same_dependency_group_as_daily_volume"]
    bar_count = int(len(df))
    if bar_count < MIN_BARS_FOR_VALID:
        status, quality = "PARTIAL", "PARTIAL"
        limitations.append(f"insufficient_bars:{bar_count}")
    else:
        status, quality = "OK", "PROXY"

    vwap = float((df["Close"] * df["Volume"]).sum() / total_volume)
    last_close = float(df["Close"].iloc[-1])
    close_vs_vwap = (last_close - vwap) / vwap if vwap else 0.0

    q1 = float(df["Volume"].quantile(0.25))
    q2 = float(df["Volume"].quantile(0.50))
    q3 = float(df["Volume"].quantile(0.75))
    qmax = float(df["Volume"].max())

    up_mask = df["Close"] > df["Open"]
    uptick_volume_ratio = float(df.loc[up_mask, "Volume"].sum() / total_volume)

    large_mask = df["Volume"] > q3
    large_volume = float(df.loc[large_mask, "Volume"].sum())
    large_bar_volume_ratio = large_volume / total_volume
    large_bar_uptick_ratio = (
        float(df.loc[large_mask & up_mask, "Volume"].sum() / large_volume)
        if large_volume > 0
        else 0.0
    )

    if isinstance(df.index, pd.DatetimeIndex):
        morning = float(df.loc[_in_window(df.index, MORNING_START, MORNING_END), "Volume"].sum())
        afternoon = float(df.loc[_in_window(df.index, AFTERNOON_START, AFTERNOON_END), "Volume"].sum())
        morning_ratio = morning / total_volume
        afternoon_ratio = afternoon / total_volume
        if morning + afternoon == 0:
            limitations.append("session_window_unmatched")
    else:
        morning_ratio = afternoon_ratio = 0.0
        limitations.append("index_not_datetime")

    return IntradayFlowSnapshot(
        schema_version=SCHEMA_VERSION,
        ticker=ticker,
        session_date=session_date,
        provider="intraday_ohlcv",
        status=status,
        quality=quality,
        retrieved_at=datetime.now(timezone.utc),
        bar_count=bar_count,
        total_volume=total_volume,
        vwap=vwap,
        last_close=last_close,
        close_vs_vwap=float(close_vs_vwap),
        uptick_volume_ratio=uptick_volume_ratio,
        large_bar_volume_ratio=large_bar_volume_ratio,
        large_bar_uptick_ratio=large_bar_uptick_ratio,
        volume_q1=q1,
        volume_q2=q2,
        volume_q3=q3,
        volume_max=qmax,
        morning_volume_ratio=morning_ratio,
        afternoon_volume_ratio=afternoon_ratio,
        limitations=tuple(limitations),
    )


__all__ = [
    "IntradayFlowSnapshot",
    "build_intraday_flow",
    "fetch_intraday_bars",
    "collect_intraday_flow",
    "SCHEMA_VERSION",
]


def fetch_intraday_bars(ticker: str) -> pd.DataFrame | None:
    """
    取当日分钟线。

    注意：westock_wrapper.download() 对港股 interval='1m' 会降级成日线
    （实测 0700.HK 只回 1-2 根 bar），因此这里直接走原生 yfinance，
    实测可拿到完整交易日 331 根 1 分钟 bar（09:30-16:08 含收盘竞价）。
    """
    try:
        import yfinance

        df = yfinance.Ticker(ticker).history(period="1d", interval="1m")
        if df is None or df.empty or len(df) < 2:
            return None
        return df
    except Exception:
        return None


def collect_intraday_flow(ticker: str, session_date: str | None = None) -> IntradayFlowSnapshot:
    """取数 + 计算的便捷入口。取数失败时返回 UNAVAILABLE 快照，不抛异常。"""
    bars = fetch_intraday_bars(ticker)
    if bars is None:
        return _unavailable(ticker, session_date or "", "intraday_fetch_failed")

    if session_date is None:
        session_date = str(bars.index[-1].date()) if isinstance(bars.index, pd.DatetimeIndex) else ""

    return build_intraday_flow(ticker, session_date, bars)
