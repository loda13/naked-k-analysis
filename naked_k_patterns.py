from __future__ import annotations

from typing import Any

import pandas as pd


def _bar_value(bar: pd.Series, key: str) -> float:
    return float(bar[key])


def detect_engulfing(frame: pd.DataFrame) -> str | None:
    if len(frame) < 2:
        return None

    latest = frame.iloc[-1]
    previous = frame.iloc[-2]
    open_price = _bar_value(latest, "Open")
    close = _bar_value(latest, "Close")
    previous_open = _bar_value(previous, "Open")
    previous_close = _bar_value(previous, "Close")
    body = abs(close - open_price)
    previous_body = abs(previous_close - previous_open)

    if close > open_price and previous_close < previous_open and close > previous_open and open_price < previous_close and body > previous_body:
        return "🟢看涨吸收"

    if close < open_price and previous_close > previous_open and close < previous_open and open_price > previous_close and body > previous_body:
        return "🔴看跌吸收"

    return None


def detect_pin_bar(frame: pd.DataFrame, tail_ratio: float = 2.0) -> str | None:
    if len(frame) < 2:
        return None

    latest = frame.iloc[-1]
    open_price = _bar_value(latest, "Open")
    close = _bar_value(latest, "Close")
    high = _bar_value(latest, "High")
    low = _bar_value(latest, "Low")
    body = abs(close - open_price)
    full_range = high - low
    if full_range == 0 or body > full_range * 0.5:
        return None

    upper_shadow = high - max(open_price, close)
    lower_shadow = min(open_price, close) - low

    if upper_shadow > body * tail_ratio and upper_shadow > lower_shadow * 1.5:
        return "📌看跌Pin"

    if lower_shadow > body * tail_ratio and lower_shadow > upper_shadow * 1.5:
        return "📌看涨Pin"

    return None


def detect_doji(frame: pd.DataFrame, body_ratio: float = 0.1) -> str | None:
    if len(frame) < 2:
        return None

    latest = frame.iloc[-1]
    open_price = _bar_value(latest, "Open")
    close = _bar_value(latest, "Close")
    high = _bar_value(latest, "High")
    low = _bar_value(latest, "Low")
    body = abs(close - open_price)
    full_range = high - low
    if full_range == 0 or body >= full_range * body_ratio:
        return None

    upper_shadow = high - max(open_price, close)
    lower_shadow = min(open_price, close) - low
    if upper_shadow > lower_shadow * 2:
        return "⚡墓碑十字(偏空)"
    if lower_shadow > upper_shadow * 2:
        return "⚡蜻蜓十字(偏多)"
    return "⚡十字星"


def detect_hammer_shooting_star(frame: pd.DataFrame) -> str | None:
    if len(frame) < 2:
        return None

    latest = frame.iloc[-1]
    open_price = _bar_value(latest, "Open")
    close = _bar_value(latest, "Close")
    high = _bar_value(latest, "High")
    low = _bar_value(latest, "Low")
    body = abs(close - open_price)
    full_range = high - low
    if full_range == 0:
        return None

    upper_shadow = high - max(open_price, close)
    lower_shadow = min(open_price, close) - low

    if lower_shadow > body * 2 and upper_shadow < body * 0.5 and close > open_price:
        return "🟢锤子线"

    if upper_shadow > body * 2 and lower_shadow < body * 0.5 and close < open_price:
        return "🔴射击之星"

    return None


def detect_morning_evening_star(frame: pd.DataFrame) -> str | None:
    if len(frame) < 3:
        return None

    third_last = frame.iloc[-3]
    previous = frame.iloc[-2]
    latest = frame.iloc[-1]

    previous_body = abs(_bar_value(previous, "Close") - _bar_value(previous, "Open"))
    previous_range = _bar_value(previous, "High") - _bar_value(previous, "Low")
    if previous_range <= 0:
        return None

    if (
        _bar_value(third_last, "Close") > _bar_value(third_last, "Open")
        and previous_body < previous_range * 0.3
        and _bar_value(latest, "Close") < _bar_value(latest, "Open")
        and _bar_value(latest, "Close") < _bar_value(third_last, "Open")
    ):
        return "🔴黄昏星"

    if (
        _bar_value(third_last, "Close") < _bar_value(third_last, "Open")
        and previous_body < previous_range * 0.3
        and _bar_value(latest, "Close") > _bar_value(latest, "Open")
        and _bar_value(latest, "Close") > _bar_value(third_last, "Open")
    ):
        return "🟢早晨星"

    return None


def detect_inside_bar(frame: pd.DataFrame) -> str | None:
    if len(frame) < 3:
        return None

    latest = frame.iloc[-1]
    previous = frame.iloc[-2]
    if _bar_value(latest, "High") < _bar_value(previous, "High") and _bar_value(latest, "Low") > _bar_value(previous, "Low"):
        previous_bullish = _bar_value(previous, "Close") > _bar_value(previous, "Open")
        latest_bullish = _bar_value(latest, "Close") > _bar_value(latest, "Open")
        if previous_bullish and not latest_bullish:
            return "🟡孕线(阳孕阴)"
        if not previous_bullish and latest_bullish:
            return "🟡孕线(阴孕阳)"
        return "🟡双孕线"
    return None


def detect_kline_patterns(frame: pd.DataFrame) -> list[str]:
    detectors: tuple[Any, ...] = (
        detect_engulfing,
        detect_pin_bar,
        detect_doji,
        detect_hammer_shooting_star,
        detect_morning_evening_star,
    )
    results: list[str] = []
    for detector in detectors:
        pattern = detector(frame)
        if pattern:
            results.append(pattern)
    return results
