from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import (
    EarningsEvent,
    EarningsSnapshot,
    MarketRiskSnapshot,
    MarketRule,
    ResearchEntry,
    ResearchSnapshot,
    WssContext,
)


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _normalize_ticker(ticker: str) -> str:
    return ticker.upper()


def _parse_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _warn_if_stale(warnings: List[str], label: str, as_of: str, today: date, max_age_days: int = 7) -> None:
    parsed = _parse_date(as_of)
    if parsed is None:
        return
    age = (today - parsed).days
    if age > max_age_days:
        warnings.append(f"{label}缓存已过期: {as_of}，距今{age}天")


def _load_research(cache_dir: Path) -> ResearchSnapshot:
    raw = _read_json(cache_dir / "research.json")
    tickers = {}
    for ticker, item in raw.get("tickers", {}).items():
        key = _normalize_ticker(ticker)
        tickers[key] = ResearchEntry(
            ticker=key,
            score=item.get("score"),
            evidence=item.get("evidence", ""),
            rating=item.get("rating", ""),
            sector=item.get("sector", ""),
            rank=item.get("rank"),
            business_purity=item.get("business_purity", ""),
            moat=item.get("moat", ""),
            commercial_validation=item.get("commercial_validation", ""),
            financial_quality=item.get("financial_quality", ""),
            industry_position=item.get("industry_position", ""),
            valuation_odds=item.get("valuation_odds", ""),
            risk_deduction=item.get("risk_deduction", ""),
            risks=list(item.get("risks", [])),
            catalysts=list(item.get("catalysts", [])),
            avoid=bool(item.get("avoid", False)),
        )
    return ResearchSnapshot(
        as_of=raw.get("as_of", ""),
        tickers=tickers,
        avoid=[_normalize_ticker(t) for t in raw.get("avoid", [])],
    )


def _load_market(cache_dir: Path) -> MarketRiskSnapshot:
    raw = _read_json(cache_dir / "market_risk.json")
    rules = [
        MarketRule(
            name=item.get("name", ""),
            status=item.get("status", ""),
            value=item.get("value", ""),
            trigger=item.get("trigger", ""),
        )
        for item in raw.get("rules", [])
    ]
    return MarketRiskSnapshot(
        as_of=raw.get("as_of", ""),
        market_state=raw.get("market_state", ""),
        bubble_phase=raw.get("bubble_phase", ""),
        sector_overheats=list(raw.get("sector_overheats", [])),
        rules=rules,
    )


def _load_earnings(cache_dir: Path) -> EarningsSnapshot:
    raw = _read_json(cache_dir / "earnings.json")
    events = {}
    for ticker, item in raw.get("events", {}).items():
        key = _normalize_ticker(ticker)
        events[key] = EarningsEvent(
            ticker=key,
            date=item.get("date", ""),
            timing=item.get("timing", ""),
            eps_estimate=item.get("eps_estimate", ""),
            revenue_estimate=item.get("revenue_estimate", ""),
            implied_move=item.get("implied_move"),
        )
    return EarningsSnapshot(as_of=raw.get("as_of", ""), events=events)


def load_wss_context(cache_dir: str = "data/cache/wss", today: Optional[date] = None) -> WssContext:
    base = Path(cache_dir)
    current_date = today or date.today()
    warnings: List[str] = []
    if not base.exists():
        warnings.append(f"WSS缓存不存在: {cache_dir}")

    research = _load_research(base)
    market = _load_market(base)
    earnings = _load_earnings(base)

    if not research.tickers:
        warnings.append("缺少WSS研究缓存，长期判断降置信度")
    if not market.market_state:
        warnings.append("缺少WSS市场风险缓存")

    _warn_if_stale(warnings, "WSS研究", research.as_of, current_date)
    _warn_if_stale(warnings, "WSS市场风险", market.as_of, current_date)
    _warn_if_stale(warnings, "WSS财报", earnings.as_of, current_date)

    return WssContext(research=research, market=market, earnings=earnings, warnings=warnings)
