from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from .models import Advice, TechnicalSnapshot


EVIDENCE_ORDER = ["technical"]
SOURCE_LABELS = {"short": "短期(4H)", "medium": "中期(日线)", "long": "长期(周线)"}
MIN_SOURCE_ROWS = {"short": 120, "medium": 120, "long": 52}
MAX_STALE_DAYS = {"short": 10, "medium": 10, "long": 35}


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
) -> List[str]:
    triggers: List[str] = []
    if overall == "买入":
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
            triggers.append("等待街哥核心战法继续确认")
    elif overall == "持有":
        triggers.append("只持有不加仓，等待日线买点或压力突破确认")
    elif overall == "观望":
        if resistances:
            triggers.append(f"等待重新站上{resistances[0]:g}并获得日线确认")
        elif supports:
            triggers.append(f"等待回踩{supports[0]:g}出现有效承接")
        else:
            triggers.append("等待街哥核心战法重新形成共振")
    elif overall in {"减仓", "卖出", "回避"}:
        triggers.append("不做新开仓，只观察风险解除信号")
    return triggers


def _build_blocked_by(tech_dir: str, overall: str) -> List[str]:
    blocked: List[str] = []
    if tech_dir == "bearish":
        blocked.append("技术趋势偏空")
    if overall == "观望" and tech_dir == "neutral":
        blocked.append("街哥技术信号未形成共振")
    return blocked


def _current_price(technical: Optional[TechnicalSnapshot]) -> Optional[float]:
    if technical and technical.current_price:
        return technical.current_price
    return None


def _risk_blockers(technical: Optional[TechnicalSnapshot]) -> List[str]:
    blockers: List[str] = []
    risk_flags = technical.risk_flags if technical else []
    if any("高位过热" in flag for flag in risk_flags):
        blockers.append("高位过热，不追新仓")
    return blockers


def _collect_data_sources(technical: Optional[TechnicalSnapshot]) -> Dict[str, object]:
    sources: Dict[str, object] = {"technical": {}}
    if technical and technical.data_sources:
        sources["technical"] = technical.data_sources
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


def _data_quality_findings(technical: Optional[TechnicalSnapshot]) -> Tuple[List[str], List[str]]:
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
    return warnings, blockers


def _short_action(tech_dir: str) -> str:
    if tech_dir == "bearish":
        return "短线减仓"
    if tech_dir == "bullish":
        return "短线买入"
    return "观望"


def _medium_action(tech_dir: str) -> str:
    if tech_dir == "bearish":
        return "减仓"
    if tech_dir == "bullish":
        return "波段买入"
    return "等待日线买点"


def _long_action(tech_dir: str) -> str:
    if tech_dir == "bearish":
        return "等待趋势修复"
    if tech_dir == "bullish":
        return "趋势持有"
    return "长期观察"


def _build_timeframe_state(technical: Optional[TechnicalSnapshot]) -> str:
    if not technical or not technical.timeframe_directions:
        return ""

    short = technical.timeframe_directions.get("short", "neutral")
    medium = technical.timeframe_directions.get("medium", "neutral")
    long = technical.timeframe_directions.get("long", "neutral")

    if long == "bullish":
        if medium == "bullish":
            if short == "bullish":
                return "周线多头，日线买点确认，4H触发偏多"
            return "周线多头，日线买点确认，等待4H触发"
        if medium == "bearish":
            return "周线多头中日线回撤，等待止跌"
        return "周线多头，日线setup未完成，等待日线买点"

    if long == "bearish":
        if medium == "bullish":
            if short == "bullish":
                return "周线空头但日线反弹，4H只按反弹节奏处理"
            return "周线空头但日线反弹，等待4H确认"
        if medium == "bearish":
            return "周线空头，日线卖点确认，回避新仓"
        return "周线空头，日线未修复"

    if medium == "bullish":
        if short == "bullish":
            return "周线中性，日线买点确认，4H触发偏多"
        return "周线中性，日线买点确认，等待4H触发"
    if medium == "bearish":
        return "周线中性，日线转弱，短线反弹只作观察"
    if short == "bullish":
        return "周线中性，日线未确认，4H只作短线触发"
    return "多周期未形成清晰共振"


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
) -> Advice:
    key = _ticker_key(ticker)
    tech_dir = _technical_direction(technical)
    medium_dir = _horizon_direction(technical, "medium")
    current_price = _current_price(technical)
    risk_blockers = _risk_blockers(technical)
    data_warnings, data_blockers = _data_quality_findings(technical)

    warnings: List[str] = []
    if technical:
        warnings.extend(technical.warnings)
    warnings.extend(data_warnings)

    evidence: Dict[str, List[str]] = {name: [] for name in EVIDENCE_ORDER}
    _append_technical_evidence(evidence, technical)

    if tech_dir == "bearish":
        overall = "减仓"
        confidence = "中"
        position = "降低仓位"
    elif tech_dir == "bullish" and medium_dir != "bullish":
        overall = "小仓试错"
        confidence = "中"
        position = "小仓"
    elif tech_dir == "bullish":
        overall = "买入"
        confidence = "高"
        position = "标准仓"
    else:
        overall = "观望"
        confidence = "中"
        position = "空仓等待"

    if overall == "买入" and any("高位过热" in item for item in risk_blockers):
        overall = "小仓试错"
        confidence = "中"
        position = "小仓"
    if overall in {"买入", "小仓试错"} and data_blockers:
        overall = "观望"
        confidence = "中"
        position = "空仓等待"

    invalidation = _format_price(None)
    supports = technical.supports if technical else []
    resistances = technical.resistances if technical else []

    short_action = _short_action(_horizon_direction(technical, "short"))
    if overall in {"减仓", "卖出", "回避"} and short_action in {"短线买入", "突破确认后买", "短线小仓试错"}:
        short_action = "短线反弹观察"
    medium_action = _medium_action(_horizon_direction(technical, "medium"))
    long_action = _long_action(_horizon_direction(technical, "long"))
    if overall == "观望" and data_blockers:
        short_action = "观望"
        medium_action = "等待数据修复"

    entry_triggers = _build_entry_triggers(overall, supports, resistances)
    if overall == "观望" and data_blockers:
        entry_triggers = ["等待关键数据恢复后重新评估"]
    blocked_by = _build_blocked_by(tech_dir, overall)
    if overall in {"观望", "小仓试错"}:
        blocked_by.extend(item for item in risk_blockers if item not in blocked_by)
        blocked_by.extend(item for item in data_blockers if item not in blocked_by)
    timeframe_state = _build_timeframe_state(technical)

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
        current_price=current_price,
        data_sources=_collect_data_sources(technical),
        entry_triggers=entry_triggers,
        blocked_by=blocked_by,
        timeframe_state=timeframe_state,
    )
