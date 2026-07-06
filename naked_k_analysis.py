#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

import naked_k_patterns
import westock_wrapper as yf

DEFAULT_TICKERS = [
    ("腾讯", "0700.HK"),
    ("小米", "1810.HK"),
    ("PDD", "PDD"),
    ("泡泡玛特", "9992.HK"),
]
DEFAULT_JOURNAL_PATH = Path("reports/naked_k_journal.jsonl")
DEFAULT_REPORT_PATH = Path("reports/naked_k_latest.md")

BULLISH_PATTERN_KEYS = ("看涨吸收", "看涨Pin", "锤子线", "早晨星", "蜻蜓十字", "阴孕阳")
BEARISH_PATTERN_KEYS = ("看跌吸收", "看跌Pin", "射击之星", "黄昏星", "墓碑十字", "阳孕阴")
WATCH_PATTERN_KEYS = ("十字星", "双孕线", "孕线")
BULLISH_ACTIONS = {"买入", "小仓试错"}
BEARISH_ACTIONS = {"减仓", "回避"}
MIN_ACTIONABLE_REWARD_TO_RISK = 1.0


def classify_market(ticker: str) -> str:
    symbol = ticker.upper()
    if symbol.endswith(".HK"):
        return "hk"
    if symbol.endswith((".SS", ".SZ")):
        return "cn"
    return "us"


@dataclass
class InstrumentReport:
    name: str
    ticker: str
    action: str
    entry_trigger: float
    stop_loss: float
    target_price: float | None
    risk_per_share: float
    reward_to_risk: float | None
    signal_state: str
    resistance: float
    support: float
    position_size: str
    rationale: str
    daily_patterns: list[str]
    weekly_patterns: list[str]
    weekly_context: str
    data_sources: dict[str, str]
    latest_k_dates: dict[str, str]
    latest_closes: dict[str, float]
    review: dict[str, Any]
    improvement: str
    intraday_status: dict[str, Any] = field(default_factory=dict)
    price_action: dict[str, Any] = field(default_factory=dict)


def build_breakout_trigger(bar: pd.Series, side: str, buffer_ratio: float = 0.002) -> float:
    if side == "bullish":
        return round(float(bar["High"]) * (1 + buffer_ratio), 2)
    return round(float(bar["Low"]) * (1 - buffer_ratio), 2)


def build_invalidation_level(bar: pd.Series, side: str, buffer_ratio: float = 0.002) -> float:
    if side == "bullish":
        return round(float(bar["Low"]) * (1 - buffer_ratio), 2)
    return round(float(bar["High"]) * (1 + buffer_ratio), 2)


def calculate_atr(frame: pd.DataFrame, window: int = 14) -> float | None:
    if frame.empty or not {"High", "Low", "Close"}.issubset(frame.columns):
        return None
    high = frame["High"].astype(float)
    low = frame["Low"].astype(float)
    close = frame["Close"].astype(float)
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    true_range = true_range.dropna()
    if true_range.empty:
        return None
    sample = true_range.tail(window)
    return float(sample.mean())


def build_volatility_buffer_ratio(
    frame: pd.DataFrame,
    base_ratio: float = 0.002,
    atr_fraction: float = 0.10,
    max_ratio: float = 0.015,
) -> float:
    atr = calculate_atr(frame)
    if atr is None:
        return base_ratio
    close = float(frame["Close"].iloc[-1])
    if close <= 0:
        return base_ratio
    atr_buffer = atr / close * atr_fraction
    return round(max(base_ratio, min(max_ratio, atr_buffer)), 4)


def build_signal_state(action: str) -> str:
    if action in BULLISH_ACTIONS:
        return "planned_long"
    if action in BEARISH_ACTIONS:
        return "planned_short"
    return "watching"


def build_trade_metrics(
    action: str,
    entry_trigger: float,
    stop_loss: float,
    resistance: float,
    support: float,
) -> tuple[float | None, float, float | None]:
    risk_per_share = round(abs(entry_trigger - stop_loss), 2)
    target_price: float | None = None
    if action in BULLISH_ACTIONS and resistance > entry_trigger:
        target_price = resistance
    elif action in BEARISH_ACTIONS and support < entry_trigger:
        target_price = support

    reward_to_risk: float | None = None
    if target_price is not None and risk_per_share > 0:
        reward_to_risk = round(abs(target_price - entry_trigger) / risk_per_share, 2)
    return target_price, risk_per_share, reward_to_risk


def downgrade_low_reward_setup(
    action: str,
    target_price: float | None,
    reward_to_risk: float | None,
    minimum_reward_to_risk: float = MIN_ACTIONABLE_REWARD_TO_RISK,
) -> tuple[str, float | None, float | None, str | None]:
    if action not in BULLISH_ACTIONS:
        return action, target_price, reward_to_risk, None
    if target_price is None or reward_to_risk is None:
        return action, target_price, reward_to_risk, None
    if reward_to_risk >= minimum_reward_to_risk:
        return action, target_price, reward_to_risk, None
    return "观望", None, None, f"首个压力位空间不足，盈亏比不足 {minimum_reward_to_risk:.1f}R"


def build_position_guidance(
    action: str,
    entry_trigger: float,
    stop_loss: float,
    account_risk_pct: float = 1.0,
) -> str:
    if action == "买入":
        max_gross_pct = 30.0
    elif action == "小仓试错":
        max_gross_pct = 15.0
    elif action == "减仓":
        return "降至10%以内"
    elif action == "回避":
        return "0%-5%"
    else:
        return "0%-10%"

    if entry_trigger <= 0:
        return f"最高约{max_gross_pct:.1f}%仓位"
    risk_pct = abs(entry_trigger - stop_loss) / entry_trigger * 100
    if risk_pct <= 0:
        return f"最高约{max_gross_pct:.1f}%仓位"
    risk_budget_cap = account_risk_pct / risk_pct * 100
    gross_pct = min(max_gross_pct, risk_budget_cap)
    return f"最高约{gross_pct:.1f}%仓位（按{account_risk_pct:g}%账户风险，单股风险{risk_pct:.1f}%）"


def _to_float(value: Any) -> float:
    return round(float(value), 2)


def _format_ts(value: Any) -> str:
    ts = pd.Timestamp(value)
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def build_intraday_status(
    frame: pd.DataFrame | None,
    action: str,
    entry_trigger: float,
    stop_loss: float,
    proximity_pct: float = 1.0,
) -> dict[str, Any]:
    if frame is None or getattr(frame, "empty", True):
        return {
            "status": "无盘中数据",
            "note": "未获取到1h盘中K线",
        }

    latest = frame.iloc[-1]
    latest_volume = _to_float(latest.get("Volume", 0))
    payload = {
        "status": "盘中观察",
        "note": "未接近触发位或失效位",
        "source": str(frame.attrs.get("source", "unknown")),
        "interval": str(frame.attrs.get("interval", "1h")),
        "latest_time": _format_ts(frame.index[-1]),
        "latest_close": _to_float(latest["Close"]),
        "latest_high": _to_float(latest["High"]),
        "latest_low": _to_float(latest["Low"]),
        "latest_volume": latest_volume,
    }

    if latest_volume <= 0:
        payload.update(
            {
                "status": "盘中数据未确认",
                "note": "最新1h K线成交量为0，等待有效K线确认",
            }
        )
        return payload

    close = float(latest["Close"])
    high = float(latest["High"])
    low = float(latest["Low"])
    proximity = proximity_pct / 100
    is_bearish_plan = action in BEARISH_ACTIONS

    if is_bearish_plan:
        if close <= entry_trigger:
            payload.update({"status": "盘中确认", "note": "最近有效1h收盘跌破触发位"})
        elif low <= entry_trigger:
            payload.update({"status": "盘中跌破未确认", "note": "盘中跌破触发位，但1h收盘未确认"})
        elif high >= stop_loss * (1 - proximity):
            payload.update({"status": "接近失效位", "note": "盘中价格接近空头失效位"})
        elif close <= entry_trigger * (1 + proximity):
            payload.update({"status": "接近触发", "note": "最新1h价格距离触发位1%以内"})
    else:
        if close >= entry_trigger:
            payload.update({"status": "盘中确认", "note": "最近有效1h收盘站上触发位"})
        elif high >= entry_trigger:
            payload.update({"status": "盘中突破未确认", "note": "盘中突破触发位，但1h收盘未确认"})
        elif low <= stop_loss * (1 + proximity):
            payload.update({"status": "接近失效位", "note": "盘中价格接近多头失效位"})
        elif close >= entry_trigger * (1 - proximity):
            payload.update({"status": "接近触发", "note": "最新1h价格距离触发位1%以内"})

    return payload


def _latest_bar_metrics(bar: pd.Series) -> dict[str, float]:
    open_price = float(bar["Open"])
    high = float(bar["High"])
    low = float(bar["Low"])
    close = float(bar["Close"])
    full_range = max(high - low, 0.0)
    body = abs(close - open_price)
    upper_shadow = max(high - max(open_price, close), 0.0)
    lower_shadow = max(min(open_price, close) - low, 0.0)
    if full_range <= 0:
        close_position_pct = 50.0
        body_pct = 0.0
        upper_shadow_pct = 0.0
        lower_shadow_pct = 0.0
    else:
        close_position_pct = (close - low) / full_range * 100
        body_pct = body / full_range * 100
        upper_shadow_pct = upper_shadow / full_range * 100
        lower_shadow_pct = lower_shadow / full_range * 100

    return {
        "open": round(open_price, 2),
        "high": round(high, 2),
        "low": round(low, 2),
        "close": round(close, 2),
        "range": round(full_range, 2),
        "body_pct": round(body_pct, 1),
        "upper_shadow_pct": round(upper_shadow_pct, 1),
        "lower_shadow_pct": round(lower_shadow_pct, 1),
        "close_position_pct": round(close_position_pct, 1),
    }


def classify_latest_candle(bar: pd.Series) -> list[str]:
    metrics = _latest_bar_metrics(bar)
    open_price = float(metrics["open"])
    close = float(metrics["close"])
    candle_range = float(metrics["range"])
    body_pct = float(metrics["body_pct"])
    upper_shadow_pct = float(metrics["upper_shadow_pct"])
    lower_shadow_pct = float(metrics["lower_shadow_pct"])
    close_position_pct = float(metrics["close_position_pct"])
    labels: list[str] = []

    if candle_range <= 0:
        return ["无波动K线"]

    if body_pct <= 12:
        labels.append("十字犹豫")
    elif close > open_price and body_pct >= 55 and close_position_pct >= 70:
        labels.append("强阳收近高点")
    elif close < open_price and body_pct >= 55 and close_position_pct <= 30:
        labels.append("强阴收近低点")

    if upper_shadow_pct >= 45 and upper_shadow_pct > lower_shadow_pct * 1.5 and close_position_pct < 60:
        labels.append("上影线压力")
    if lower_shadow_pct >= 45 and lower_shadow_pct > upper_shadow_pct * 1.5 and close_position_pct > 40:
        labels.append("下影线承接")

    if not labels:
        labels.append("普通阳线" if close >= open_price else "普通阴线")
    return labels


def analyze_price_action_context(frame: pd.DataFrame, lookback: int = 20) -> dict[str, Any]:
    if frame.empty or len(frame) < 2:
        return {
            "bias": "neutral",
            "candle": [],
            "signals": ["样本不足"],
            "warnings": [],
        }

    clean = frame[["Open", "High", "Low", "Close", "Volume"]].dropna().copy()
    if len(clean) < 2:
        return {
            "bias": "neutral",
            "candle": [],
            "signals": ["样本不足"],
            "warnings": [],
        }

    latest = clean.iloc[-1]
    prior = clean.iloc[:-1].tail(lookback)
    actual_lookback = len(prior)
    prior_high = float(prior["High"].max())
    prior_low = float(prior["Low"].min())
    latest_high = float(latest["High"])
    latest_low = float(latest["Low"])
    latest_close = float(latest["Close"])
    metrics = _latest_bar_metrics(latest)
    candle = classify_latest_candle(latest)
    signals: list[str] = []
    warnings: list[str] = []
    score = 0

    if latest_high > prior_high and latest_close < prior_high:
        signals.append(f"上破{actual_lookback}日高点失败")
        warnings.append("前高假突破风险")
        score -= 2
    elif latest_close > prior_high:
        signals.append(f"收盘突破{actual_lookback}日高点")
        score += 2

    if latest_low < prior_low and latest_close > prior_low:
        signals.append(f"下破{actual_lookback}日低点收回")
        score += 2
    elif latest_close < prior_low:
        signals.append(f"收盘跌破{actual_lookback}日低点")
        warnings.append("前低失守")
        score -= 2

    recent = clean.tail(3)
    if len(recent) == 3:
        highs = recent["High"].astype(float).tolist()
        lows = recent["Low"].astype(float).tolist()
        if highs[0] < highs[1] < highs[2] and lows[0] < lows[1] < lows[2]:
            signals.append("高低点抬高")
            score += 1
        elif highs[0] > highs[1] > highs[2] and lows[0] > lows[1] > lows[2]:
            signals.append("高低点降低")
            score -= 1

    ranges = (clean["High"].astype(float) - clean["Low"].astype(float)).tail(4).tolist()
    if len(ranges) == 4 and ranges[1] > ranges[2] > ranges[3] and ranges[3] < sum(ranges[:3]) / 3:
        signals.append("波幅连续收敛")

    if "强阳收近高点" in candle:
        score += 1
    if "强阴收近低点" in candle:
        score -= 1
    if "上影线压力" in candle:
        score -= 1
    if "下影线承接" in candle:
        score += 1

    latest_volume = float(latest.get("Volume", 0) or 0)
    avg_volume = float(prior["Volume"].astype(float).mean()) if "Volume" in prior else 0.0
    volume_state = "成交量中性"
    if avg_volume > 0 and latest_volume >= avg_volume * 1.5:
        volume_state = "放量"
        if score > 0:
            signals.append("放量配合多头K线")
        elif score < 0:
            signals.append("放量配合空头K线")
        else:
            signals.append("放量换手")
    elif avg_volume > 0 and latest_volume <= avg_volume * 0.6:
        volume_state = "缩量"

    if score >= 2:
        bias = "bullish"
    elif score <= -2:
        bias = "bearish"
    elif any(signal in signals for signal in ["波幅连续收敛"]) or "十字犹豫" in candle:
        bias = "watch"
    else:
        bias = "neutral"

    if not signals:
        signals.append("区间内震荡")

    return {
        "bias": bias,
        "score": score,
        "candle": candle,
        "signals": signals,
        "warnings": warnings,
        "lookback": actual_lookback,
        "range_high": round(prior_high, 2),
        "range_low": round(prior_low, 2),
        "close_position_pct": metrics["close_position_pct"],
        "body_pct": metrics["body_pct"],
        "upper_shadow_pct": metrics["upper_shadow_pct"],
        "lower_shadow_pct": metrics["lower_shadow_pct"],
        "volume_state": volume_state,
    }


def format_price_action_summary(price_action: dict[str, Any]) -> str:
    if not price_action:
        return "暂无"
    parts: list[str] = []
    candle = price_action.get("candle") or []
    signals = price_action.get("signals") or []
    warnings = price_action.get("warnings") or []
    if candle:
        parts.append(f"K线：{'、'.join(str(item) for item in candle)}")
    if signals:
        parts.append(f"结构：{'、'.join(str(item) for item in signals)}")
    if warnings:
        parts.append(f"风险：{'、'.join(str(item) for item in warnings)}")
    if price_action.get("close_position_pct") is not None:
        parts.append(f"收盘位置：{price_action['close_position_pct']}%")
    if price_action.get("volume_state"):
        parts.append(f"量能：{price_action['volume_state']}")
    return "；".join(parts) if parts else "暂无"


def classify_patterns(patterns: list[str]) -> str:
    joined = " ".join(patterns)
    if any(key in joined for key in BULLISH_PATTERN_KEYS):
        return "bullish"
    if any(key in joined for key in BEARISH_PATTERN_KEYS):
        return "bearish"
    if any(key in joined for key in WATCH_PATTERN_KEYS):
        return "watch"
    return "neutral"


def market_timezone(market: str) -> ZoneInfo:
    return ZoneInfo("America/New_York") if market == "us" else ZoneInfo("Asia/Shanghai")


def market_close_hour(market: str) -> int:
    return 16


def trim_to_closed_bars(
    frame: pd.DataFrame,
    market: str,
    interval: str,
    now: pd.Timestamp | None = None,
) -> pd.DataFrame:
    if frame.empty:
        return frame

    tz = market_timezone(market)
    clock = now or pd.Timestamp.now(tz=tz)
    if clock.tzinfo is None:
        clock = clock.tz_localize(tz)
    else:
        clock = clock.tz_convert(tz)

    last_ts = pd.Timestamp(frame.index[-1])
    last_date = last_ts.date()
    current_date = clock.date()

    if interval == "1d" and last_date == current_date and clock.hour < market_close_hour(market):
        return frame.iloc[:-1]

    if interval == "1wk":
        current_week = clock.isocalendar()[:2]
        last_week = last_ts.isocalendar()[:2]
        before_weekly_close = clock.weekday() < 4 or (clock.weekday() == 4 and clock.hour < market_close_hour(market))
        if last_week == current_week and before_weekly_close:
            return frame.iloc[:-1]

    if interval == "1h" and len(frame) > 1:
        latest_volume = pd.to_numeric(pd.Series([frame.iloc[-1].get("Volume")]), errors="coerce").iloc[0]
        if pd.notna(latest_volume) and float(latest_volume) <= 0:
            return frame.iloc[:-1]

    return frame


def load_ohlcv(ticker: str, interval: str, period: str) -> pd.DataFrame:
    frame = yf.download(ticker, period=period, interval=interval, progress=False)
    if frame is None or getattr(frame, "empty", True):
        raise ValueError(f"{ticker} {interval} 无可用数据")
    frame = frame[["Open", "High", "Low", "Close", "Volume"]].dropna().copy()
    frame.index = pd.to_datetime(frame.index)
    frame = frame.sort_index()
    frame = trim_to_closed_bars(frame, market=classify_market(ticker), interval=interval)
    if frame.empty:
        raise ValueError(f"{ticker} {interval} 只有未收盘K线")
    return frame


def detect_price_action_patterns(frame: pd.DataFrame) -> list[str]:
    patterns = list(naked_k_patterns.detect_kline_patterns(frame))
    inside = naked_k_patterns.detect_inside_bar(frame)
    if inside:
        patterns.append(inside)
    return patterns


def resolve_weekly_context(frame: pd.DataFrame, patterns: list[str]) -> str:
    latest = frame.iloc[-1]
    recent = frame.tail(9)
    prior = recent.iloc[:-1]
    pattern_bias = classify_patterns(patterns)
    if pattern_bias == "bullish":
        return "周线偏多，允许日线多头触发"
    if pattern_bias == "bearish":
        return "周线偏空，优先过滤日线追多"

    prior_high = float(prior["High"].max()) if not prior.empty else float(latest["High"])
    prior_low = float(prior["Low"].min()) if not prior.empty else float(latest["Low"])
    range_mid = (prior_high + prior_low) / 2
    if float(latest["Close"]) >= range_mid:
        return "周线中性偏多，只接受确认后做多"
    return "周线中性偏空，等待更强确认"


def find_price_levels(frame: pd.DataFrame, close: float) -> tuple[float, float]:
    recent = frame.tail(30)
    swing_lows: list[float] = []
    swing_highs: list[float] = []
    for i in range(1, len(recent) - 1):
        low = float(recent["Low"].iloc[i])
        high = float(recent["High"].iloc[i])
        if low <= float(recent["Low"].iloc[i - 1]) and low <= float(recent["Low"].iloc[i + 1]):
            swing_lows.append(low)
        if high >= float(recent["High"].iloc[i - 1]) and high >= float(recent["High"].iloc[i + 1]):
            swing_highs.append(high)

    support_candidates = [value for value in swing_lows if value < close]
    resistance_candidates = [value for value in swing_highs if value > close]

    support = max(support_candidates) if support_candidates else float(recent["Low"].tail(10).min())
    resistance = min(resistance_candidates) if resistance_candidates else float(recent["High"].tail(10).max())
    return round(support, 2), round(resistance, 2)


def review_previous_call(previous: dict[str, Any] | None, current_bar: pd.Series, current_close: float) -> dict[str, Any]:
    if not previous:
        return {"status": "无上次记录", "error_type": None, "note": "首日运行，暂无可复盘样本"}

    action = previous.get("action")
    trigger = previous.get("entry_trigger")
    stop_loss = previous.get("stop_loss")
    high = float(current_bar["High"])
    low = float(current_bar["Low"])

    if action in BULLISH_ACTIONS:
        if trigger is not None and high >= float(trigger):
            if stop_loss is not None and low <= float(stop_loss):
                return {"status": "未命中", "error_type": "假突破", "note": "触发后回落到失效位"}
            if current_close < float(trigger):
                return {"status": "未命中", "error_type": "假突破", "note": "盘中上破但收盘未站稳触发位"}
            return {"status": "命中", "error_type": None, "note": "触发位被突破且收盘保持在其上"}
        return {"status": "未触发", "error_type": "缺少确认K", "note": "没有突破信号K高点"}

    if action in BEARISH_ACTIONS:
        if trigger is not None and low <= float(trigger):
            if stop_loss is not None and high >= float(stop_loss):
                return {"status": "未命中", "error_type": "假跌破", "note": "跌破后快速收回失效位"}
            if current_close > float(trigger):
                return {"status": "未命中", "error_type": "假跌破", "note": "盘中跌破但收盘未守住"}
            return {"status": "命中", "error_type": None, "note": "跌破触发位且收盘仍弱"}
        return {"status": "未触发", "error_type": "缺少确认K", "note": "没有跌破信号K低点"}

    return {"status": "观察中", "error_type": None, "note": "上一交易日偏观察，不计入成败"}


def build_trade_plan(
    name: str,
    ticker: str,
    daily: pd.DataFrame,
    weekly: pd.DataFrame,
    previous: dict[str, Any] | None,
    intraday: pd.DataFrame | None = None,
) -> InstrumentReport:
    daily_bar = daily.iloc[-1]
    weekly_bar = weekly.iloc[-1]
    daily_patterns = detect_price_action_patterns(daily)
    weekly_patterns = detect_price_action_patterns(weekly)
    price_action = analyze_price_action_context(daily)
    weekly_context = resolve_weekly_context(weekly, weekly_patterns)
    support, resistance = find_price_levels(daily, float(daily_bar["Close"]))
    buffer_ratio = build_volatility_buffer_ratio(daily)

    daily_bias = classify_patterns(daily_patterns)
    weekly_bias = classify_patterns(weekly_patterns)
    structure_bias = str(price_action.get("bias", "neutral"))

    if daily_bias == "bullish":
        action = "买入" if weekly_bias == "bullish" else "小仓试错"
        entry_trigger = build_breakout_trigger(daily_bar, "bullish", buffer_ratio=buffer_ratio)
        stop_loss = build_invalidation_level(daily_bar, "bullish", buffer_ratio=buffer_ratio)
    elif daily_bias == "bearish":
        action = "回避" if weekly_bias in {"bearish", "neutral"} else "减仓"
        entry_trigger = build_breakout_trigger(daily_bar, "bearish", buffer_ratio=buffer_ratio)
        stop_loss = build_invalidation_level(daily_bar, "bearish", buffer_ratio=buffer_ratio)
    elif daily_bias == "watch":
        action = "观望"
        entry_trigger = build_breakout_trigger(daily_bar, "bullish", buffer_ratio=buffer_ratio)
        stop_loss = build_invalidation_level(daily_bar, "bearish", buffer_ratio=buffer_ratio)
    elif structure_bias == "bullish":
        action = "买入" if weekly_bias == "bullish" else "小仓试错"
        entry_trigger = build_breakout_trigger(daily_bar, "bullish", buffer_ratio=buffer_ratio)
        stop_loss = build_invalidation_level(daily_bar, "bullish", buffer_ratio=buffer_ratio)
    elif structure_bias == "bearish":
        action = "回避" if weekly_bias in {"bearish", "neutral"} else "减仓"
        entry_trigger = build_breakout_trigger(daily_bar, "bearish", buffer_ratio=buffer_ratio)
        stop_loss = build_invalidation_level(daily_bar, "bearish", buffer_ratio=buffer_ratio)
    else:
        action = "观望"
        entry_trigger = round(resistance * 1.002, 2)
        stop_loss = round(support * 0.998, 2)

    target_price, risk_per_share, reward_to_risk = build_trade_metrics(
        action,
        entry_trigger,
        stop_loss,
        resistance,
        support,
    )
    action, target_price, reward_to_risk, reward_filter_note = downgrade_low_reward_setup(
        action,
        target_price,
        reward_to_risk,
    )
    position_size = build_position_guidance(action, entry_trigger, stop_loss)
    signal_state = build_signal_state(action)
    intraday_status = build_intraday_status(intraday, action, entry_trigger, stop_loss)
    review = review_previous_call(previous, daily_bar, float(daily_bar["Close"]))
    rationale_parts = [
        f"日线形态：{'、'.join(daily_patterns) if daily_patterns else '无明确信号'}",
        f"周线背景：{'、'.join(weekly_patterns) if weekly_patterns else '无明确信号'}",
        weekly_context,
        f"裸K结构：{format_price_action_summary(price_action)}",
        f"ATR缓冲：{buffer_ratio * 100:.2f}%",
        "改进：多头/空头都要求先突破信号K极值再触发，减少无确认追价。",
    ]
    if reward_filter_note:
        rationale_parts.append(f"改进：{reward_filter_note}")

    return InstrumentReport(
        name=name,
        ticker=ticker,
        action=action,
        entry_trigger=entry_trigger,
        stop_loss=stop_loss,
        target_price=target_price,
        risk_per_share=risk_per_share,
        reward_to_risk=reward_to_risk,
        signal_state=signal_state,
        resistance=resistance,
        support=support,
        position_size=position_size,
        rationale="；".join(rationale_parts),
        daily_patterns=daily_patterns,
        weekly_patterns=weekly_patterns,
        weekly_context=weekly_context,
        data_sources={
            "daily": str(daily.attrs.get("source", "unknown")),
            "weekly": str(weekly.attrs.get("source", "unknown")),
        },
        latest_k_dates={
            "daily": daily.index[-1].strftime("%Y-%m-%d"),
            "weekly": weekly.index[-1].strftime("%Y-%m-%d"),
        },
        latest_closes={
            "daily": round(float(daily_bar["Close"]), 2),
            "weekly": round(float(weekly_bar["Close"]), 2),
        },
        review=review,
        improvement="新增裸K结构读线：识别影线、收盘位置、前高/前低突破或失败，再用确认K触发。",
        intraday_status=intraday_status,
        price_action=price_action,
    )


def load_journal(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def latest_journal_entry(
    rows: list[dict[str, Any]],
    ticker: str,
    current_daily_date: str | None = None,
) -> dict[str, Any] | None:
    matches = [row for row in rows if row.get("ticker") == ticker]
    if current_daily_date is not None:
        current_ts = pd.Timestamp(current_daily_date)
        matches = [
            row
            for row in matches
            if (
                (row.get("latest_k_dates") or {}).get("daily")
                and pd.Timestamp((row.get("latest_k_dates") or {}).get("daily")) < current_ts
            )
        ]
    return matches[-1] if matches else None


def append_journal(path: Path, run_date: str, report: InstrumentReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_date": run_date,
        "name": report.name,
        "ticker": report.ticker,
        "action": report.action,
        "entry_trigger": report.entry_trigger,
        "stop_loss": report.stop_loss,
        "target_price": report.target_price,
        "risk_per_share": report.risk_per_share,
        "reward_to_risk": report.reward_to_risk,
        "signal_state": report.signal_state,
        "resistance": report.resistance,
        "support": report.support,
        "position_size": report.position_size,
        "daily_patterns": report.daily_patterns,
        "weekly_patterns": report.weekly_patterns,
        "weekly_context": report.weekly_context,
        "data_sources": report.data_sources,
        "latest_k_dates": report.latest_k_dates,
        "latest_closes": report.latest_closes,
        "review": report.review,
        "improvement": report.improvement,
        "intraday_status": report.intraday_status,
        "price_action": report.price_action,
    }
    rows = load_journal(path)
    match_key = (report.ticker, report.latest_k_dates["daily"])
    rows = [
        row
        for row in rows
        if (row.get("ticker"), (row.get("latest_k_dates") or {}).get("daily")) != match_key
    ]
    rows.append(payload)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def format_report(run_date: str, reports: list[InstrumentReport], journal_path: Path) -> str:
    sections = [
        f"# 裸K收盘报告",
        f"生成日期：{run_date}",
        f"日志：{journal_path}",
        "",
    ]
    for report in reports:
        target_text = str(report.target_price) if report.target_price is not None else "暂无"
        reward_to_risk_text = f"{report.reward_to_risk}R" if report.reward_to_risk is not None else "暂无"
        intraday = report.intraday_status or {"status": "无盘中数据", "note": "未获取到1h盘中K线"}
        intraday_detail = []
        if intraday.get("latest_time"):
            intraday_detail.append(str(intraday["latest_time"]))
        if intraday.get("latest_close") is not None:
            intraday_detail.append(f"最新{intraday['latest_close']}")
        if intraday.get("source"):
            intraday_detail.append(f"source={intraday['source']}")
        intraday_note = str(intraday.get("note") or "")
        intraday_line = f"{intraday.get('status', '无盘中数据')}"
        if intraday_detail:
            intraday_line += f"（{'，'.join(intraday_detail)}）"
        if intraday_note:
            intraday_line += f"；{intraday_note}"
        sections.extend(
            [
                f"## {report.name} {report.ticker}",
                f"- 数据源：日线 `{report.data_sources['daily']}`，周线 `{report.data_sources['weekly']}`",
                f"- 最新K线：日线 {report.latest_k_dates['daily']} 收 {report.latest_closes['daily']}；周线 {report.latest_k_dates['weekly']} 收 {report.latest_closes['weekly']}",
                f"- 当前动作：{report.action}",
                f"- 信号状态：{report.signal_state}",
                f"- 入场触发位：{report.entry_trigger}",
                f"- 失效/止损位：{report.stop_loss}",
                f"- 第一目标位：{target_text}",
                f"- 单股风险：{report.risk_per_share}",
                f"- 目标盈亏比：{reward_to_risk_text}",
                f"- 盘中状态：{intraday_line}",
                f"- 裸K解读：{format_price_action_summary(report.price_action)}",
                f"- 上方压力：{report.resistance}",
                f"- 下方支撑：{report.support}",
                f"- 仓位建议：{report.position_size}",
                f"- 理由：{report.rationale}",
                f"- 复盘：{report.review['status']}；错误类型：{report.review['error_type'] or '无'}；备注：{report.review['note']}",
                f"- 持续优化：{report.improvement}",
                "",
            ]
        )

    ranked = sorted(
        reports,
        key=lambda item: {"买入": 0, "小仓试错": 1, "观望": 2, "减仓": 3, "回避": 4}.get(item.action, 9),
    )
    best_trial = next((item for item in ranked if item.action in {"买入", "小仓试错"}), None)
    best_trial_text = (
        f"{best_trial.name}（{best_trial.action}）"
        if best_trial is not None
        else "暂无（无满足触发条件标的）"
    )
    sections.extend(
        [
            "## 今日结论",
            f"- 最值得试错：{best_trial_text}",
            f"- 继续观察：{next((item.name for item in ranked if item.action == '观望'), ranked[1].name if len(ranked) > 1 else ranked[0].name)}",
            f"- 需要回避：{next((item.name for item in ranked if item.action in {'回避', '减仓'}), ranked[-1].name)}",
            "",
            "不构成投资建议；以上仅作交易辅助。",
        ]
    )
    return "\n".join(sections)


def run_analysis(tickers: list[tuple[str, str]], journal_path: Path) -> tuple[str, list[InstrumentReport]]:
    journal_rows = load_journal(journal_path)
    reports: list[InstrumentReport] = []
    run_date = pd.Timestamp.now(tz="Asia/Shanghai").strftime("%Y-%m-%d %H:%M:%S %Z")

    for name, ticker in tickers:
        daily = load_ohlcv(ticker, interval="1d", period="18mo")
        weekly = load_ohlcv(ticker, interval="1wk", period="5y")
        try:
            intraday = load_ohlcv(ticker, interval="1h", period="5d")
        except Exception:
            intraday = None
        previous = latest_journal_entry(
            journal_rows,
            ticker,
            current_daily_date=daily.index[-1].strftime("%Y-%m-%d"),
        )
        report = build_trade_plan(name, ticker, daily, weekly, previous, intraday=intraday)
        append_journal(journal_path, run_date, report)
        reports.append(report)

    return format_report(run_date, reports, journal_path), reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成固定标的的裸K收盘报告")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--journal-path", default=str(DEFAULT_JOURNAL_PATH), help="复盘日志路径")
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH), help="Markdown 报告输出路径")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    journal_path = Path(args.journal_path)
    report_path = Path(args.report_path)
    report_text, reports = run_analysis(DEFAULT_TICKERS, journal_path)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")

    if args.json:
        payload = {"report": report_text, "items": [asdict(item) for item in reports], "report_path": str(report_path)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(report_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
