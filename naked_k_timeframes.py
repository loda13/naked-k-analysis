from __future__ import annotations

from typing import Any

import pandas as pd

import naked_k_structure
import naked_k_trade


TIMEFRAME_LABELS = {
    "macro": "月线",
    "structure": "周线",
    "opportunity": "日线",
}


def _clean_ohlcv(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or getattr(frame, "empty", True):
        return pd.DataFrame()
    columns = [column for column in ["Open", "High", "Low", "Close", "Volume"] if column in frame.columns]
    clean = frame[columns].dropna().copy()
    clean.index = pd.to_datetime(clean.index)
    return clean.sort_index()


def _slope_direction(clean: pd.DataFrame) -> str:
    if len(clean) < 2:
        return "neutral"
    closes = clean["Close"].astype(float).tail(min(6, len(clean))).tolist()
    rising = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i - 1])
    falling = sum(1 for i in range(1, len(closes)) if closes[i] < closes[i - 1])
    if closes[-1] > closes[0] and rising >= falling:
        return "bullish"
    if closes[-1] < closes[0] and falling >= rising:
        return "bearish"
    return "neutral"


def _direction(
    clean: pd.DataFrame,
    price_action: dict[str, Any],
    structure: dict[str, Any],
    regime: dict[str, Any],
) -> str:
    regime_direction = str(regime.get("direction") or "neutral")
    if regime_direction in {"bullish", "bearish"}:
        return regime_direction

    event = structure.get("latest_event") or {}
    event_direction = str(event.get("direction") or "neutral")
    if event_direction in {"bullish", "bearish"}:
        return event_direction

    structure_direction = str(structure.get("direction") or "neutral")
    if structure_direction == "up":
        return "bullish"
    if structure_direction == "down":
        return "bearish"

    action_bias = str(price_action.get("bias") or "neutral")
    if action_bias in {"bullish", "bearish"}:
        return action_bias

    return _slope_direction(clean)


def _snapshot(
    key: str,
    role: str,
    frame: pd.DataFrame | None,
    price_action: dict[str, Any] | None = None,
    structure: dict[str, Any] | None = None,
    regime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean = _clean_ohlcv(frame)
    if clean.empty:
        return {
            "timeframe": TIMEFRAME_LABELS[key],
            "role": role,
            "status": "missing",
            "direction": "neutral",
            "summary": "无可用K线",
        }

    if price_action is None:
        price_action = naked_k_trade.analyze_price_action_context(clean)
    if structure is None:
        structure = naked_k_structure.analyze_market_structure(clean, swing_window=1)
    if regime is None:
        regime = naked_k_structure.classify_market_regime(clean, structure)

    direction = _direction(clean, price_action, structure, regime)
    return {
        "timeframe": TIMEFRAME_LABELS[key],
        "role": role,
        "status": "ready",
        "direction": direction,
        "latest_date": pd.Timestamp(clean.index[-1]).strftime("%Y-%m-%d"),
        "latest_close": round(float(clean["Close"].iloc[-1]), 2),
        "structure": structure,
        "regime": regime,
        "price_action": price_action,
        "summary": "；".join(
            [
                naked_k_trade.format_market_regime_summary(regime),
                naked_k_trade.format_market_structure_summary(structure),
                naked_k_trade.format_price_action_summary(price_action),
            ]
        ),
    }


def _direction_text(direction: str) -> str:
    return {
        "bullish": "偏多",
        "bearish": "偏空",
        "neutral": "中性",
        "watch": "观察",
    }.get(direction, direction)


def _alignment(macro_direction: str, structure_direction: str, opportunity_direction: str) -> tuple[str, str]:
    higher = [direction for direction in [macro_direction, structure_direction] if direction in {"bullish", "bearish"}]
    if opportunity_direction == "bullish":
        if "bearish" in higher:
            return "conflict", "日线机会与高周期方向冲突，只允许降仓试错或等待周线重新确认"
        if "bullish" in higher:
            return "aligned_long", "大周期方向与中周期结构支持日线多头机会，等待小周期触发确认"
    if opportunity_direction == "bearish":
        if "bullish" in higher:
            return "conflict", "日线机会与高周期方向冲突，优先视为回撤或风险预警"
        if "bearish" in higher:
            return "aligned_short", "大周期方向与中周期结构支持空头/回避计划，等待小周期跌破确认"
    if opportunity_direction in {"watch", "neutral"}:
        return "waiting", "日线未给出明确机会，等待区间边界、BOS/CHoCH 或压缩扩张"
    return "mixed", "多周期信号不完整，降低仓位并等待更清晰的结构证据"


def build_timeframe_context(
    monthly: pd.DataFrame | None,
    weekly: pd.DataFrame,
    daily: pd.DataFrame,
    intraday_status: dict[str, Any] | None = None,
    daily_price_action: dict[str, Any] | None = None,
    daily_structure: dict[str, Any] | None = None,
    daily_regime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    macro = _snapshot("macro", "长期方向", monthly)
    structure = _snapshot("structure", "主要结构", weekly)
    opportunity = _snapshot(
        "opportunity",
        "交易机会",
        daily,
        price_action=daily_price_action,
        structure=daily_structure,
        regime=daily_regime,
    )
    trigger = {
        "timeframe": "1H",
        "role": "入场触发",
        "status": (intraday_status or {}).get("status", "无盘中数据"),
        "note": (intraday_status or {}).get("note", "未获取到1h盘中K线"),
    }

    alignment, decision_filter = _alignment(
        str(macro["direction"]),
        str(structure["direction"]),
        str(opportunity["direction"]),
    )
    framework = (
        f"大周期方向（月线）：{_direction_text(str(macro['direction']))}；"
        f"中周期结构（周线）：{_direction_text(str(structure['direction']))}；"
        f"交易机会（日线）：{_direction_text(str(opportunity['direction']))}；"
        f"小周期触发（1H）：{trigger['status']}"
    )

    return {
        "alignment": alignment,
        "decision_filter": decision_filter,
        "framework": framework,
        "macro": macro,
        "structure": structure,
        "opportunity": opportunity,
        "trigger": trigger,
        "bias_stack": [
            {"timeframe": macro["timeframe"], "role": macro["role"], "direction": macro["direction"]},
            {"timeframe": structure["timeframe"], "role": structure["role"], "direction": structure["direction"]},
            {"timeframe": opportunity["timeframe"], "role": opportunity["role"], "direction": opportunity["direction"]},
            {"timeframe": trigger["timeframe"], "role": trigger["role"], "status": trigger["status"]},
        ],
    }


def format_timeframe_context(context: dict[str, Any]) -> str:
    if not context:
        return "暂无"
    framework = str(context.get("framework") or "暂无")
    decision_filter = str(context.get("decision_filter") or "")
    if decision_filter:
        return f"{framework}；过滤：{decision_filter}"
    return framework
