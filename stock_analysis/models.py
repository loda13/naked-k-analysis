from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


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
    entry_triggers: List[str] = field(default_factory=list)
    blocked_by: List[str] = field(default_factory=list)
