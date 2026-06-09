from __future__ import annotations

import contextlib
import io
from typing import Optional

from .models import NakedKSnapshot


def _nearest_below(levels: list[float], price: Optional[float]) -> Optional[float]:
    if price is None:
        return levels[0] if levels else None
    below = [level for level in levels if level < price]
    return max(below) if below else (levels[0] if levels else None)


def _nearest_above(levels: list[float], price: Optional[float]) -> Optional[float]:
    if price is None:
        return levels[0] if levels else None
    above = [level for level in levels if level > price]
    return min(above) if above else None


def _risk_reward(price: Optional[float], invalidation: Optional[float], resistance: Optional[float]) -> Optional[float]:
    if price is None or invalidation is None or resistance is None:
        return None
    downside = price - invalidation
    upside = resistance - price
    if downside <= 0 or upside <= 0:
        return None
    return round(upside / downside, 2)


def analyze_naked_k(ticker: str) -> NakedKSnapshot:
    try:
        import naked_k_analysis
    except ModuleNotFoundError as exc:
        return NakedKSnapshot(warnings=[f"裸K分析依赖缺失: {exc.name}"])
    except Exception as exc:
        return NakedKSnapshot(warnings=[f"裸K分析不可用: {exc}"])

    err_stream = io.StringIO()
    try:
        with contextlib.redirect_stderr(err_stream):
            payload = naked_k_analysis.analyze_one(ticker, period="d", days=365, as_json=True)
    except Exception as exc:
        return NakedKSnapshot(warnings=[f"裸K分析失败: {exc}"])

    if payload.get("error"):
        details = err_stream.getvalue().strip().splitlines()
        warning = f"裸K分析无数据: {payload['error']}"
        if details:
            warning += f" ({details[-1]})"
        return NakedKSnapshot(warnings=[warning])

    score = float(payload.get("score", 0))
    if score > 0:
        direction = "bullish"
    elif score < -1:
        direction = "bearish"
    else:
        direction = "neutral"

    supports = [float(item["price"]) for item in payload.get("supports", []) if item.get("price") is not None]
    resistances = [float(item["price"]) for item in payload.get("resistances", []) if item.get("price") is not None]
    current_price = float(payload["price"]) if payload.get("price") is not None else None
    invalidation = _nearest_below(supports, current_price)
    target = _nearest_above(resistances, current_price)

    return NakedKSnapshot(
        direction=direction,
        score=score,
        current_price=current_price,
        invalidation=invalidation,
        risk_reward=_risk_reward(current_price, invalidation, target),
        supports=supports[:3],
        resistances=resistances[:3],
        summary=", ".join(payload.get("reasons", [])[:3]),
        data_source=payload.get("data_source") or {},
    )
