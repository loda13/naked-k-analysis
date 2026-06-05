from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from .models import Advice, NakedKSnapshot, TechnicalSnapshot


EVIDENCE_ORDER = ["technical", "naked_k"]
SOURCE_LABELS = {"short": "短期(4H)", "medium": "中期(日线)", "long": "长期(周线)"}
MIN_SOURCE_ROWS = {"short": 120, "medium": 120, "long": 52, "naked_k": 80}
MAX_STALE_DAYS = {"short": 10, "medium": 10, "long": 35, "naked_k": 10}


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


def _horizon_direction(technical: Optional[TechnicalSnapshot], horizon: str) -> str:
    if technical and technical.timeframe_directions.get(horizon):
        return technical.timeframe_directions[horizon]
    return _technical_direction(technical)


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


def _current_price(technical: Optional[TechnicalSnapshot], naked: Optional[NakedKSnapshot]) -> Optional[float]:
    if naked and naked.current_price:
        return naked.current_price
    if technical and technical.current_price:
        return technical.current_price
    return None


def _stop_distance_pct(price: Optional[float], invalidation: Optional[float]) -> Optional[float]:
    if price is None or invalidation is None or price <= 0:
        return None
    return abs(price - invalidation) / price * 100


def _risk_blockers(
    technical: Optional[TechnicalSnapshot],
    price: Optional[float],
    invalidation: Optional[float],
) -> List[str]:
    blockers: List[str] = []
    risk_flags = technical.risk_flags if technical else []
    if any("高位过热" in flag for flag in risk_flags):
        blockers.append("高位过热，不追新仓")
    stop_dist = _stop_distance_pct(price, invalidation)
    if stop_dist is not None and stop_dist > 20:
        blockers.append(f"失效线距离过远({stop_dist:.1f}%)")
    elif stop_dist is not None and stop_dist > 12:
        blockers.append(f"失效线距离偏远({stop_dist:.1f}%)")
    return blockers


def _collect_data_sources(
    technical: Optional[TechnicalSnapshot],
    naked: Optional[NakedKSnapshot],
) -> Dict[str, object]:
    sources: Dict[str, object] = {"technical": {}, "naked_k": {}}
    if technical and technical.data_sources:
        sources["technical"] = technical.data_sources
    if naked and naked.data_source:
        sources["naked_k"] = naked.data_source
    return sources


def _parse_latest_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for candidate in (text[:10], text):
        try:
            return datetime.fromisoformat(candidate).date()
        except ValueError:
            continue
    return None


def _source_rows(source: Dict[str, Any]) -> Optional[int]:
    rows = source.get("rows")
    if rows in (None, ""):
        return None
    try:
        return int(rows)
    except (TypeError, ValueError):
        return None


def _append_once(items: List[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _check_source_quality(
    label: str,
    source: Dict[str, Any],
    min_rows: int,
    max_stale_days: int,
    critical: bool,
    warnings: List[str],
    blockers: List[str],
) -> None:
    source_name = source.get("source", "unknown")
    rows = _source_rows(source)
    if rows is not None and rows < min_rows:
        warnings.append(f"{label}数据行数不足(rows={rows}, source={source_name})")
        if critical:
            _append_once(blockers, "关键数据质量不足")

    latest = _parse_latest_date(source.get("latest"))
    if latest is None:
        return
    stale_days = (date.today() - latest).days
    if stale_days > max_stale_days:
        warnings.append(f"{label}数据过旧(latest={latest.isoformat()}, {stale_days}天前, source={source_name})")
        if critical:
            _append_once(blockers, "关键数据质量不足")


def _data_quality_findings(
    technical: Optional[TechnicalSnapshot],
    naked: Optional[NakedKSnapshot],
) -> Tuple[List[str], List[str]]:
    warnings: List[str] = []
    blockers: List[str] = []
    if technical and technical.data_sources:
        for horizon, label in SOURCE_LABELS.items():
            source = technical.data_sources.get(horizon)
            if isinstance(source, dict):
                _check_source_quality(
                    label,
                    source,
                    MIN_SOURCE_ROWS[horizon],
                    MAX_STALE_DAYS[horizon],
                    critical=horizon == "medium",
                    warnings=warnings,
                    blockers=blockers,
                )
    if naked and naked.data_source:
        _check_source_quality(
            "裸K",
            naked.data_source,
            MIN_SOURCE_ROWS["naked_k"],
            MAX_STALE_DAYS["naked_k"],
            critical=True,
            warnings=warnings,
            blockers=blockers,
        )
    return warnings, blockers


def _short_action(tech_dir: str, naked_dir: str, naked: Optional[NakedKSnapshot]) -> str:
    if tech_dir == "bearish":
        return "短线减仓"
    if tech_dir == "bullish" and naked_dir != "bearish":
        return "短线买入" if naked and naked.invalidation else "突破确认后买"
    if tech_dir == "neutral" and naked_dir == "bullish":
        return "短线小仓试错"
    return "观望"


def _medium_action(tech_dir: str, naked_dir: str) -> str:
    if tech_dir == "bearish":
        return "减仓"
    if tech_dir == "bullish" and naked_dir != "bearish":
        return "波段买入"
    if tech_dir == "bullish" and naked_dir == "bearish":
        return "等待日线确认"
    return "等待日线买点"


def _long_action(tech_dir: str) -> str:
    if tech_dir == "bearish":
        return "等待趋势修复"
    if tech_dir == "bullish":
        return "趋势持有"
    return "长期观察"


def _append_technical_evidence(evidence: Dict[str, List[str]], technical: Optional[TechnicalSnapshot]) -> None:
    if not technical:
        evidence["technical"].append("技术分析不可用")
        return

    evidence["technical"].append(f"技术方向: {technical.direction}，评分 {technical.score:+.1f}")
    horizon_labels = {"short": "短期(4H)", "medium": "中期(日线)", "long": "长期(周线)"}
    for horizon, label in horizon_labels.items():
        if horizon in technical.timeframe_scores:
            direction = technical.timeframe_directions.get(horizon, "neutral")
            score = technical.timeframe_scores[horizon]
            evidence["technical"].append(f"{label}: {direction}，评分 {score:+.1f}")

    section_labels = {"trend": "趋势", "momentum": "动量", "cost": "成本区"}
    for key, label in section_labels.items():
        items = technical.evidence_sections.get(key, [])
        if items:
            evidence["technical"].append(f"{label}: " + "；".join(items[:3]))

    if technical.summary:
        evidence["technical"].append(technical.summary)


def build_advice(
    ticker: str,
    technical: Optional[TechnicalSnapshot] = None,
    naked: Optional[NakedKSnapshot] = None,
) -> Advice:
    key = _ticker_key(ticker)
    tech_dir = _technical_direction(technical)
    naked_dir = _naked_direction(naked)
    medium_dir = _horizon_direction(technical, "medium")
    current_price = _current_price(technical, naked)
    raw_invalidation = naked.invalidation if naked else None
    risk_blockers = _risk_blockers(technical, current_price, raw_invalidation)
    data_warnings, data_blockers = _data_quality_findings(technical, naked)

    warnings: List[str] = []
    if technical:
        warnings.extend(technical.warnings)
    if naked:
        warnings.extend(naked.warnings)
    warnings.extend(data_warnings)

    evidence: Dict[str, List[str]] = {name: [] for name in EVIDENCE_ORDER}
    _append_technical_evidence(evidence, technical)

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
    elif tech_dir == "bullish" and medium_dir != "bullish":
        overall = "小仓试错"
        confidence = "中"
        position = "小仓"
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

    if overall in {"买入", "小仓试错"} and any("失效线距离过远" in item for item in risk_blockers):
        overall = "观望"
        confidence = "中"
        position = "空仓等待"
    elif overall == "买入" and any("高位过热" in item for item in risk_blockers):
        overall = "小仓试错"
        confidence = "中"
        position = "小仓"
    elif overall == "买入" and any("失效线距离偏远" in item for item in risk_blockers):
        overall = "小仓试错"
        confidence = "中"
        position = "小仓"
    if overall in {"买入", "小仓试错"} and data_blockers:
        overall = "观望"
        confidence = "中"
        position = "空仓等待"

    invalidation = _format_price(raw_invalidation)
    supports = naked.supports if naked else (technical.supports if technical else [])
    resistances = naked.resistances if naked else (technical.resistances if technical else [])

    short_action = _short_action(_horizon_direction(technical, "short"), naked_dir, naked)
    if overall in {"减仓", "卖出", "回避"} and short_action in {"短线买入", "突破确认后买", "短线小仓试错"}:
        short_action = "短线反弹观察"
    medium_action = _medium_action(_horizon_direction(technical, "medium"), naked_dir)
    long_action = _long_action(_horizon_direction(technical, "long"))
    if overall == "观望" and any("高位过热" in item or "失效线距离过远" in item for item in risk_blockers):
        short_action = "观望"
        medium_action = "等待日线买点"
    if overall == "观望" and data_blockers:
        short_action = "观望"
        medium_action = "等待数据修复"

    entry_triggers = _build_entry_triggers(overall, supports, resistances, naked)
    if overall == "观望" and data_blockers:
        entry_triggers = ["等待关键数据恢复后重新评估"]
    blocked_by = _build_blocked_by(tech_dir, naked_dir, overall)
    if overall in {"观望", "小仓试错"}:
        blocked_by.extend(item for item in risk_blockers if item not in blocked_by)
        blocked_by.extend(item for item in data_blockers if item not in blocked_by)

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
        data_sources=_collect_data_sources(technical, naked),
        entry_triggers=entry_triggers,
        blocked_by=blocked_by,
    )
