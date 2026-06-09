from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class TechnicalSnapshot:
    direction: str = "neutral"
    score: float = 0.0
    current_price: Optional[float] = None
    summary: str = ""
    supports: List[float] = field(default_factory=list)
    resistances: List[float] = field(default_factory=list)
    timeframe_scores: Dict[str, float] = field(default_factory=dict)
    timeframe_directions: Dict[str, str] = field(default_factory=dict)
    macd_regimes: Dict[str, str] = field(default_factory=dict)
    evidence_sections: Dict[str, List[str]] = field(default_factory=dict)
    data_sources: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    risk_flags: List[str] = field(default_factory=list)
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
    current_price: Optional[float] = None
    data_sources: Dict[str, Any] = field(default_factory=dict)
    entry_triggers: List[str] = field(default_factory=list)
    blocked_by: List[str] = field(default_factory=list)
    timeframe_state: str = ""
