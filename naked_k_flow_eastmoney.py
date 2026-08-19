"""
naked_k_flow_eastmoney.py

东方财富逐笔成交数据采集 provider - 港股专用

符合 docs/superpowers/specs/2026-08-17-smart-money-dual-evidence-design.md §5.2
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


# 数据契约版本
SCHEMA_VERSION = "trade-flow.v1"

# 东方财富港股逐笔成交接口
EASTMONEY_TRADE_FLOW_URL = "https://push2.eastmoney.com/api/qt/stock/details/get"


@dataclass(frozen=True)
class TradePrint:
    """单笔成交记录"""
    source_ordinal: int  # 原响应顺序
    occurrence_index: int  # 同内容重复的出现序号
    trade_time: datetime  # 有时区的成交时间
    price: float  # 成交价
    volume: int  # 成交量（股）
    notional: float  # 成交金额 = price * volume
    session_phase: str  # pre_open|continuous|post_continuous_window|unknown
    side_raw: str | None  # 原始方向代码，未验证
    tick_direction: str  # uptick|downtick|zero_tick|unknown
    classification_method: str  # tick_rule
    source_row_id: str  # source_ordinal:occurrence_index


@dataclass(frozen=True)
class TradeFlowSnapshot:
    """逐笔成交快照"""
    schema_version: str
    ticker: str
    market: str
    session_date: str  # ISO date
    timezone: str
    provider: str
    source_url: str
    request_fingerprint: str
    status: str  # OK|PARTIAL|STALE|UNAVAILABLE|DEFINITION_MISMATCH|INVALID
    retrieved_at: datetime
    coverage_start: datetime | None
    coverage_end: datetime | None
    session_complete: bool
    currency: str
    price_unit: str
    volume_unit: str
    trade_count: int
    total_volume: int | None
    total_notional: float | None
    classified_notional_coverage: float
    raw_snapshot_id: str  # sha256:<64 hex>
    normalized_snapshot_id: str  # sha256:<64 hex>
    limitations: tuple[str, ...]
    trades: tuple[TradePrint, ...]


def _hk_ticker_to_eastmoney_code(ticker: str) -> str:
    """
    将 0700.HK 转换为东方财富代码 116.00700

    港股代码映射为 116.XXXXX（补齐5位）
    """
    if not ticker.endswith(".HK"):
        raise ValueError(f"Only HK tickers supported, got: {ticker}")

    code = ticker.replace(".HK", "")
    # 补齐到5位
    code_padded = code.zfill(5)
    return f"116.{code_padded}"


def _compute_sha256(content: bytes) -> str:
    """计算 SHA-256 哈希，返回 sha256:<64 hex> 格式"""
    digest = hashlib.sha256(content).hexdigest()
    return f"sha256:{digest}"


def _parse_eastmoney_response(
    response_data: dict[str, Any],
    ticker: str,
    session_date: str,
    retrieved_at: datetime,
) -> TradeFlowSnapshot:
    """
    解析东方财富接口响应

    东方财富返回格式（未文档化，基于探测）：
    {
        "data": {
            "code": "116.00700",
            "market": 116,
            "details": "时间,价格,数量,方向\n09:30:03,372.20,10000,1\n..."
            或
            "details": ["09:30:03,372.20,10000,1", "09:30:05,372.40,5000,1", ...]
        }
    }
    """
    data = response_data.get("data", {})
    details_raw = data.get("details", "")

    # 处理 details 为列表或字符串的情况
    if isinstance(details_raw, list):
        rows = details_raw
    elif isinstance(details_raw, str):
        if not details_raw:
            rows = []
        else:
            lines = details_raw.strip().split("\n")
            # 跳过可能的表头
            rows = lines[1:] if lines and "时间" in lines[0] else lines
    else:
        rows = []

    if not rows:
        return TradeFlowSnapshot(
            schema_version=SCHEMA_VERSION,
            ticker=ticker,
            market="hk",
            session_date=session_date,
            timezone="Asia/Hong_Kong",
            provider="eastmoney",
            source_url=EASTMONEY_TRADE_FLOW_URL,
            request_fingerprint="",
            status="UNAVAILABLE",
            retrieved_at=retrieved_at,
            coverage_start=None,
            coverage_end=None,
            session_complete=False,
            currency="HKD",
            price_unit="per_share",
            volume_unit="shares",
            trade_count=0,
            total_volume=None,
            total_notional=None,
            classified_notional_coverage=0.0,
            raw_snapshot_id="",
            normalized_snapshot_id="",
            limitations=("no_data",),
            trades=(),
        )

    # 解析逐笔数据

    trades: list[TradePrint] = []
    prev_price: float | None = None
    last_nonzero_direction: str = "unknown"

    for ordinal, row in enumerate(rows):
        parts = row.split(",")
        if len(parts) < 4:
            continue

        try:
            time_str, price_str, volume_str, side_raw_str = parts[:4]
            price = float(price_str)
            volume = int(volume_str)
            notional = price * volume

            # 解析时间
            # 假设格式为 HH:MM:SS
            hour, minute, second = map(int, time_str.split(":"))
            trade_dt = datetime(
                int(session_date[:4]),
                int(session_date[5:7]),
                int(session_date[8:10]),
                hour,
                minute,
                second,
                tzinfo=timezone.utc,  # 先用 UTC，后续可改为 Asia/Hong_Kong
            )

            # Tick direction
            if prev_price is None:
                tick_direction = "unknown"
            elif price > prev_price:
                tick_direction = "uptick"
                last_nonzero_direction = "uptick"
            elif price < prev_price:
                tick_direction = "downtick"
                last_nonzero_direction = "downtick"
            else:
                tick_direction = last_nonzero_direction

            # Session phase (简化版本)
            if hour < 9 or (hour == 9 and minute < 30):
                phase = "pre_open"
            elif hour < 16:
                phase = "continuous"
            else:
                phase = "post_continuous_window"

            trades.append(TradePrint(
                source_ordinal=ordinal,
                occurrence_index=0,  # 暂不处理重复
                trade_time=trade_dt,
                price=price,
                volume=volume,
                notional=notional,
                session_phase=phase,
                side_raw=side_raw_str,
                tick_direction=tick_direction,
                classification_method="tick_rule",
                source_row_id=f"{ordinal}:0",
            ))

            prev_price = price

        except (ValueError, IndexError):
            continue

    # 统计
    trade_count = len(trades)
    total_volume = sum(t.volume for t in trades) if trades else None
    total_notional = sum(t.notional for t in trades) if trades else None

    # 覆盖时间
    coverage_start = trades[0].trade_time if trades else None
    coverage_end = trades[-1].trade_time if trades else None

    # Session complete (简化判断)
    session_complete = False
    if coverage_end and coverage_end.hour >= 16:
        session_complete = True

    # 计算快照ID
    raw_content = json.dumps(response_data, sort_keys=True).encode()
    raw_snapshot_id = _compute_sha256(raw_content)

    # 序列化 trades 时需要将 datetime 转换为 ISO 字符串
    trades_for_hash = []
    for t in trades:
        t_dict = asdict(t)
        t_dict["trade_time"] = t.trade_time.isoformat()
        trades_for_hash.append(t_dict)
    normalized_content = json.dumps(trades_for_hash, sort_keys=True).encode()
    normalized_snapshot_id = _compute_sha256(normalized_content)

    return TradeFlowSnapshot(
        schema_version=SCHEMA_VERSION,
        ticker=ticker,
        market="hk",
        session_date=session_date,
        timezone="Asia/Hong_Kong",
        provider="eastmoney",
        source_url=EASTMONEY_TRADE_FLOW_URL,
        request_fingerprint="",  # TODO: 实现请求指纹
        status="OK" if trade_count > 0 else "UNAVAILABLE",
        retrieved_at=retrieved_at,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        session_complete=session_complete,
        currency="HKD",
        price_unit="per_share",
        volume_unit="shares",
        trade_count=trade_count,
        total_volume=total_volume,
        total_notional=total_notional,
        classified_notional_coverage=1.0 if trade_count > 0 else 0.0,
        raw_snapshot_id=raw_snapshot_id,
        normalized_snapshot_id=normalized_snapshot_id,
        limitations=(),
        trades=tuple(trades),
    )


def fetch_trade_flow(
    ticker: str,
    session_date: str,
    timeout: int = 30,
) -> TradeFlowSnapshot:
    """
    获取港股逐笔成交数据

    Args:
        ticker: 股票代码，如 "0700.HK"
        session_date: 交易日，ISO格式 "YYYY-MM-DD"
        timeout: 请求超时（秒）

    Returns:
        TradeFlowSnapshot 快照对象
    """
    retrieved_at = datetime.now(timezone.utc)

    try:
        em_code = _hk_ticker_to_eastmoney_code(ticker)
    except ValueError as e:
        return TradeFlowSnapshot(
            schema_version=SCHEMA_VERSION,
            ticker=ticker,
            market="hk",
            session_date=session_date,
            timezone="Asia/Hong_Kong",
            provider="eastmoney",
            source_url=EASTMONEY_TRADE_FLOW_URL,
            request_fingerprint="",
            status="INVALID",
            retrieved_at=retrieved_at,
            coverage_start=None,
            coverage_end=None,
            session_complete=False,
            currency="HKD",
            price_unit="per_share",
            volume_unit="shares",
            trade_count=0,
            total_volume=None,
            total_notional=None,
            classified_notional_coverage=0.0,
            raw_snapshot_id="",
            normalized_snapshot_id="",
            limitations=(f"invalid_ticker: {str(e)}",),
            trades=(),
        )

    # 构造请求参数
    params = {
        "fields1": "f1,f2,f3,f4",
        "fields2": "f51,f52,f53,f54",
        "mpi": "2000",  # 最大返回条数
        "secid": em_code,
    }

    try:
        response = requests.get(
            EASTMONEY_TRADE_FLOW_URL,
            params=params,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        response_data = response.json()

        return _parse_eastmoney_response(
            response_data,
            ticker,
            session_date,
            retrieved_at,
        )

    except requests.RequestException as e:
        return TradeFlowSnapshot(
            schema_version=SCHEMA_VERSION,
            ticker=ticker,
            market="hk",
            session_date=session_date,
            timezone="Asia/Hong_Kong",
            provider="eastmoney",
            source_url=EASTMONEY_TRADE_FLOW_URL,
            request_fingerprint="",
            status="UNAVAILABLE",
            retrieved_at=retrieved_at,
            coverage_start=None,
            coverage_end=None,
            session_complete=False,
            currency="HKD",
            price_unit="per_share",
            volume_unit="shares",
            trade_count=0,
            total_volume=None,
            total_notional=None,
            classified_notional_coverage=0.0,
            raw_snapshot_id="",
            normalized_snapshot_id="",
            limitations=(f"request_failed: {str(e)}",),
            trades=(),
        )


def save_snapshot(
    snapshot: TradeFlowSnapshot,
    output_dir: Path,
) -> Path:
    """
    保存快照到磁盘

    路径格式：reports/market_data/trade_flow/YYYY-MM-DD/<ticker>/<retrieved_at>-<sha256>.raw.json.gz

    Returns:
        保存的文件路径
    """
    # 构造目录结构
    session_dir = output_dir / snapshot.session_date / snapshot.ticker
    session_dir.mkdir(parents=True, exist_ok=True)

    # 文件名：YYYYMMDDTHHMMSSffffffZ-<sha256前12位>.raw.json.gz
    retrieved_str = snapshot.retrieved_at.strftime("%Y%m%dT%H%M%S%fZ")
    hash_prefix = snapshot.raw_snapshot_id.split(":")[1][:12]
    filename = f"{retrieved_str}-{hash_prefix}.raw.json.gz"
    filepath = session_dir / filename

    # 序列化并压缩保存
    snapshot_dict = asdict(snapshot)
    # 将 datetime 转换为 ISO 字符串
    snapshot_dict["retrieved_at"] = snapshot.retrieved_at.isoformat()
    if snapshot.coverage_start:
        snapshot_dict["coverage_start"] = snapshot.coverage_start.isoformat()
    if snapshot.coverage_end:
        snapshot_dict["coverage_end"] = snapshot.coverage_end.isoformat()

    # 处理 trades
    trades_serializable = []
    for trade in snapshot.trades:
        trade_dict = asdict(trade)
        trade_dict["trade_time"] = trade.trade_time.isoformat()
        trades_serializable.append(trade_dict)
    snapshot_dict["trades"] = trades_serializable

    with gzip.open(filepath, "wt", encoding="utf-8") as f:
        json.dump(snapshot_dict, f, ensure_ascii=False, indent=2)

    return filepath
