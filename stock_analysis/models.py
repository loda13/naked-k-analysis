from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ResearchEntry:
    ticker: str
    score: Optional[float] = None
    evidence: str = ""
    rating: str = ""
    sector: str = ""
    rank: Optional[int] = None
    business_purity: str = ""
    risks: List[str] = field(default_factory=list)
    catalysts: List[str] = field(default_factory=list)
    avoid: bool = False


@dataclass(frozen=True)
class ResearchSnapshot:
    as_of: str = ""
    tickers: Dict[str, ResearchEntry] = field(default_factory=dict)
    avoid: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class MarketRule:
    name: str
    status: str
    value: str = ""
    trigger: str = ""


@dataclass(frozen=True)
class MarketRiskSnapshot:
    as_of: str = ""
    market_state: str = ""
    bubble_phase: str = ""
    sector_overheats: List[str] = field(default_factory=list)
    rules: List[MarketRule] = field(default_factory=list)


@dataclass(frozen=True)
class EarningsEvent:
    ticker: str
    date: str = ""
    timing: str = ""
    eps_estimate: str = ""
    revenue_estimate: str = ""
    implied_move: Optional[float] = None


@dataclass(frozen=True)
class EarningsSnapshot:
    as_of: str = ""
    events: Dict[str, EarningsEvent] = field(default_factory=dict)


@dataclass(frozen=True)
class WssContext:
    research: ResearchSnapshot
    market: MarketRiskSnapshot
    earnings: EarningsSnapshot
    warnings: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class TechnicalSnapshot:
    direction: str = "neutral"
    score: float = 0.0
    summary: str = ""
    supports: List[float] = field(default_factory=list)
    resistances: List[float] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class NakedKSnapshot:
    direction: str = "neutral"
    score: float = 0.0
    invalidation: Optional[float] = None
    supports: List[float] = field(default_factory=list)
    resistances: List[float] = field(default_factory=list)
    summary: str = ""
    warnings: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Advice:
    ticker: str
    overall_action: str
    short_term_action: str
    medium_term_action: str
    long_term_action: str
    confidence: str
    position_guidance: str
    invalidation: str
    upside_zones: List[str]
    downside_zones: List[str]
    evidence: Dict[str, List[str]]
    warnings: List[str]
