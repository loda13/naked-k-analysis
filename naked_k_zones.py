from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ZoneCandidate:
    kind: str
    price: float
    volume: float
    position: int


def _clean_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    clean = frame[["Open", "High", "Low", "Close", "Volume"]].dropna().copy()
    clean.index = pd.to_datetime(clean.index)
    return clean.sort_index()


def _average_range(clean: pd.DataFrame) -> float:
    if clean.empty:
        return 0.0
    ranges = clean["High"].astype(float) - clean["Low"].astype(float)
    return float(ranges.mean())


def _cluster_tolerance(clean: pd.DataFrame, close: float) -> float:
    average_range = _average_range(clean)
    return round(max(average_range * 0.2, close * 0.004), 4)


def _strength(touches: int, volume_ratio: float) -> str:
    if touches >= 3 or volume_ratio >= 1.5:
        return "strong"
    if touches == 2 or volume_ratio >= 1.1:
        return "developing"
    return "weak"


def _find_candidates(clean: pd.DataFrame, swing_window: int) -> list[ZoneCandidate]:
    if len(clean) < swing_window * 2 + 1:
        return []

    highs = clean["High"].astype(float)
    lows = clean["Low"].astype(float)
    volumes = clean["Volume"].astype(float)
    candidates: list[ZoneCandidate] = []
    for position in range(swing_window, len(clean) - swing_window):
        high_window = highs.iloc[position - swing_window : position + swing_window + 1]
        low_window = lows.iloc[position - swing_window : position + swing_window + 1]
        high = float(highs.iloc[position])
        low = float(lows.iloc[position])
        neighbor_highs = high_window.drop(high_window.index[swing_window])
        neighbor_lows = low_window.drop(low_window.index[swing_window])
        volume = float(volumes.iloc[position])

        if high == float(high_window.max()) and high > float(neighbor_highs.max()):
            candidates.append(ZoneCandidate("supply", round(high, 2), volume, position))
        if low == float(low_window.min()) and low < float(neighbor_lows.min()):
            candidates.append(ZoneCandidate("demand", round(low, 2), volume, position))
    return candidates


def _generate_zone_id(kind: str, lower: float, upper: float, member_positions: list[int]) -> str:
    """生成稳定的 zone_id，基于价格范围和成员位置"""
    positions_str = ",".join(str(p) for p in sorted(member_positions))
    content = f"{kind}:{lower:.2f}:{upper:.2f}:{positions_str}"
    hash_digest = hashlib.sha256(content.encode()).hexdigest()[:12]
    return f"zone-{hash_digest}"


def _generate_pool_id(kind: str, midpoint: float) -> str:
    """生成稳定的 pool_id，基于类型和中点价格"""
    content = f"{kind}:{midpoint:.2f}"
    hash_digest = hashlib.sha256(content.encode()).hexdigest()[:12]
    return f"pool-{hash_digest}"


def _cluster_candidates(
    candidates: list[ZoneCandidate],
    kind: str,
    close: float,
    tolerance: float,
    average_volume: float,
    clean: pd.DataFrame,
) -> list[dict[str, Any]]:
    kind_candidates = sorted([candidate for candidate in candidates if candidate.kind == kind], key=lambda item: item.price)
    clusters: list[list[ZoneCandidate]] = []
    for candidate in kind_candidates:
        if not clusters:
            clusters.append([candidate])
            continue
        cluster_midpoint = sum(item.price for item in clusters[-1]) / len(clusters[-1])
        if abs(candidate.price - cluster_midpoint) <= tolerance:
            clusters[-1].append(candidate)
        else:
            clusters.append([candidate])

    zones: list[dict[str, Any]] = []
    for cluster in clusters:
        prices = [item.price for item in cluster]
        positions = [item.position for item in cluster]
        total_volume = sum(item.volume for item in cluster)
        volume_ratio = total_volume / (average_volume * len(cluster)) if average_volume > 0 else 1.0
        lower = round(min(prices), 2)
        upper = round(max(prices), 2)
        midpoint = round(sum(prices) / len(prices), 2)
        side = "below" if midpoint < close else "above"
        zone_id = _generate_zone_id(kind, lower, upper, positions)
        member_dates = [str(clean.index[pos].date()) for pos in positions]
        zones.append(
            {
                "kind": kind,
                "label": "需求区" if kind == "demand" else "供给区",
                "lower": lower,
                "upper": upper,
                "midpoint": midpoint,
                "touches": len(cluster),
                "strength": _strength(len(cluster), volume_ratio),
                "side": side,
                "source": "swing_cluster",
                "volume_ratio": round(volume_ratio, 2),
                "zone_id": zone_id,
                "member_dates": member_dates,
            }
        )
    return zones


def _build_liquidity_pools(zones: list[dict[str, Any]], close: float) -> list[dict[str, Any]]:
    pools: list[dict[str, Any]] = []
    for zone in zones:
        if int(zone["touches"]) < 2:
            continue
        if zone["kind"] == "supply" and float(zone["midpoint"]) > close:
            kind = "buy_side_liquidity"
            label = "上方买方流动性池"
        elif zone["kind"] == "demand" and float(zone["midpoint"]) < close:
            kind = "sell_side_liquidity"
            label = "下方卖方流动性池"
        else:
            continue
        payload = dict(zone)
        pool_id = _generate_pool_id(kind, float(zone["midpoint"]))
        payload.update({"kind": kind, "label": label, "source": "equal_high_low_cluster", "pool_id": pool_id})
        pools.append(payload)
    return sorted(
        pools,
        key=lambda zone: (
            0 if zone["kind"] == "buy_side_liquidity" else 1,
            abs(float(zone["midpoint"]) - close),
        ),
    )


def _volume_zones(clean: pd.DataFrame, bins: int) -> list[dict[str, Any]]:
    profile = _volume_profile(clean, bins)
    poc = profile.get("poc") if profile else None
    if not poc:
        return []
    return [
        {
            "kind": "volume_node",
            "label": "成交密集区",
            "lower": poc["lower"],
            "upper": poc["upper"],
            "midpoint": poc["midpoint"],
            "touches": None,
            "strength": "strong" if float(poc["volume_share"]) >= 0.35 else "developing",
            "side": "volume",
            "source": "volume_profile",
            "volume_share": poc["volume_share"],
        }
    ]


def _volume_profile(clean: pd.DataFrame, bins: int, value_area_ratio: float = 0.70) -> dict[str, Any]:
    if clean.empty or bins <= 0:
        return {"buckets": [], "poc": None, "value_area": None}

    low = float(clean["Low"].min())
    high = float(clean["High"].max())
    if high <= low:
        return {"buckets": [], "poc": None, "value_area": None}

    bin_width = (high - low) / bins
    buckets = [
        {
            "index": i,
            "lower": low + i * bin_width,
            "upper": low + (i + 1) * bin_width,
            "midpoint": low + (i + 0.5) * bin_width,
            "volume": 0.0,
        }
        for i in range(bins)
    ]
    typical_prices = (clean["High"].astype(float) + clean["Low"].astype(float) + clean["Close"].astype(float)) / 3
    volumes = clean["Volume"].astype(float)
    for price, volume in zip(typical_prices, volumes, strict=False):
        bucket_index = min(int((float(price) - low) / bin_width), bins - 1)
        buckets[bucket_index]["volume"] += float(volume)

    total_volume = sum(bucket["volume"] for bucket in buckets)
    if total_volume <= 0:
        return {"buckets": [], "poc": None, "value_area": None}

    buckets = sorted(buckets, key=lambda bucket: int(bucket["index"]))
    for bucket in buckets:
        bucket["lower"] = round(float(bucket["lower"]), 2)
        bucket["upper"] = round(float(bucket["upper"]), 2)
        bucket["midpoint"] = round(float(bucket["midpoint"]), 2)
        bucket["volume"] = round(float(bucket["volume"]), 2)
        bucket["volume_share"] = round(float(bucket["volume"]) / total_volume, 2)

    poc_bucket = max(buckets, key=lambda bucket: float(bucket["volume"]))
    selected = {int(poc_bucket["index"])}
    cumulative_volume = float(poc_bucket["volume"])
    while cumulative_volume / total_volume < value_area_ratio and len(selected) < len(buckets):
        left = min(selected) - 1
        right = max(selected) + 1
        left_volume = float(buckets[left]["volume"]) if left >= 0 else -1.0
        right_volume = float(buckets[right]["volume"]) if right < len(buckets) else -1.0
        if right_volume >= left_volume and right < len(buckets):
            selected.add(right)
            cumulative_volume += right_volume
        elif left >= 0:
            selected.add(left)
            cumulative_volume += left_volume
        else:
            break

    selected_buckets = [bucket for bucket in buckets if int(bucket["index"]) in selected]
    value_area = {
        "kind": "value_area",
        "label": "价值区域",
        "lower": round(min(float(bucket["lower"]) for bucket in selected_buckets), 2),
        "upper": round(max(float(bucket["upper"]) for bucket in selected_buckets), 2),
        "midpoint": round(
            (
                min(float(bucket["lower"]) for bucket in selected_buckets)
                + max(float(bucket["upper"]) for bucket in selected_buckets)
            )
            / 2,
            2,
        ),
        "volume_share": round(cumulative_volume / total_volume, 2),
    }
    poc = {
        "kind": "point_of_control",
        "label": "POC成交控制点",
        "lower": poc_bucket["lower"],
        "upper": poc_bucket["upper"],
        "midpoint": poc_bucket["midpoint"],
        "volume": poc_bucket["volume"],
        "volume_share": poc_bucket["volume_share"],
        "source": "volume_profile",
    }
    return {
        "buckets": buckets,
        "poc": poc,
        "value_area": value_area,
        "total_volume": round(total_volume, 2),
    }


def _anchored_vwap(clean: pd.DataFrame, close: float, swing_window: int) -> dict[str, Any] | None:
    candidates = _find_candidates(clean, swing_window=swing_window)
    if not candidates:
        return None
    if close >= float(clean["Close"].iloc[0]):
        swing_lows = [candidate for candidate in candidates if candidate.kind == "demand"]
        anchor = swing_lows[-1] if swing_lows else min(candidates, key=lambda item: item.price)
        anchor_type = "swing_low"
    else:
        swing_highs = [candidate for candidate in candidates if candidate.kind == "supply"]
        anchor = swing_highs[-1] if swing_highs else max(candidates, key=lambda item: item.price)
        anchor_type = "swing_high"

    anchored = clean.iloc[anchor.position :].copy()
    if anchored.empty:
        return None
    typical = (anchored["High"].astype(float) + anchored["Low"].astype(float) + anchored["Close"].astype(float)) / 3
    volume = anchored["Volume"].astype(float)
    volume_sum = float(volume.sum())
    if volume_sum <= 0:
        return None
    value = float((typical * volume).sum() / volume_sum)
    return {
        "kind": "anchored_vwap",
        "label": "Anchored VWAP",
        "anchor_type": anchor_type,
        "anchor_date": pd.Timestamp(clean.index[anchor.position]).strftime("%Y-%m-%d"),
        "anchor_price": round(float(anchor.price), 2),
        "value": round(value, 2),
        "side": "below" if value < close else "above",
        "source": "structural_swing",
    }


def _nearest(zones: list[dict[str, Any]], close: float, side: str) -> dict[str, Any] | None:
    if side == "support":
        candidates = [zone for zone in zones if float(zone["midpoint"]) < close and zone["kind"] == "demand"]
        candidates.sort(key=lambda zone: float(zone["midpoint"]), reverse=True)
    else:
        candidates = [zone for zone in zones if float(zone["midpoint"]) > close and zone["kind"] == "supply"]
        candidates.sort(key=lambda zone: float(zone["midpoint"]))
    return candidates[0] if candidates else None


def detect_price_zones(
    frame: pd.DataFrame,
    close: float | None = None,
    lookback: int = 60,
    swing_window: int = 2,
    bins: int = 8,
) -> dict[str, Any]:
    clean = _clean_ohlcv(frame).tail(lookback)
    if clean.empty:
        return {
            "zones": [],
            "support_zones": [],
            "resistance_zones": [],
            "liquidity_pools": [],
            "volume_zones": [],
            "volume_profile": {"buckets": [], "poc": None, "value_area": None},
            "anchored_vwap": None,
            "nearest_support": None,
            "nearest_resistance": None,
        }

    latest_close = float(close if close is not None else clean["Close"].iloc[-1])
    tolerance = _cluster_tolerance(clean, latest_close)
    average_volume = float(clean["Volume"].astype(float).mean())
    candidates = _find_candidates(clean, swing_window=swing_window)
    support_zones = _cluster_candidates(candidates, "demand", latest_close, tolerance, average_volume, clean)
    resistance_zones = _cluster_candidates(candidates, "supply", latest_close, tolerance, average_volume, clean)
    zones = sorted(support_zones + resistance_zones, key=lambda zone: abs(float(zone["midpoint"]) - latest_close))
    liquidity_pools = _build_liquidity_pools(zones, latest_close)
    volume_profile = _volume_profile(clean, bins)
    volume_zones = _volume_zones(clean, bins)
    anchored_vwap = _anchored_vwap(clean, latest_close, swing_window=swing_window)

    return {
        "zones": zones,
        "support_zones": support_zones,
        "resistance_zones": resistance_zones,
        "liquidity_pools": liquidity_pools,
        "volume_zones": volume_zones,
        "volume_profile": volume_profile,
        "anchored_vwap": anchored_vwap,
        "nearest_support": _nearest(zones, latest_close, "support"),
        "nearest_resistance": _nearest(zones, latest_close, "resistance"),
        "tolerance": tolerance,
    }
