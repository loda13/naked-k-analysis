from __future__ import annotations

from typing import Any


def _contains(items: list[Any], needle: str) -> bool:
    return any(needle in str(item) for item in items)


def _base_setup() -> dict[str, Any]:
    return {
        "key": "neutral_wait",
        "name": "无明确交易剧本",
        "direction": "watch",
        "quality": "weak",
        "confidence_score": 35,
        "thesis": "价格行为、结构和市场状态尚未形成一致交易剧本。",
        "required_confirmation": ["等待结构突破、假突破收回或压缩扩张后的收盘确认"],
        "invalidation_logic": "缺少明确 setup，不预设失效位。",
        "risk_notes": ["无明确优势前控制仓位或观望"],
    }


def classify_trade_setup(
    price_action: dict[str, Any],
    market_structure: dict[str, Any],
    market_regime: dict[str, Any],
    daily_patterns: list[str],
) -> dict[str, Any]:
    signals = list(price_action.get("signals") or [])
    warnings = list(price_action.get("warnings") or [])
    event = market_structure.get("latest_event") or {}
    event_kind = str(event.get("kind") or "")
    event_direction = str(event.get("direction") or "")
    structure_direction = str(market_structure.get("direction") or "")
    sequence = str(market_structure.get("sequence") or "")
    regime_state = str(market_regime.get("state") or "")
    regime_direction = str(market_regime.get("direction") or "")
    volume_pressure = str(price_action.get("volume_pressure") or "")

    if (
        event_kind == "BOS"
        and event_direction == "bullish"
        and structure_direction == "up"
        and sequence == "HH/HL"
        and regime_state == "trend"
        and regime_direction == "bullish"
    ):
        return {
            "key": "bullish_bos_continuation",
            "name": "多头BOS趋势延续",
            "direction": "long",
            "quality": "strong",
            "confidence_score": 78,
            "thesis": "价格收盘突破结构高点，并处于HH/HL趋势结构中，说明多头仍在主动推进。",
            "required_confirmation": ["等待回踩不破突破位", "小周期重新转强后再触发"],
            "invalidation_logic": "跌回突破位下方并失守最近结构低点，说明BOS失败。",
            "risk_notes": ["避免突破当日追高过深", "优先用结构低点或ATR缓冲定义失效"],
        }

    if event_kind == "CHoCH" and event_direction == "bullish":
        return {
            "key": "bullish_choch_reversal",
            "name": "多头CHoCH反转试错",
            "direction": "long",
            "quality": "developing",
            "confidence_score": 62,
            "thesis": "下降结构中出现向上CHoCH，代表空头节奏被打断，结构转换开始但尚未确认反转趋势。",
            "required_confirmation": ["等待小周期形成HL", "回踩不再跌破扫单低点后再触发"],
            "invalidation_logic": "重新跌破CHoCH前的扫单低点，说明反转试错失败。",
            "risk_notes": ["CHoCH只代表转换，不等同趋势反转", "只能小仓试错，等待二次确认"],
        }

    if (
        _contains(signals, "上破")
        and _contains(signals, "失败")
        and (_contains(warnings, "假突破") or _contains(warnings, "上破失败") or volume_pressure == "派发压力")
    ):
        return {
            "key": "failed_breakout_short",
            "name": "上方流动性扫过失败",
            "direction": "short",
            "quality": "strong",
            "confidence_score": 74,
            "thesis": "价格扫过上方流动性后未能收住，卖压重新控制短线节奏，假突破后的回落风险上升。",
            "required_confirmation": ["跌破假突破K低点后再确认", "弱反抽无法站回前高区域"],
            "invalidation_logic": "重新站回假突破高点上方，说明上方供给被吸收。",
            "risk_notes": ["震荡区间内优先按反打处理", "若再次放量突破需停止做空假设"],
        }

    if regime_state == "low_volatility_compression" or _contains(signals, "波幅连续收敛"):
        return {
            "key": "compression_breakout_watch",
            "name": "压缩后等待扩张",
            "direction": "watch",
            "quality": "developing",
            "confidence_score": 55,
            "thesis": "波动持续压缩，市场处于蓄势阶段，优势来自扩张方向确认而不是提前押方向。",
            "required_confirmation": ["等待扩张K收盘确认", "突破母线高低点后观察量价是否同步"],
            "invalidation_logic": "压缩区间继续收敛时不提前失效，只降低交易优先级。",
            "risk_notes": ["压缩阶段减少预判", "扩张首日注意假突破和滑点"],
        }

    if _contains(signals, "下破") and _contains(signals, "收回"):
        return {
            "key": "liquidity_sweep_reclaim_long",
            "name": "下方流动性扫过收回",
            "direction": "long",
            "quality": "developing",
            "confidence_score": 66,
            "thesis": "价格下破前低后快速收回，说明空头突破失败，下方卖压被吸收。",
            "required_confirmation": ["站上扫单K高点后再触发", "回踩不破扫单低点"],
            "invalidation_logic": "重新跌破扫单低点，说明承接失败。",
            "risk_notes": ["优先小仓试错", "若周线偏空需降低仓位"],
        }

    return _base_setup()
