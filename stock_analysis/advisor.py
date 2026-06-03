from __future__ import annotations

from typing import Dict, List, Optional

from .models import Advice, NakedKSnapshot, TechnicalSnapshot


EVIDENCE_ORDER = ["technical", "naked_k"]


def _ticker_key(ticker: str) -> str:
    return ticker.upper()


def _technical_direction(technical: Optional[TechnicalSnapshot]) -> str:
    if technical is None:
        return "neutral"
    if technical.direction == "bullish" and technical.score > 0:
        return "bullish"
    if technical.direction == "bearish" or technical.score < -1:
        return "bearish"
    return "neutral"


def _naked_direction(naked: Optional[NakedKSnapshot]) -> str:
    if naked is None:
        return "neutral"
    if naked.direction == "bullish" and naked.score > 0:
        return "bullish"
    if naked.direction == "bearish" or naked.score < -1:
        return "bearish"
    return "neutral"


def _format_price(value: Optional[float]) -> str:
    if value is None:
        return "暂无明确失效线"
    return f"{value:g}"


def _zones(values: List[float]) -> List[str]:
    return [f"{value:g}" for value in values]


def _build_entry_triggers(
    overall: str,
    supports: List[float],
    resistances: List[float],
    naked: Optional[NakedKSnapshot],
) -> List[str]:
    triggers: List[str] = []
    if overall == "买入":
        if naked and naked.invalidation:
            triggers.append(f"价格站稳{naked.invalidation:g}上方，失效线清晰")
        if resistances:
            triggers.append(f"放量突破{resistances[0]:g}后确认")
        elif supports:
            triggers.append(f"回踩{supports[0]:g}不破后再加仓")
    elif overall == "小仓试错":
        if supports:
            triggers.append(f"回踩{supports[0]:g}不破后小仓试错")
        elif resistances:
            triggers.append(f"突破{resistances[0]:g}后再加仓")
        else:
            triggers.append("等待街哥技术信号和裸K结构继续确认")
    elif overall == "持有":
        triggers.append("只持有不加仓，等待日线买点或压力突破确认")
    elif overall == "观望":
        if resistances:
            triggers.append(f"等待重新站上{resistances[0]:g}并获得日线确认")
        elif supports:
            triggers.append(f"等待回踩{supports[0]:g}出现有效承接")
        else:
            triggers.append("等待街哥技术流和裸K结构重新共振")
    elif overall in {"减仓", "卖出", "回避"}:
        triggers.append("不做新开仓，只观察风险解除信号")
    return triggers


def _build_blocked_by(tech_dir: str, naked_dir: str, overall: str) -> List[str]:
    blocked: List[str] = []
    if tech_dir == "bearish":
        blocked.append("技术趋势偏空")
    if naked_dir == "bearish":
        blocked.append("裸K结构偏空")
    if overall == "观望" and tech_dir == "neutral" and naked_dir != "bullish":
        blocked.append("街哥技术信号未形成共振")
    if overall == "观望" and tech_dir == "bullish" and naked_dir == "bearish":
        blocked.append("技术与裸K方向冲突")
    return blocked


def build_advice(
    ticker: str,
    technical: Optional[TechnicalSnapshot] = None,
    naked: Optional[NakedKSnapshot] = None,
) -> Advice:
    key = _ticker_key(ticker)
    tech_dir = _technical_direction(technical)
    naked_dir = _naked_direction(naked)

    warnings: List[str] = []
    if technical:
        warnings.extend(technical.warnings)
    if naked:
        warnings.extend(naked.warnings)

    evidence: Dict[str, List[str]] = {name: [] for name in EVIDENCE_ORDER}
    if technical:
        evidence["technical"].append(f"技术方向: {technical.direction}，评分 {technical.score:+.1f}")
        if technical.summary:
            evidence["technical"].append(technical.summary)
    else:
        evidence["technical"].append("技术分析不可用")

    if naked:
        evidence["naked_k"].append(f"裸K方向: {naked.direction}，评分 {naked.score:+.1f}")
        if naked.summary:
            evidence["naked_k"].append(naked.summary)
    else:
        evidence["naked_k"].append("裸K分析不可用")

    if tech_dir == "bearish" and naked_dir == "bearish":
        overall = "卖出"
        confidence = "高"
        position = "降低仓位"
    elif tech_dir == "bearish":
        overall = "减仓"
        confidence = "中"
        position = "降低仓位"
    elif tech_dir == "bullish" and naked_dir == "bearish":
        overall = "观望"
        confidence = "中"
        position = "空仓等待"
    elif tech_dir == "bullish":
        overall = "买入"
        confidence = "高" if naked_dir == "bullish" else "中"
        position = "标准仓" if naked_dir == "bullish" else "轻仓"
    elif tech_dir == "neutral" and naked_dir == "bullish":
        overall = "小仓试错"
        confidence = "中"
        position = "小仓"
    elif naked_dir == "bearish":
        overall = "观望"
        confidence = "中"
        position = "空仓等待"
    else:
        overall = "观望"
        confidence = "中"
        position = "空仓等待"

    invalidation = _format_price(naked.invalidation if naked else None)
    supports = naked.supports if naked else (technical.supports if technical else [])
    resistances = naked.resistances if naked else (technical.resistances if technical else [])

    if overall == "买入":
        short_action = "短线买入" if naked and naked.invalidation else "突破确认后买"
        medium_action = "波段买入"
        long_action = "趋势持有"
    elif overall == "小仓试错":
        short_action = "短线小仓试错"
        medium_action = "等待日线确认"
        long_action = "长期观察"
    elif overall in {"减仓", "卖出", "回避"}:
        short_action = "短线减仓"
        medium_action = "减仓"
        long_action = "等待趋势修复"
    else:
        short_action = "观望"
        medium_action = "等待日线买点"
        long_action = "长期观察"

    entry_triggers = _build_entry_triggers(overall, supports, resistances, naked)
    blocked_by = _build_blocked_by(tech_dir, naked_dir, overall)

    return Advice(
        ticker=key,
        overall_action=overall,
        short_term_action=short_action,
        medium_term_action=medium_action,
        long_term_action=long_action,
        confidence=confidence,
        position_guidance=position,
        invalidation=invalidation,
        upside_zones=_zones(resistances),
        downside_zones=_zones(supports),
        evidence=evidence,
        warnings=warnings,
        entry_triggers=entry_triggers,
        blocked_by=blocked_by,
    )
