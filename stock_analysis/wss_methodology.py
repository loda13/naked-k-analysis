from __future__ import annotations

from typing import Any, Dict, List


def _text(value: Any) -> str:
    return str(value or "").strip()


def _format_level(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return _text(value)


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


def _interpret_vegas(item: Dict[str, Any]) -> str:
    vegas = item.get("vegas") or {}
    if not vegas:
        return ""
    position = _text(vegas.get("position"))
    trend = _text(vegas.get("trend"))
    detail = "，".join(part for part in [position, trend] if part)
    return f"Vegas{detail}，先看EMA144/169通道，再用EMA12确认节奏"


def _interpret_ichimoku(item: Dict[str, Any]) -> str:
    ichimoku = item.get("ichimoku") or {}
    if not ichimoku:
        return ""
    cloud = _text(ichimoku.get("cloud_pos"))
    tk_cross = _text(ichimoku.get("tk_cross"))
    detail = "，".join(part for part in [cloud, tk_cross] if part)
    return f"一目云{detail}，先看价格相对云层，再看转换/基准线"


def _interpret_obv(item: Dict[str, Any]) -> str:
    obv = item.get("obv") or {}
    if not obv:
        return ""
    trend = _text(obv.get("trend"))
    divergence = _text(obv.get("divergence"))
    detail = "，".join(part for part in [trend, divergence] if part)
    return f"OBV{detail}，关注方向和量价背离"


def _interpret_avwap(item: Dict[str, Any]) -> str:
    low = item.get("avwap_low")
    high = item.get("avwap_high")
    if low is None and high is None:
        return ""
    parts = []
    if low is not None:
        parts.append(f"低点锚{_format_level(low)}")
    if high is not None:
        parts.append(f"高点锚{_format_level(high)}")
    return "AVWAP成本区: " + "/".join(parts)


def _interpret_volume_profile(item: Dict[str, Any]) -> str:
    frvp = item.get("frvp") or {}
    if not frvp:
        return ""
    poc = frvp.get("poc")
    position = _text(frvp.get("position"))
    levels = []
    if poc is not None:
        levels.append(f"POC{_format_level(poc)}")
    for label, key in [("VAH", "vah"), ("VAL", "val")]:
        if frvp.get(key) is not None:
            levels.append(f"{label}{_format_level(frvp[key])}")
    detail = "，".join([position] + levels if position else levels)
    return f"FRVP{detail}，用POC/VAH/VAL定支撑压力和失效"


def _interpret_fibonacci(item: Dict[str, Any]) -> str:
    signals = [_text(item.get("fb_signal")), _text(item.get("fbd_signal")), _text(item.get("pb_signal"))]
    useful = [signal for signal in signals if signal]
    if not useful:
        return ""
    return "Fib/结构信号: " + "，".join(useful) + "，作为反应区而非预测"


def interpret_timeframe(item: Dict[str, Any]) -> str:
    label = _text(item.get("tf")) or "未知周期"
    parts = [
        _interpret_macd(item),
        _interpret_rsi(item),
        _interpret_bollinger(item),
        _interpret_vegas(item),
        _interpret_ichimoku(item),
        _interpret_obv(item),
        _interpret_avwap(item),
        _interpret_volume_profile(item),
        _interpret_fibonacci(item),
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
