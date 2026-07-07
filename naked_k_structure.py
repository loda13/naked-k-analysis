from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class SwingPoint:
    kind: str
    date: str
    position: int
    price: float


def _clean_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    columns = [column for column in ["Open", "High", "Low", "Close", "Volume"] if column in frame.columns]
    clean = frame[columns].dropna().copy()
    clean.index = pd.to_datetime(clean.index)
    return clean.sort_index()


def _format_date(value: Any) -> str:
    ts = pd.Timestamp(value)
    if ts.hour or ts.minute or ts.second:
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    return ts.strftime("%Y-%m-%d")


def _point_to_dict(point: SwingPoint | None) -> dict[str, Any] | None:
    if point is None:
        return None
    return asdict(point)


def find_swing_points(frame: pd.DataFrame, window: int = 2) -> list[SwingPoint]:
    clean = _clean_ohlcv(frame)
    if len(clean) < window * 2 + 1:
        return []

    highs = clean["High"].astype(float)
    lows = clean["Low"].astype(float)
    points: list[SwingPoint] = []
    for position in range(window, len(clean) - window):
        high_window = highs.iloc[position - window : position + window + 1]
        low_window = lows.iloc[position - window : position + window + 1]
        high = float(highs.iloc[position])
        low = float(lows.iloc[position])
        neighbor_highs = high_window.drop(high_window.index[window])
        neighbor_lows = low_window.drop(low_window.index[window])
        date = _format_date(clean.index[position])

        if high == float(high_window.max()) and high > float(neighbor_highs.max()):
            points.append(SwingPoint("high", date, position, round(high, 2)))
        if low == float(low_window.min()) and low < float(neighbor_lows.min()):
            points.append(SwingPoint("low", date, position, round(low, 2)))

    return points


def _summarize_swings(swings: list[SwingPoint]) -> dict[str, Any]:
    highs = [point for point in swings if point.kind == "high"]
    lows = [point for point in swings if point.kind == "low"]
    last_high = highs[-1] if highs else None
    previous_high = highs[-2] if len(highs) >= 2 else None
    last_low = lows[-1] if lows else None
    previous_low = lows[-2] if len(lows) >= 2 else None

    direction = "neutral"
    sequence = "样本不足"
    strength = "weak"
    if previous_high and last_high and previous_low and last_low:
        higher_high = last_high.price > previous_high.price
        higher_low = last_low.price > previous_low.price
        lower_high = last_high.price < previous_high.price
        lower_low = last_low.price < previous_low.price
        if higher_high and higher_low:
            direction = "up"
            sequence = "HH/HL"
            strength = "confirmed"
        elif lower_high and lower_low:
            direction = "down"
            sequence = "LH/LL"
            strength = "confirmed"
        elif higher_high and lower_low:
            direction = "expanding_range"
            sequence = "HH/LL"
        elif lower_high and higher_low:
            direction = "contracting_range"
            sequence = "LH/HL"
        else:
            direction = "sideways"
            sequence = "mixed"
    elif last_high or last_low:
        sequence = "结构形成中"

    return {
        "direction": direction,
        "sequence": sequence,
        "strength": strength,
        "last_swing_high": _point_to_dict(last_high),
        "last_swing_low": _point_to_dict(last_low),
        "previous_swing_high": _point_to_dict(previous_high),
        "previous_swing_low": _point_to_dict(previous_low),
        "swing_count": len(swings),
    }


def _detect_structure_event(clean: pd.DataFrame, prior_summary: dict[str, Any]) -> dict[str, Any] | None:
    if clean.empty:
        return None

    latest = clean.iloc[-1]
    latest_close = float(latest["Close"])
    latest_date = _format_date(clean.index[-1])
    prior_direction = str(prior_summary.get("direction", "neutral"))
    last_high = prior_summary.get("last_swing_high")
    last_low = prior_summary.get("last_swing_low")

    if last_high and latest_close > float(last_high["price"]):
        kind = "CHoCH" if prior_direction == "down" else "BOS"
        return {
            "kind": kind,
            "direction": "bullish",
            "date": latest_date,
            "broken_level": round(float(last_high["price"]), 2),
            "close": round(latest_close, 2),
        }

    if last_low and latest_close < float(last_low["price"]):
        kind = "CHoCH" if prior_direction == "up" else "BOS"
        return {
            "kind": kind,
            "direction": "bearish",
            "date": latest_date,
            "broken_level": round(float(last_low["price"]), 2),
            "close": round(latest_close, 2),
        }

    return None


def analyze_market_structure(frame: pd.DataFrame, swing_window: int = 2) -> dict[str, Any]:
    clean = _clean_ohlcv(frame)
    if len(clean) < swing_window * 2 + 2:
        return {
            "direction": "neutral",
            "prior_direction": "neutral",
            "sequence": "样本不足",
            "strength": "weak",
            "latest_event": None,
            "last_swing_high": None,
            "last_swing_low": None,
            "swing_count": 0,
        }

    swings = find_swing_points(clean, window=swing_window)
    summary = _summarize_swings(swings)
    prior_clean = clean.iloc[:-1]
    prior_summary = _summarize_swings(find_swing_points(prior_clean, window=swing_window))
    event = _detect_structure_event(clean, prior_summary)
    direction = str(summary["direction"])
    if event and event["kind"] == "CHoCH":
        direction = "transition"

    summary.update(
        {
            "direction": direction,
            "prior_direction": prior_summary["direction"],
            "latest_event": event,
        }
    )
    return summary


def classify_market_regime(
    frame: pd.DataFrame,
    structure: dict[str, Any] | None = None,
    lookback: int = 20,
) -> dict[str, Any]:
    clean = _clean_ohlcv(frame)
    if len(clean) < 3:
        return {
            "state": "unknown",
            "label": "状态未知",
            "direction": "neutral",
            "range_ratio": None,
        }

    ranges = (clean["High"].astype(float) - clean["Low"].astype(float)).tail(lookback)
    latest_range = float(ranges.iloc[-1])
    average_range = float(ranges.mean())
    range_ratio = latest_range / average_range if average_range > 0 else 1.0
    if structure is None:
        structure = analyze_market_structure(clean)

    structure_direction = str(structure.get("direction", "neutral"))
    if range_ratio >= 1.8:
        state = "high_volatility"
        label = "高波动市场"
        direction = "neutral"
    elif range_ratio <= 0.7:
        state = "low_volatility_compression"
        label = "低波动压缩"
        direction = "neutral"
    elif structure_direction == "up":
        state = "trend"
        label = "趋势市场"
        direction = "bullish"
    elif structure_direction == "down":
        state = "trend"
        label = "趋势市场"
        direction = "bearish"
    elif structure_direction == "transition":
        state = "transition"
        label = "结构转换"
        event = structure.get("latest_event") or {}
        direction = str(event.get("direction", "neutral"))
    else:
        state = "range"
        label = "震荡市场"
        direction = "neutral"

    return {
        "state": state,
        "label": label,
        "direction": direction,
        "range_ratio": round(range_ratio, 2),
        "average_range": round(average_range, 2),
        "latest_range": round(latest_range, 2),
    }
