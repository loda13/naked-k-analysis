from __future__ import annotations

from typing import Any, Dict, List


def _text(value: Any) -> str:
    return str(value or "").strip()


def _is_strong_trend(item: Dict[str, Any]) -> bool:
    arrangement = _text(item.get("arrangement"))
    vegas = item.get("vegas") or {}
    ichimoku = item.get("ichimoku") or {}
    trend_text = " ".join(
        [
            arrangement,
            _text(vegas.get("trend")),
            _text(vegas.get("position")),
            _text(ichimoku.get("cloud_pos")),
        ]
    )
    return any(token in trend_text for token in ["多头", "空头", "趋势", "通道上方", "通道下方"])


def _interpret_macd(item: Dict[str, Any]) -> str:
    macd = item.get("macd") or {}
    if not macd:
        return ""

    zone = _text(macd.get("zone")) or "零轴未知"
    hist = _text(macd.get("hist_dir")) or "柱体未知"
    cross = _text(macd.get("cross"))
    parts = [f"MACD{zone}", hist]
    if cross:
        parts.append(f"{cross}只作节奏确认")
    return "，".join(parts)


def _interpret_rsi(item: Dict[str, Any]) -> str:
    rsi = item.get("rsi")
    signal = _text(item.get("rsi_signal"))
    if rsi is None and not signal:
        return ""

    try:
        rsi_text = f"{float(rsi):.0f}"
    except (TypeError, ValueError):
        rsi_text = "未知"

    if _is_strong_trend(item) and ("超买" in signal or "超卖" in signal):
        return f"RSI{rsi_text}{signal}处于强趋势，不直接按{signal}卖出"
    if "超买" in signal or "超卖" in signal:
        return f"RSI{rsi_text}{signal}，先确认趋势/区间环境"
    if signal:
        return f"RSI{rsi_text}{signal}"
    return f"RSI{rsi_text}"


def _interpret_bollinger(item: Dict[str, Any]) -> str:
    signal = _text(item.get("boll_signal"))
    if not signal:
        return ""
    return f"BOLL{signal}，先看中轨方向和带宽，再看价格位置"


def interpret_timeframe(item: Dict[str, Any]) -> str:
    label = _text(item.get("tf")) or "未知周期"
    parts = [
        _interpret_macd(item),
        _interpret_rsi(item),
        _interpret_bollinger(item),
    ]
    useful = [part for part in parts if part]
    if not useful:
        return ""
    return f"{label}: " + "；".join(useful)


def summarize_methodology(payload: Dict[str, Any], limit: int = 3) -> List[str]:
    summaries = []
    for item in payload.get("timeframes", []):
        summary = interpret_timeframe(item)
        if summary:
            summaries.append(summary)
        if len(summaries) >= limit:
            break
    return summaries
