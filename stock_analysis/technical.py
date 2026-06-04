from __future__ import annotations

import contextlib
import io
import json
from typing import Any, Dict, List, Optional

from .data import resolve_technical_timeframes
from .models import TechnicalSnapshot
from .jg_methodology import summarize_methodology


def _horizon_key(label: str) -> Optional[str]:
    if "4" in label or "小时" in label:
        return "short"
    if "日" in label:
        return "medium"
    if "周" in label:
        return "long"
    return None


def _score_direction(score: float) -> str:
    if score > 0.5:
        return "bullish"
    if score < -1:
        return "bearish"
    return "neutral"


def _join_parts(label: str, parts: List[str]) -> str:
    return f"{label}: " + "，".join(part for part in parts if part)


def _format_level(value: Any) -> str:
    try:
        text = f"{float(value):.2f}"
        return text.rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _build_evidence_sections(payload: Dict[str, Any]) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {"trend": [], "momentum": [], "cost": []}
    for item in payload.get("timeframes", []):
        label = str(item.get("tf") or "未知周期")

        trend_parts: List[str] = []
        if item.get("arrangement"):
            trend_parts.append(str(item["arrangement"]))
        vegas = item.get("vegas") or {}
        if vegas:
            trend_parts.append(
                "Vegas" + " ".join(str(vegas.get(key) or "") for key in ["position", "trend"]).strip()
            )
        ichimoku = item.get("ichimoku") or {}
        if ichimoku:
            trend_parts.append(
                "一目云" + " ".join(str(ichimoku.get(key) or "") for key in ["cloud_pos", "tk_cross"]).strip()
            )
        if trend_parts:
            sections["trend"].append(_join_parts(label, trend_parts))

        momentum_parts: List[str] = []
        macd = item.get("macd") or {}
        if macd:
            macd_parts = [str(macd.get(key) or "") for key in ["zone", "hist_dir", "cross"] if macd.get(key)]
            momentum_parts.append("MACD" + " ".join(macd_parts))
        if item.get("rsi") is not None or item.get("rsi_signal"):
            momentum_parts.append(f"RSI{item.get('rsi') or '未知'}{item.get('rsi_signal') or ''}")
        if item.get("boll_signal"):
            momentum_parts.append(f"BOLL{item['boll_signal']}")
        if momentum_parts:
            sections["momentum"].append(_join_parts(label, momentum_parts))

        cost_parts: List[str] = []
        if item.get("avwap_low") is not None or item.get("avwap_high") is not None:
            avwap = []
            if item.get("avwap_low") is not None:
                avwap.append(f"低点锚{_format_level(item['avwap_low'])}")
            if item.get("avwap_high") is not None:
                avwap.append(f"高点锚{_format_level(item['avwap_high'])}")
            cost_parts.append("AVWAP" + "/".join(avwap))
        frvp = item.get("frvp") or {}
        if frvp:
            frvp_parts = [str(frvp.get("position") or "")]
            if frvp.get("poc") is not None:
                frvp_parts.append(f"POC{_format_level(frvp['poc'])}")
            if frvp.get("vah") is not None:
                frvp_parts.append(f"VAH{_format_level(frvp['vah'])}")
            if frvp.get("val") is not None:
                frvp_parts.append(f"VAL{_format_level(frvp['val'])}")
            cost_parts.append("FRVP" + " ".join(part for part in frvp_parts if part))
        supports = [level.get("price") for level in item.get("supports", []) if level.get("price") is not None]
        resistances = [level.get("price") for level in item.get("resistances", []) if level.get("price") is not None]
        if supports:
            cost_parts.append("支撑" + "/".join(f"{float(value):g}" for value in supports[:3]))
        if resistances:
            cost_parts.append("压力" + "/".join(f"{float(value):g}" for value in resistances[:3]))
        if cost_parts:
            sections["cost"].append(_join_parts(label, cost_parts))

    return {key: value for key, value in sections.items() if value}


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
    timeframe_scores: Dict[str, float] = {}
    timeframe_directions: Dict[str, str] = {}
    for item in payload.get("timeframes", []):
        score = ((item.get("weighted_score") or {}).get("score") or 0)
        numeric_score = float(score)
        scores.append(numeric_score)
        horizon = _horizon_key(str(item.get("tf") or ""))
        if horizon:
            timeframe_scores[horizon] = numeric_score
            timeframe_directions[horizon] = _score_direction(numeric_score)
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
        timeframe_scores=timeframe_scores,
        timeframe_directions=timeframe_directions,
        evidence_sections=_build_evidence_sections(payload),
        warnings=resolved.warnings,
    )
