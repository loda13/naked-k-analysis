from __future__ import annotations

from typing import Dict

from .models import FundamentalSnapshot


COMPONENT_MAX = {
    "purity": 10,
    "moat": 30,
    "commercialization": 20,
    "financial_quality": 15,
    "industry_position": 15,
    "valuation": 10,
    "risk_deduction": 20,
}


def _clamp(value: float, upper: float) -> float:
    return max(0.0, min(float(value), upper))


def _status(total: float, evidence_grade: str) -> str:
    if evidence_grade == "C":
        return "观察"
    if total >= 80:
        return "买入"
    if total >= 70:
        return "审慎买入"
    if total >= 55:
        return "观察"
    return "回避"


def score_fundamental(
    *,
    ticker: str = "",
    purity: float,
    moat: float,
    commercialization: float,
    financial_quality: float,
    industry_position: float,
    valuation: float,
    risk_deduction: float,
    evidence_grade: str = "B",
) -> FundamentalSnapshot:
    grade = (evidence_grade or "B").upper()
    if grade not in {"A", "B", "C"}:
        grade = "B"

    components: Dict[str, float] = {
        "purity": _clamp(purity, COMPONENT_MAX["purity"]),
        "moat": _clamp(moat, COMPONENT_MAX["moat"]),
        "commercialization": _clamp(commercialization, COMPONENT_MAX["commercialization"]),
        "financial_quality": _clamp(financial_quality, COMPONENT_MAX["financial_quality"]),
        "industry_position": _clamp(industry_position, COMPONENT_MAX["industry_position"]),
        "valuation": _clamp(valuation, COMPONENT_MAX["valuation"]),
        "risk_deduction": _clamp(risk_deduction, COMPONENT_MAX["risk_deduction"]),
    }
    total = (
        components["purity"]
        + components["moat"]
        + components["commercialization"]
        + components["financial_quality"]
        + components["industry_position"]
        + components["valuation"]
        - components["risk_deduction"]
    )

    return FundamentalSnapshot(
        ticker=ticker.upper(),
        total_score=round(total, 2),
        status=_status(total, grade),
        evidence_grade=grade,
        components=components,
    )
