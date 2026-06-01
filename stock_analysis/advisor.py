from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional

from .models import Advice, NakedKSnapshot, ResearchEntry, TechnicalSnapshot, WssContext


EVIDENCE_ORDER = ["market", "research", "technical", "naked_k", "earnings"]


def _ticker_key(ticker: str) -> str:
    return ticker.upper()


def _research_quality(entry: Optional[ResearchEntry], avoid_list: List[str], ticker: str) -> str:
    if entry is None:
        return "missing"
    if entry.avoid or ticker in avoid_list or "回避" in entry.rating:
        return "weak"

    score = entry.score or 0
    evidence_rank = {"A": 4, "A-": 3, "B+": 2, "B": 1}
    evidence = evidence_rank.get(entry.evidence, 0)
    if score >= 80 and evidence >= 3:
        return "strong"
    if score >= 68 and evidence >= 2:
        return "acceptable"
    return "weak"


def _market_state(ctx: WssContext, entry: Optional[ResearchEntry]) -> str:
    if any(rule.status == "rupture" for rule in ctx.market.rules):
        return "rupture"
    if ctx.market.market_state == "触发防守":
        return "rupture"

    sector = entry.sector if entry else ""
    if ctx.market.market_state == "警戒观察":
        return "overheated"
    if sector and any(sector in note for note in ctx.market.sector_overheats):
        return "overheated"
    if ctx.market.market_state == "趋势仍强":
        return "supportive"
    return "unknown"


def _technical_direction(technical: Optional[TechnicalSnapshot]) -> str:
    if technical is None:
        return "neutral"
    if technical.direction == "bullish" and technical.score > 0:
        return "bullish"
    if technical.direction == "bearish" or technical.score < -1:
        return "bearish"
    return "neutral"


def _format_price(value: Optional[float]) -> str:
    if value is None:
        return "暂无明确失效线"
    return f"{value:g}"


def _zones(values: List[float]) -> List[str]:
    return [f"{value:g}" for value in values]


def _parse_date(value: str) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _is_high_risk_earnings(ctx: WssContext, key: str, today: date) -> bool:
    event = ctx.earnings.events.get(key)
    if event is None:
        return False
    event_date = _parse_date(event.date)
    if event_date is None:
        return False
    days = (event_date - today).days
    implied_move = event.implied_move or 0
    return 0 <= days <= 7 and implied_move >= 5


def build_advice(
    ticker: str,
    ctx: WssContext,
    technical: Optional[TechnicalSnapshot] = None,
    naked: Optional[NakedKSnapshot] = None,
    today: Optional[date] = None,
) -> Advice:
    current_date = today or date.today()
    key = _ticker_key(ticker)
    entry = ctx.research.tickers.get(key)
    quality = _research_quality(entry, ctx.research.avoid, key)
    market = _market_state(ctx, entry)
    tech_dir = _technical_direction(technical)
    high_risk_earnings = _is_high_risk_earnings(ctx, key, current_date)

    warnings = list(ctx.warnings)
    if technical:
        warnings.extend(technical.warnings)
    if naked:
        warnings.extend(naked.warnings)
    if high_risk_earnings:
        warnings.append("财报临近且IV隐含波动较高，阻止短线新开仓")

    evidence: Dict[str, List[str]] = {name: [] for name in EVIDENCE_ORDER}
    if ctx.market.market_state:
        evidence["market"].append(f"市场状态: {ctx.market.market_state}")
    if ctx.market.bubble_phase:
        evidence["market"].append(f"泡沫阶段: {ctx.market.bubble_phase}")

    if entry:
        evidence["research"].append(
            f"WSS研究: {entry.rating or '未评级'}，分数 {entry.score if entry.score is not None else '未知'}，证据 {entry.evidence or '未知'}"
        )
        if entry.catalysts:
            evidence["research"].append("催化: " + " / ".join(entry.catalysts[:3]))
        if entry.risks:
            evidence["research"].append("风险: " + " / ".join(entry.risks[:3]))
    else:
        evidence["research"].append("无WSS研究缓存，长期判断降置信度")

    if technical:
        evidence["technical"].append(f"技术方向: {technical.direction}，评分 {technical.score:+.1f}")
        if technical.summary:
            evidence["technical"].append(technical.summary)
    else:
        evidence["technical"].append("技术分析不可用")

    if naked:
        evidence["naked_k"].append(f"裸K方向: {naked.direction}")
        if naked.summary:
            evidence["naked_k"].append(naked.summary)
    else:
        evidence["naked_k"].append("裸K分析不可用")

    event = ctx.earnings.events.get(key)
    if event:
        evidence["earnings"].append(f"财报: {event.date} {event.timing}")
        if event.implied_move is not None:
            evidence["earnings"].append(f"IV隐含波动: {event.implied_move:g}%")

    if quality == "weak":
        overall = "回避"
        confidence = "高"
        position = "空仓等待"
    elif quality == "missing":
        overall = "观望"
        confidence = "中"
        position = "空仓等待"
    elif market == "rupture" and tech_dir == "bearish":
        overall = "卖出"
        confidence = "高"
        position = "降低高 beta"
    elif market == "rupture":
        overall = "减仓"
        confidence = "中"
        position = "降低高 beta"
    elif tech_dir == "bullish":
        overall = "买入"
        confidence = "中" if market == "overheated" else "高"
        position = "轻仓" if market == "overheated" else "标准仓"
    elif quality in {"strong", "acceptable"}:
        overall = "持有"
        confidence = "中"
        position = "只持有不加仓"
    else:
        overall = "观望"
        confidence = "中"
        position = "空仓等待"

    if high_risk_earnings and overall == "买入":
        overall = "观望"
        confidence = "中"
        position = "空仓等待"

    invalidation = _format_price(naked.invalidation if naked else None)
    supports = naked.supports if naked else (technical.supports if technical else [])
    resistances = naked.resistances if naked else (technical.resistances if technical else [])

    if high_risk_earnings and overall == "观望":
        short_action = "等财报后再看"
    elif overall == "买入":
        short_action = "短线买入" if naked and naked.invalidation else "突破确认后买"
    elif overall in {"减仓", "卖出", "回避"}:
        short_action = "短线减仓"
    else:
        short_action = "观望"

    if overall in {"买入", "小仓试错"}:
        medium_action = "波段买入"
    elif overall == "持有":
        medium_action = "持有"
    elif overall in {"减仓", "卖出", "回避"}:
        medium_action = "减仓"
    else:
        medium_action = "等待日线买点"

    if quality in {"strong", "acceptable"} and overall not in {"卖出", "回避"}:
        long_action = "长期观察" if market == "overheated" else "长期核心持有"
    elif overall == "回避":
        long_action = "回避"
    else:
        long_action = "长期观察"

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
    )
