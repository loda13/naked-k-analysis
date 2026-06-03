from __future__ import annotations

import contextlib
import io
import json
from typing import List, Optional

from .data import resolve_technical_timeframes
from .models import TechnicalSnapshot
from .jg_methodology import summarize_methodology


def analyze_technical(ticker: str, timeframes: Optional[List[str]] = None) -> TechnicalSnapshot:
    resolved = resolve_technical_timeframes(timeframes)
    try:
        import ma_analysis
    except ModuleNotFoundError as exc:
        return TechnicalSnapshot(warnings=resolved.warnings + [f"技术分析依赖缺失: {exc.name}"])
    except Exception as exc:
        return TechnicalSnapshot(warnings=resolved.warnings + [f"技术分析不可用: {exc}"])

    stream = io.StringIO()
    err_stream = io.StringIO()
    try:
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(err_stream):
            ma_analysis.analyze(ticker, resolved.timeframes, output_json=True)
        raw = stream.getvalue().strip()
        payload = json.loads(raw)
    except Exception as exc:
        return TechnicalSnapshot(warnings=resolved.warnings + [f"技术分析失败: {exc}"])

    if payload.get("error"):
        details = err_stream.getvalue().strip().splitlines()
        warning = f"技术分析无数据: {payload['error']}"
        if details:
            warning += f" ({details[-1]})"
        return TechnicalSnapshot(warnings=resolved.warnings + [warning])

    scores = []
    supports = []
    resistances = []
    for item in payload.get("timeframes", []):
        score = ((item.get("weighted_score") or {}).get("score") or 0)
        scores.append(float(score))
        supports.extend(level.get("price") for level in item.get("supports", []) if level.get("price") is not None)
        resistances.extend(level.get("price") for level in item.get("resistances", []) if level.get("price") is not None)

    total = sum(scores)
    if total > 0.5:
        direction = "bullish"
    elif total < -1:
        direction = "bearish"
    else:
        direction = "neutral"

    summary_parts = []
    resonance = (payload.get("resonance") or {}).get("action", "")
    if resonance:
        summary_parts.append(resonance)
    summary_parts.extend(summarize_methodology(payload))

    return TechnicalSnapshot(
        direction=direction,
        score=round(total, 2),
        summary="；".join(summary_parts),
        supports=[float(v) for v in supports[:3]],
        resistances=[float(v) for v in resistances[:3]],
        warnings=resolved.warnings,
    )
