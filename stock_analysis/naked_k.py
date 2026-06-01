from __future__ import annotations

import contextlib
import io
from typing import Optional

from .models import NakedKSnapshot


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
    invalidation: Optional[float] = supports[0] if supports else None

    return NakedKSnapshot(
        direction=direction,
        score=score,
        invalidation=invalidation,
        supports=supports[:3],
        resistances=resistances[:3],
        summary=", ".join(payload.get("reasons", [])[:3]),
    )
