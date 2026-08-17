"""
naked_k_smart_money.py

主力资金行为识别模块 - Smart Money Concepts (SMC)

识别机构/大资金的建仓、吸筹、扫单等行为模式。
只使用OHLCV数据，不依赖付费数据源。

设计原则：
1. 纯价格+成交量分析，无黑盒指标
2. 所有计算确定性可重现
3. 返回结构化信号，附带置信度评分
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def _clean_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    """清洗和标准化OHLCV数据"""
    if frame.empty:
        return frame.copy()
    clean = frame[["Open", "High", "Low", "Close", "Volume"]].dropna().copy()
    clean.index = pd.to_datetime(clean.index)
    return clean.sort_index()


def detect_accumulation_volume(
    frame: pd.DataFrame,
    window: int = 20,
    volume_threshold: float = 2.0,
    price_cluster_threshold: float = 0.02,
) -> list[dict[str, Any]]:
    """
    识别吸筹成交量模式

    特征：
    - 成交量显著放大（> 均量的 volume_threshold 倍）
    - 收盘价在K线上半部分（拒绝下跌，买盘强劲）
    - 价格在相似区间反复震荡（同一位置吸筹）

    Args:
        frame: OHLCV数据
        window: 均量计算窗口
        volume_threshold: 成交量异常倍数
        price_cluster_threshold: 价格聚集判断阈值

    Returns:
        吸筹信号列表，每个信号包含位置、强度、置信度
    """
    clean = _clean_ohlcv(frame)
    if len(clean) < window + 3:
        return []

    volume_ma = clean["Volume"].rolling(window).mean()
    signals: list[dict[str, Any]] = []

    for i in range(window, len(clean) - 2):
        current_volume = float(clean["Volume"].iloc[i])
        avg_volume = float(volume_ma.iloc[i])

        if avg_volume == 0:
            continue

        vol_ratio = current_volume / avg_volume

        # 成交量异常
        if vol_ratio < volume_threshold:
            continue

        # 价格行为：收盘在K线上半区（买盘强劲）
        close = float(clean["Close"].iloc[i])
        low = float(clean["Low"].iloc[i])
        high = float(clean["High"].iloc[i])
        candle_range = high - low

        if candle_range == 0:
            body_position = 0.5
        else:
            body_position = (close - low) / candle_range

        if body_position < 0.5:
            continue

        # 价格聚集：后续2根K线收盘价在相似区间
        next_closes = clean["Close"].iloc[i : i + 3]
        price_std = float(next_closes.std())
        price_cluster = (price_std / close) < price_cluster_threshold if close > 0 else False

        if not price_cluster:
            continue

        # 计算信号强度
        strength = "strong" if vol_ratio > 3.0 and body_position > 0.7 else "developing"
        confidence = min(95, int(40 + vol_ratio * 10 + body_position * 30))

        signals.append(
            {
                "type": "accumulation",
                "date": str(clean.index[i]),
                "position": i,
                "price": round(close, 2),
                "volume_ratio": round(vol_ratio, 2),
                "body_position": round(body_position, 2),
                "strength": strength,
                "confidence_score": confidence,
                "thesis": f"放量{vol_ratio:.1f}倍但价格窄幅震荡，显示低位吸筹",
            }
        )

    return signals


def analyze_sweep_quality(
    sweep_candle: dict[str, Any],
    recovery_candles: list[dict[str, Any]],
    reference_zone: dict[str, Any],
    sweep_type: str = "bullish",
) -> dict[str, Any]:
    """
    评估流动性扫荡后的反转质量

    高质量bullish扫荡信号：
    - 长下影线，收盘价收回大部分跌幅（拒绝下跌）
    - 后续K线快速站稳需求区上沿
    - 扫荡K成交量 > 回收K成交量（洗盘充分）

    Args:
        sweep_candle: 扫荡K线数据
        recovery_candles: 后续1-2根恢复K线
        reference_zone: 参考需求区/供给区
        sweep_type: 'bullish' 或 'bearish'

    Returns:
        质量评估结果，包含评分和组成部分
    """
    if not sweep_candle or not recovery_candles:
        return {"quality": "invalid", "confidence_score": 0}

    sweep_low = float(sweep_candle.get("Low", 0))
    sweep_high = float(sweep_candle.get("High", 0))
    sweep_close = float(sweep_candle.get("Close", 0))
    sweep_volume = float(sweep_candle.get("Volume", 1))

    candle_range = sweep_high - sweep_low
    if candle_range == 0:
        return {"quality": "weak", "confidence_score": 20}

    quality_score = 0

    if sweep_type == "bullish":
        # 反转力度：下影线收回比例
        wick_recovery = (sweep_close - sweep_low) / candle_range
        quality_score += int(wick_recovery * 40)

        # 后续确认：收盘站稳需求区上沿
        zone_upper = float(reference_zone.get("upper", sweep_close))
        reclaim_zone = all(float(c.get("Close", 0)) > zone_upper for c in recovery_candles)
        if reclaim_zone:
            quality_score += 30

    else:  # bearish
        # 反转力度：上影线收回比例
        wick_recovery = (sweep_high - sweep_close) / candle_range
        quality_score += int(wick_recovery * 40)

        # 后续确认：收盘跌破供给区下沿
        zone_lower = float(reference_zone.get("lower", sweep_close))
        reclaim_zone = all(float(c.get("Close", 0)) < zone_lower for c in recovery_candles)
        if reclaim_zone:
            quality_score += 30

    # 成交量对比：洗盘后缩量是健康的
    recovery_volumes = [float(c.get("Volume", 1)) for c in recovery_candles]
    avg_recovery_volume = sum(recovery_volumes) / len(recovery_volumes) if recovery_volumes else 1
    volume_contrast = sweep_volume / avg_recovery_volume if avg_recovery_volume > 0 else 1

    if volume_contrast > 1.5:
        quality_score += 30
    elif volume_contrast > 1.2:
        quality_score += 15

    quality_score = min(100, quality_score)
    quality_label = "strong" if quality_score >= 70 else "developing" if quality_score >= 50 else "weak"

    direction_text = "下方" if sweep_type == "bullish" else "上方"
    thesis = f"{direction_text}流动性扫荡后快速收回，显示{'买盘' if sweep_type == 'bullish' else '卖压'}强劲"

    return {
        "quality": quality_label,
        "confidence_score": quality_score,
        "thesis": thesis,
        "components": {
            "wick_recovery": round(wick_recovery, 2),
            "reclaim_confirmed": reclaim_zone,
            "volume_contrast": round(volume_contrast, 2),
        },
    }


def detect_selling_exhaustion(frame: pd.DataFrame, lookback: int = 10, volume_window: int = 20) -> dict[str, Any]:
    """
    识别卖压衰竭信号（抄底前兆）

    特征：
    - 价格创近期新低（空头仍在推进）
    - 成交量持续萎缩（卖压减弱）
    - 下跌速度变缓（斜率变平）

    Args:
        frame: OHLCV数据
        lookback: 判断新低的回溯窗口
        volume_window: 均量计算窗口

    Returns:
        衰竭信号，包含强度和组成指标
    """
    clean = _clean_ohlcv(frame)
    if len(clean) < max(lookback, volume_window) + 10:
        return {}

    recent_low = float(clean["Low"].iloc[-lookback:].min())
    current_low = float(clean["Low"].iloc[-1])
    current_close = float(clean["Close"].iloc[-1])

    # 价格新低
    new_low = current_low <= recent_low * 1.001  # 允许0.1%误差

    if not new_low:
        return {}

    # 成交量萎缩
    volume_ma = clean["Volume"].rolling(volume_window).mean()
    recent_volume = float(clean["Volume"].iloc[-3:].mean())
    avg_volume = float(volume_ma.iloc[-1])

    if avg_volume == 0:
        return {}

    volume_ratio = recent_volume / avg_volume
    volume_dried = volume_ratio < 0.8

    # 下跌减速
    if len(clean) < lookback + 10:
        return {}

    close_series = clean["Close"].astype(float)
    slope_recent = (float(close_series.iloc[-lookback]) - float(close_series.iloc[-1])) / lookback
    slope_earlier = (float(close_series.iloc[-lookback - 7]) - float(close_series.iloc[-lookback])) / 7

    deceleration = False
    slope_change_ratio = 0.0
    if abs(slope_earlier) > 0.001:  # 避免除零
        slope_change_ratio = slope_recent / slope_earlier
        deceleration = slope_change_ratio < 0.5

    if not (volume_dried and deceleration):
        return {}

    # 计算置信度
    confidence = 50
    if volume_ratio < 0.6:
        confidence += 20
    if slope_change_ratio < 0.3:
        confidence += 20
    if current_close > current_low + (clean["High"].iloc[-1] - current_low) * 0.5:
        confidence += 10  # 收在K线上半区

    return {
        "signal": "selling_exhaustion",
        "strength": "strong" if confidence >= 70 else "developing",
        "confidence_score": min(95, confidence),
        "thesis": "价格新低但量能萎缩，卖压衰竭，底部可能形成",
        "components": {
            "volume_ratio": round(volume_ratio, 2),
            "slope_change": round(slope_change_ratio, 2),
            "current_price": round(current_close, 2),
        },
    }


def detect_buying_exhaustion(frame: pd.DataFrame, lookback: int = 10, volume_window: int = 20) -> dict[str, Any]:
    """
    识别买盘衰竭信号（见顶前兆）

    特征：
    - 价格创近期新高（多头仍在推进）
    - 成交量持续萎缩（买盘减弱）
    - 上涨速度变缓（斜率变平）

    Args:
        frame: OHLCV数据
        lookback: 判断新高的回溯窗口
        volume_window: 均量计算窗口

    Returns:
        衰竭信号，包含强度和组成指标
    """
    clean = _clean_ohlcv(frame)
    if len(clean) < max(lookback, volume_window) + 10:
        return {}

    recent_high = float(clean["High"].iloc[-lookback:].max())
    current_high = float(clean["High"].iloc[-1])
    current_close = float(clean["Close"].iloc[-1])

    # 价格新高
    new_high = current_high >= recent_high * 0.999  # 允许0.1%误差

    if not new_high:
        return {}

    # 成交量萎缩
    volume_ma = clean["Volume"].rolling(volume_window).mean()
    recent_volume = float(clean["Volume"].iloc[-3:].mean())
    avg_volume = float(volume_ma.iloc[-1])

    if avg_volume == 0:
        return {}

    volume_ratio = recent_volume / avg_volume
    volume_dried = volume_ratio < 0.8

    # 上涨减速
    if len(clean) < lookback + 10:
        return {}

    close_series = clean["Close"].astype(float)
    slope_recent = (float(close_series.iloc[-1]) - float(close_series.iloc[-lookback])) / lookback
    slope_earlier = (float(close_series.iloc[-lookback]) - float(close_series.iloc[-lookback - 7])) / 7

    deceleration = False
    slope_change_ratio = 0.0
    if abs(slope_earlier) > 0.001:
        slope_change_ratio = slope_recent / slope_earlier
        deceleration = slope_change_ratio < 0.5

    if not (volume_dried and deceleration):
        return {}

    # 计算置信度
    confidence = 50
    if volume_ratio < 0.6:
        confidence += 20
    if slope_change_ratio < 0.3:
        confidence += 20
    if current_close < current_high - (current_high - clean["Low"].iloc[-1]) * 0.5:
        confidence += 10  # 收在K线下半区

    return {
        "signal": "buying_exhaustion",
        "strength": "strong" if confidence >= 70 else "developing",
        "confidence_score": min(95, confidence),
        "thesis": "价格新高但量能萎缩，买盘衰竭，顶部可能形成",
        "components": {
            "volume_ratio": round(volume_ratio, 2),
            "slope_change": round(slope_change_ratio, 2),
            "current_price": round(current_close, 2),
        },
    }


def detect_multi_tf_confluence(
    monthly_zones: list[dict[str, Any]],
    weekly_zones: list[dict[str, Any]],
    daily_zones: list[dict[str, Any]],
    daily_price: float,
    direction: str = "bullish",
) -> dict[str, Any]:
    """
    识别多周期需求区/供给区共振

    强信号：
    - bullish: 日线价格在周线需求区内，且周线在月线需求区内
    - bearish: 日线价格在周线供给区内，且周线在月线供给区内

    Args:
        monthly_zones: 月线供需区
        weekly_zones: 周线供需区
        daily_zones: 日线供需区
        daily_price: 当前日线价格
        direction: 'bullish' 或 'bearish'

    Returns:
        共振信号，包含强度和相关区域
    """
    zone_kind = "demand" if direction == "bullish" else "supply"

    # 日线价格在周线区域内
    daily_in_weekly = False
    weekly_zone_match = None
    for zone in weekly_zones:
        if zone.get("kind") != zone_kind:
            continue
        lower = float(zone.get("lower", 0))
        upper = float(zone.get("upper", 0))
        if lower <= daily_price <= upper:
            daily_in_weekly = True
            weekly_zone_match = zone
            break

    if not daily_in_weekly:
        return {}

    # 周线区域在月线区域内
    weekly_in_monthly = False
    monthly_zone_match = None
    if weekly_zone_match:
        weekly_mid = float(weekly_zone_match.get("midpoint", daily_price))
        for zone in monthly_zones:
            if zone.get("kind") != zone_kind:
                continue
            lower = float(zone.get("lower", 0))
            upper = float(zone.get("upper", 0))
            if lower <= weekly_mid <= upper:
                weekly_in_monthly = True
                monthly_zone_match = zone
                break

    if not weekly_in_monthly:
        return {}

    # 计算置信度：考虑区域强度
    base_confidence = 75
    weekly_strength = str(weekly_zone_match.get("strength", "weak"))
    monthly_strength = str(monthly_zone_match.get("strength", "weak"))

    if weekly_strength == "strong":
        base_confidence += 5
    if monthly_strength == "strong":
        base_confidence += 5

    direction_text = "需求" if direction == "bullish" else "供给"
    action_text = "长期布局" if direction == "bullish" else "长期派发"

    return {
        "signal": f"multi_tf_{zone_kind}_confluence",
        "strength": "strong",
        "confidence_score": min(95, base_confidence),
        "thesis": f"日线、周线、月线{direction_text}区三重共振，主力{action_text}区域",
        "zones": {
            "monthly": {
                "range": f"{monthly_zone_match.get('lower')}-{monthly_zone_match.get('upper')}",
                "strength": monthly_strength,
            },
            "weekly": {
                "range": f"{weekly_zone_match.get('lower')}-{weekly_zone_match.get('upper')}",
                "strength": weekly_strength,
            },
        },
    }


def analyze_smart_money_signals(
    daily_df: pd.DataFrame,
    zones: list[dict[str, Any]],
    liquidity_pools: list[dict[str, Any]],
    market_structure: dict[str, Any],
    monthly_zones: list[dict[str, Any]] | None = None,
    weekly_zones: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    综合分析所有主力资金信号

    Args:
        daily_df: 日线OHLCV数据
        zones: 日线供需区
        liquidity_pools: 流动性池
        market_structure: 市场结构
        monthly_zones: 月线供需区（可选）
        weekly_zones: 周线供需区（可选）

    Returns:
        主力信号汇总，包含各类信号和综合评估
    """
    if daily_df.empty:
        return {"enabled": False, "signals": []}

    signals: list[dict[str, Any]] = []

    # 1. 吸筹成交量模式
    accumulation_signals = detect_accumulation_volume(daily_df)
    if accumulation_signals:
        latest_acc = accumulation_signals[-1]  # 最近的吸筹信号
        signals.append(
            {
                "category": "accumulation",
                "label": "吸筹信号",
                "strength": latest_acc["strength"],
                "confidence": latest_acc["confidence_score"],
                "thesis": latest_acc["thesis"],
                "date": latest_acc["date"],
                "details": f"成交量放大{latest_acc['volume_ratio']}倍",
            }
        )

    # 2. 卖压衰竭
    exhaustion = detect_selling_exhaustion(daily_df)
    if exhaustion:
        signals.append(
            {
                "category": "exhaustion",
                "label": "卖压衰竭",
                "strength": exhaustion["strength"],
                "confidence": exhaustion["confidence_score"],
                "thesis": exhaustion["thesis"],
                "details": f"成交量萎缩至{exhaustion['components']['volume_ratio']*100:.0f}%",
            }
        )

    # 3. 买盘衰竭
    buying_exhaustion = detect_buying_exhaustion(daily_df)
    if buying_exhaustion:
        signals.append(
            {
                "category": "buying_exhaustion",
                "label": "买盘衰竭",
                "strength": buying_exhaustion["strength"],
                "confidence": buying_exhaustion["confidence_score"],
                "thesis": buying_exhaustion["thesis"],
                "details": f"成交量萎缩至{buying_exhaustion['components']['volume_ratio']*100:.0f}%",
            }
        )

    # 4. 多周期共振（如果有周线和月线数据）
    current_price = float(daily_df["Close"].iloc[-1])
    if monthly_zones and weekly_zones:
        bullish_confluence = detect_multi_tf_confluence(monthly_zones, weekly_zones, zones, current_price, "bullish")
        if bullish_confluence:
            signals.append(
                {
                    "category": "confluence",
                    "label": "多周期需求共振",
                    "strength": bullish_confluence["strength"],
                    "confidence": bullish_confluence["confidence_score"],
                    "thesis": bullish_confluence["thesis"],
                    "details": f"月线区间 {bullish_confluence['zones']['monthly']['range']}",
                }
            )

        bearish_confluence = detect_multi_tf_confluence(monthly_zones, weekly_zones, zones, current_price, "bearish")
        if bearish_confluence:
            signals.append(
                {
                    "category": "confluence",
                    "label": "多周期供给共振",
                    "strength": bearish_confluence["strength"],
                    "confidence": bearish_confluence["confidence_score"],
                    "thesis": bearish_confluence["thesis"],
                    "details": f"月线区间 {bearish_confluence['zones']['monthly']['range']}",
                }
            )

    # 综合评估
    if not signals:
        return {"enabled": True, "signals": [], "overall_assessment": "无明显主力信号"}

    # 计算综合概率
    bullish_signals = [s for s in signals if s["category"] in ("accumulation", "exhaustion", "confluence")]
    bearish_signals = [s for s in signals if s["category"] in ("buying_exhaustion")]

    bullish_confidence = sum(s["confidence"] for s in bullish_signals) / len(bullish_signals) if bullish_signals else 0
    bearish_confidence = sum(s["confidence"] for s in bearish_signals) / len(bearish_signals) if bearish_signals else 0

    if bullish_confidence > bearish_confidence:
        direction = "bullish"
        probability = int(bullish_confidence)
        assessment = f"主力抄底概率 {probability}%"
    else:
        direction = "bearish"
        probability = int(bearish_confidence)
        assessment = f"主力派发概率 {probability}%"

    return {
        "enabled": True,
        "signals": signals,
        "overall_assessment": assessment,
        "direction": direction,
        "probability": probability,
    }
