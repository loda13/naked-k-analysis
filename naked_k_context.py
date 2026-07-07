from __future__ import annotations

from typing import Any

import pandas as pd

import naked_k_patterns


def _clean_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    clean = frame[["Open", "High", "Low", "Close", "Volume"]].dropna().copy()
    clean.index = pd.to_datetime(clean.index)
    return clean.sort_index()


def _latest_metrics(clean: pd.DataFrame) -> dict[str, float]:
    latest = clean.iloc[-1]
    open_price = float(latest["Open"])
    high = float(latest["High"])
    low = float(latest["Low"])
    close = float(latest["Close"])
    candle_range = max(high - low, 0.0)
    body = abs(close - open_price)
    upper_wick = max(high - max(open_price, close), 0.0)
    lower_wick = max(min(open_price, close) - low, 0.0)
    if candle_range <= 0:
        return {
            "body_pct": 0.0,
            "upper_wick_pct": 0.0,
            "lower_wick_pct": 0.0,
            "close_position_pct": 50.0,
        }
    return {
        "body_pct": round(body / candle_range * 100, 1),
        "upper_wick_pct": round(upper_wick / candle_range * 100, 1),
        "lower_wick_pct": round(lower_wick / candle_range * 100, 1),
        "close_position_pct": round((close - low) / candle_range * 100, 1),
    }


def _pattern_list(clean: pd.DataFrame) -> list[str]:
    patterns = list(naked_k_patterns.detect_kline_patterns(clean))
    inside = naked_k_patterns.detect_inside_bar(clean)
    if inside:
        patterns.append(inside)
    return patterns


def _direction_from_pattern(pattern: str, price_action: dict[str, Any]) -> str:
    if "孕线" in pattern:
        return "watch"
    if "看涨" in pattern or "锤子" in pattern or "早晨" in pattern or "蜻蜓" in pattern or "阴孕阳" in pattern:
        return "bullish"
    if "看跌" in pattern or "射击" in pattern or "黄昏" in pattern or "墓碑" in pattern or "阳孕阴" in pattern:
        return "bearish"
    if str(price_action.get("bias")) in {"bullish", "bearish", "watch"}:
        return str(price_action["bias"])
    return "watch"


def _behavior_from_pattern(pattern: str) -> str:
    if "Pin" in pattern or "锤子" in pattern or "射击" in pattern:
        return "pin_bar"
    if "吸收" in pattern:
        return "engulfing"
    if "孕线" in pattern:
        return "inside_bar"
    if "十字" in pattern:
        return "doji"
    return "candle_pattern"


def _location(direction: str, price_zones: dict[str, Any], price_action: dict[str, Any]) -> str:
    signals = " ".join(str(item) for item in price_action.get("signals", []))
    if direction == "bullish" and ("下破" in signals or price_zones.get("nearest_support")):
        return "support_liquidity"
    if direction == "bearish" and ("上破" in signals or price_zones.get("nearest_resistance")):
        return "resistance_liquidity"
    if price_zones.get("nearest_support") or price_zones.get("nearest_resistance"):
        return "near_price_zone"
    return "mid_range"


def _volume_context(price_action: dict[str, Any]) -> str:
    pressure = str(price_action.get("volume_pressure", ""))
    state = str(price_action.get("volume_state", ""))
    signals = " ".join(str(item) for item in price_action.get("signals", []))
    if pressure in {"承接增强", "派发压力"} or "放量下破收回" in signals or "放量上破失败" in signals:
        return "volume_absorption"
    if pressure == "量价确认":
        return "volume_confirmation"
    if state == "缩量":
        return "low_volume"
    return "neutral_volume"


def _volatility_context(price_action: dict[str, Any]) -> str:
    state = str(price_action.get("volatility_state", ""))
    signals = " ".join(str(item) for item in price_action.get("signals", []))
    if "压缩" in state or "收敛" in signals:
        return "compression"
    if "扩张" in state:
        return "expansion"
    if "宽幅" in state:
        return "wide_range"
    return "normal"


def _structure_context(direction: str, market_structure: dict[str, Any]) -> str:
    event = market_structure.get("latest_event") or {}
    event_kind = str(event.get("kind", "")).lower()
    event_direction = str(event.get("direction", ""))
    if event_kind == "choch" and event_direction == direction:
        return f"{direction}_choch"
    if event_kind == "bos" and event_direction == direction:
        return f"{direction}_bos"
    sequence = str(market_structure.get("sequence", ""))
    if direction == "bullish" and sequence == "HH/HL":
        return "bullish_structure"
    if direction == "bearish" and sequence == "LH/LL":
        return "bearish_structure"
    return "context_mixed"


def _quality_score(
    behavior: str,
    direction: str,
    location: str,
    volume_context: str,
    volatility_context: str,
    structure_context: str,
    metrics: dict[str, float],
) -> int:
    score = 3
    if location in {"support_liquidity", "resistance_liquidity"}:
        score += 2
    if volume_context in {"volume_absorption", "volume_confirmation"}:
        score += 2
    if volatility_context in {"expansion", "wide_range", "compression"}:
        score += 1
    if structure_context.endswith(("choch", "bos")) or structure_context.endswith("structure"):
        score += 2
    if direction == "bullish" and metrics["lower_wick_pct"] >= 45 and metrics["close_position_pct"] >= 65:
        score += 1
    if direction == "bearish" and metrics["upper_wick_pct"] >= 45 and metrics["close_position_pct"] <= 35:
        score += 1
    if behavior == "inside_bar" and volume_context == "low_volume":
        score += 1
    return max(1, min(10, score))


def _interpretation(behavior: str, direction: str, location: str, volume_context: str) -> str:
    if behavior == "liquidity_sweep" and direction == "bullish":
        return "价格扫过前低流动性后收回，空头突破失败，多头在低位吸收卖压"
    if behavior == "liquidity_sweep" and direction == "bearish":
        return "价格扫过前高流动性后回落，多头突破失败，卖盘在高位压制延续"
    if behavior == "inside_bar":
        return "价格进入母线内部压缩，方向未确认，不能把孕线本身当作交易信号"
    if direction == "bullish" and location == "support_liquidity":
        return "看涨K线发生在支撑/流动性区域，若后续收盘确认，说明承接开始占优"
    if direction == "bearish" and location == "resistance_liquidity":
        return "看跌K线发生在压力/流动性区域，若后续收盘确认，说明派发压力增强"
    if volume_context == "volume_confirmation":
        return "形态与量价方向一致，但仍需等待触发位确认"
    return "单根K线只作为行为线索，需要结构位置和后续确认共同验证"


def _confirmation(behavior: str, direction: str) -> str:
    if behavior == "inside_bar":
        return "等待母线高低点被收盘突破，再按突破方向处理"
    if direction == "bullish":
        return "等待下一根K线收盘站上信号K高点或小周期形成HL后再触发"
    if direction == "bearish":
        return "等待下一根K线收盘跌破信号K低点或小周期形成LH后再触发"
    return "等待收盘突破区间边界"


def _base_context(
    behavior: str,
    pattern: str,
    direction: str,
    price_action: dict[str, Any],
    market_structure: dict[str, Any],
    price_zones: dict[str, Any],
    metrics: dict[str, float],
) -> dict[str, Any]:
    location = _location(direction, price_zones, price_action)
    volume_context = _volume_context(price_action)
    volatility_context = _volatility_context(price_action)
    structure_context = _structure_context(direction, market_structure)
    quality_score = _quality_score(
        behavior,
        direction,
        location,
        volume_context,
        volatility_context,
        structure_context,
        metrics,
    )
    return {
        "behavior": behavior,
        "pattern": pattern,
        "direction": direction,
        "location": location,
        "wick_quality": {
            "upper_wick_pct": metrics["upper_wick_pct"],
            "lower_wick_pct": metrics["lower_wick_pct"],
        },
        "close_quality": {
            "close_position_pct": metrics["close_position_pct"],
            "body_pct": metrics["body_pct"],
        },
        "volume_context": volume_context,
        "volatility_context": volatility_context,
        "structure_context": structure_context,
        "quality_score": quality_score,
        "interpretation": _interpretation(behavior, direction, location, volume_context),
        "confirmation": _confirmation(behavior, direction),
    }


def _sweep_context(
    price_action: dict[str, Any],
    market_structure: dict[str, Any],
    price_zones: dict[str, Any],
    metrics: dict[str, float],
) -> dict[str, Any] | None:
    signals = " ".join(str(item) for item in price_action.get("signals", []))
    warnings = " ".join(str(item) for item in price_action.get("warnings", []))
    if "下破" in signals and "收回" in signals:
        return _base_context(
            "liquidity_sweep",
            "下破收回",
            "bullish",
            price_action,
            market_structure,
            price_zones,
            metrics,
        )
    if ("上破" in signals and "失败" in signals) or "上破失败" in warnings:
        return _base_context(
            "liquidity_sweep",
            "上破失败",
            "bearish",
            price_action,
            market_structure,
            price_zones,
            metrics,
        )
    return None


def build_candle_behavior_context(
    frame: pd.DataFrame,
    price_action: dict[str, Any] | None = None,
    market_structure: dict[str, Any] | None = None,
    price_zones: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    clean = _clean_ohlcv(frame)
    if len(clean) < 2:
        return []

    price_action = price_action or {}
    market_structure = market_structure or {}
    price_zones = price_zones or {}
    metrics = _latest_metrics(clean)
    contexts: list[dict[str, Any]] = []
    seen_behaviors: set[str] = set()

    sweep = _sweep_context(price_action, market_structure, price_zones, metrics)
    if sweep is not None:
        contexts.append(sweep)
        seen_behaviors.add(sweep["behavior"])

    for pattern in _pattern_list(clean):
        direction = _direction_from_pattern(pattern, price_action)
        behavior = _behavior_from_pattern(pattern)
        if behavior in seen_behaviors and behavior != "inside_bar":
            continue
        contexts.append(
            _base_context(
                behavior,
                pattern,
                direction,
                price_action,
                market_structure,
                price_zones,
                metrics,
            )
        )
        seen_behaviors.add(behavior)

    if not contexts and str(price_action.get("bias")) in {"bullish", "bearish", "watch"}:
        direction = str(price_action["bias"])
        contexts.append(
            _base_context(
                "price_action_signal",
                "价格行为",
                direction,
                price_action,
                market_structure,
                price_zones,
                metrics,
            )
        )

    def sort_key(item: dict[str, Any]) -> tuple[int, int]:
        behavior = str(item.get("behavior", ""))
        volatility = str(item.get("volatility_context", ""))
        if behavior == "liquidity_sweep":
            priority = 3
        elif behavior == "inside_bar" and volatility == "compression":
            priority = 2
        else:
            priority = 1
        return priority, int(item.get("quality_score", 0))

    return sorted(contexts, key=sort_key, reverse=True)


def format_candle_context_summary(contexts: list[dict[str, Any]]) -> str:
    if not contexts:
        return "暂无"
    parts: list[str] = []
    for context in contexts[:3]:
        parts.append(
            (
                f"{context.get('pattern')}->{context.get('behavior')}"
                f"({context.get('direction')}, {context.get('location')}, "
                f"score={context.get('quality_score')})：{context.get('interpretation')}"
            )
        )
    return "；".join(parts)
