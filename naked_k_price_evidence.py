"""
价格行为证据层 (Price Action Evidence Layer)

实现 §8 规范的点时价格证据：只用 OHLCV、可追溯 zone/pool 和市场结构，
不引入任何技术指标。输出离散状态和原始统计，没有概率或评分。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import pandas as pd

from naked_k_config import PriceActionEvidenceConfig
from naked_k_smart_money_contracts import (
    Direction,
    Lifecycle,
    LayerResult,
    content_id,
)

# §8.1: 基线窗口固定 20 个完整日线
BASELINE_WINDOW = 20
# §8.1: 位置容差为 range_baseline 的 0.25 倍
LOCATION_TOLERANCE_RATIO = 0.25
# §8.1: 确认窗口五个交易日
CONFIRMATION_WINDOW = 5
# 规则版本，进入 evidence_id 的 preimage
RULE_VERSION = "price-action.v1"
SCHEMA_VERSION = "price-action-layer.v1"


@dataclass(frozen=True, kw_only=True)
class PriceEvidence:
    """单条价格行为证据。inputs 保存原始统计，thresholds 保存触发阈值。"""

    evidence_id: str
    kind: str
    direction: str
    lifecycle: str
    dependency_group: str
    signal_at: pd.Timestamp
    observed_at: pd.Timestamp
    available_at: pd.Timestamp
    expires_at: pd.Timestamp | None
    signal_high: float
    signal_low: float
    inputs: dict[str, Any]
    thresholds: dict[str, Any]
    location_ids: tuple[str, ...]
    lineage_ids: tuple[str, ...] = ()
    validation_status: str = "UNVALIDATED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "direction": self.direction,
            "lifecycle": self.lifecycle,
            "dependency_group": self.dependency_group,
            "signal_at": self.signal_at.isoformat(),
            "observed_at": self.observed_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "signal_high": self.signal_high,
            "signal_low": self.signal_low,
            "inputs": self.inputs,
            "thresholds": self.thresholds,
            "location_ids": list(self.location_ids),
            "lineage_ids": list(self.lineage_ids),
            "validation_status": self.validation_status,
        }


@dataclass(frozen=True)
class _Baseline:
    """信号 K 之前 20 根的基线统计。"""

    volume_baseline: float
    range_baseline: float
    prior_low: float
    prior_high: float
    previous_close: float


def _clean(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    clean = frame[["Open", "High", "Low", "Close", "Volume"]].dropna().copy()
    clean.index = pd.to_datetime(clean.index)
    return clean.sort_index()


def _baseline_at(clean: pd.DataFrame, position: int) -> _Baseline | None:
    """§8.1: baseline 只用信号 K 之前的 20 个完整日线，排除信号 K 自身。"""
    if position < BASELINE_WINDOW:
        return None
    window = clean.iloc[position - BASELINE_WINDOW : position]
    volume_baseline = float(window["Volume"].astype(float).median())
    ranges = window["High"].astype(float) - window["Low"].astype(float)
    range_baseline = float(ranges.median())
    if volume_baseline <= 0 or range_baseline <= 0:
        return None
    return _Baseline(
        volume_baseline=volume_baseline,
        range_baseline=range_baseline,
        prior_low=float(window["Low"].astype(float).min()),
        prior_high=float(window["High"].astype(float).max()),
        previous_close=float(clean["Close"].astype(float).iloc[position - 1]),
    )


def _close_position(high: float, low: float, close: float) -> float:
    """§8.1: (Close-Low)/(High-Low)；零振幅时为 0.5。"""
    span = high - low
    if span <= 0:
        return 0.5
    return (close - low) / span


def _traceable(items: Sequence[Mapping[str, Any]], id_key: str) -> list[Mapping[str, Any]]:
    """§8.1: 没有可追溯 ID 的 zone/pool 不能作为位置条件。"""
    return [item for item in items if item.get(id_key)]


def _in_demand_location(
    *,
    low: float,
    high: float,
    close: float,
    zones: Sequence[Mapping[str, Any]],
    pools: Sequence[Mapping[str, Any]],
    range_baseline: float,
) -> tuple[str, ...]:
    """§8.1: 需求区相交或 0<=Low-zone_high<=0.25*range_baseline；
    sell-side liquidity 要求 Low<=L 且 Close>=L。"""
    tolerance = LOCATION_TOLERANCE_RATIO * range_baseline
    hits: list[str] = []
    for zone in _traceable(zones, "zone_id"):
        if str(zone.get("kind")) != "demand":
            continue
        zone_low = float(zone["lower"])
        zone_high = float(zone["upper"])
        intersects = low <= zone_high and high >= zone_low
        near = 0.0 <= low - zone_high <= tolerance
        if intersects or near:
            hits.append(str(zone["zone_id"]))
    for pool in _traceable(pools, "pool_id"):
        if str(pool.get("kind")) != "sell_side_liquidity":
            continue
        level = float(pool["midpoint"])
        if low <= level and close >= level:
            hits.append(str(pool["pool_id"]))
    return tuple(hits)


def _in_supply_location(
    *,
    low: float,
    high: float,
    close: float,
    zones: Sequence[Mapping[str, Any]],
    pools: Sequence[Mapping[str, Any]],
    range_baseline: float,
) -> tuple[str, ...]:
    """§8.2: 严格镜像 —— 供给区相交或 0<=zone_low-High<=0.25*range_baseline；
    buy-side liquidity 要求 High>=L 且 Close<=L。"""
    tolerance = LOCATION_TOLERANCE_RATIO * range_baseline
    hits: list[str] = []
    for zone in _traceable(zones, "zone_id"):
        if str(zone.get("kind")) != "supply":
            continue
        zone_low = float(zone["lower"])
        zone_high = float(zone["upper"])
        intersects = high >= zone_low and low <= zone_high
        near = 0.0 <= zone_low - high <= tolerance
        if intersects or near:
            hits.append(str(zone["zone_id"]))
    for pool in _traceable(pools, "pool_id"):
        if str(pool.get("kind")) != "buy_side_liquidity":
            continue
        level = float(pool["midpoint"])
        if high >= level and close <= level:
            hits.append(str(pool["pool_id"]))
    return tuple(hits)


def _evidence_id(
    *,
    kind: str,
    signal_at: pd.Timestamp,
    inputs: Mapping[str, Any],
    thresholds: Mapping[str, Any],
    location_ids: Sequence[str],
) -> str:
    """§Task1: evidence_id = rule version + 语义输入 + 时间 + inputs/thresholds。
    未来 K 线不进入 preimage，所以确认不会改写既有 ID。"""
    return content_id(
        "evidence",
        {
            "rule_version": RULE_VERSION,
            "kind": kind,
            "signal_at": signal_at.isoformat(),
            "inputs": dict(inputs),
            "thresholds": dict(thresholds),
            "location_ids": sorted(location_ids),
        },
    )


def _decline_pair(clean: pd.DataFrame, position: int) -> tuple[float, float] | None:
    """§8.1: prior_decline=max(0, Close[t-10]-Close[t-5])，
    recent_decline=max(0, Close[t-5]-Close[t])。"""
    if position < 10:
        return None
    closes = clean["Close"].astype(float)
    prior = max(0.0, float(closes.iloc[position - 10]) - float(closes.iloc[position - 5]))
    recent = max(0.0, float(closes.iloc[position - 5]) - float(closes.iloc[position]))
    return prior, recent


def _detect_at(
    clean: pd.DataFrame,
    position: int,
    *,
    zones: Sequence[Mapping[str, Any]],
    liquidity_pools: Sequence[Mapping[str, Any]],
    config: PriceActionEvidenceConfig,
) -> list[PriceEvidence]:
    """在单根 K 上运行 §8.1/§8.2 的全部规则。"""
    baseline = _baseline_at(clean, position)
    if baseline is None:
        return []

    bar = clean.iloc[position]
    signal_at = pd.Timestamp(clean.index[position])
    high = float(bar["High"])
    low = float(bar["Low"])
    close = float(bar["Close"])
    volume = float(bar["Volume"])

    relative_volume = volume / baseline.volume_baseline
    close_position = _close_position(high, low, close)
    bullish_close_floor = baseline.previous_close - LOCATION_TOLERANCE_RATIO * baseline.range_baseline
    bearish_close_ceiling = baseline.previous_close + LOCATION_TOLERANCE_RATIO * baseline.range_baseline

    demand_ids = _in_demand_location(
        low=low, high=high, close=close, zones=zones, pools=liquidity_pools,
        range_baseline=baseline.range_baseline,
    )
    supply_ids = _in_supply_location(
        low=low, high=high, close=close, zones=zones, pools=liquidity_pools,
        range_baseline=baseline.range_baseline,
    )

    shared_inputs = {
        "relative_volume": relative_volume,
        "close_position": close_position,
        "volume_baseline": baseline.volume_baseline,
        "range_baseline": baseline.range_baseline,
        "prior_low": baseline.prior_low,
        "prior_high": baseline.prior_high,
        "previous_close": baseline.previous_close,
        "signal_high": high,
        "signal_low": low,
        "signal_close": close,
    }

    found: list[PriceEvidence] = []

    def _emit(
        kind: str,
        direction: str,
        *,
        dependency_group: str,
        thresholds: Mapping[str, Any],
        location_ids: Sequence[str] = (),
        extra_inputs: Mapping[str, Any] | None = None,
    ) -> None:
        inputs = dict(shared_inputs)
        if extra_inputs:
            inputs.update(extra_inputs)
        found.append(
            PriceEvidence(
                evidence_id=_evidence_id(
                    kind=kind, signal_at=signal_at, inputs=inputs,
                    thresholds=thresholds, location_ids=location_ids,
                ),
                kind=kind,
                direction=direction,
                lifecycle=Lifecycle.OBSERVED.value,
                dependency_group=dependency_group,
                signal_at=signal_at,
                observed_at=signal_at,
                available_at=signal_at,
                expires_at=None,
                signal_high=high,
                signal_low=low,
                inputs=inputs,
                thresholds=dict(thresholds),
                location_ids=tuple(location_ids),
            )
        )

    # --- §8.1 做多迹象 -----------------------------------------------------
    if (
        demand_ids
        and relative_volume >= config.volume_anomaly_threshold
        and close_position >= config.sweep_close_position_threshold
        and close >= bullish_close_floor
    ):
        _emit(
            "bullish_absorption_like", Direction.BULLISH.value,
            dependency_group="price_response",
            thresholds={
                "relative_volume_min": config.volume_anomaly_threshold,
                "close_position_min": config.sweep_close_position_threshold,
                "close_floor": bullish_close_floor,
            },
            location_ids=demand_ids,
        )

    if (
        low < baseline.prior_low
        and close >= baseline.prior_low
        and close_position >= config.sweep_close_position_threshold
    ):
        _emit(
            "bullish_sweep_reclaim", Direction.BULLISH.value,
            dependency_group="price_response",
            thresholds={
                "close_position_min": config.sweep_close_position_threshold,
                "prior_low": baseline.prior_low,
            },
            location_ids=demand_ids,
        )

    declines = _decline_pair(clean, position)
    if (
        declines is not None
        and low <= baseline.prior_low
        and relative_volume <= config.exhaustion_volume_ratio
        and close_position >= 0.50
        and declines[0] > 0
        and declines[1] <= 0.5 * declines[0]
    ):
        _emit(
            "selling_exhaustion_like", Direction.BULLISH.value,
            dependency_group="price_response",
            thresholds={
                "relative_volume_max": config.exhaustion_volume_ratio,
                "close_position_min": 0.50,
                "recent_decline_max_ratio": 0.5,
            },
            location_ids=demand_ids,
            extra_inputs={"prior_decline": declines[0], "recent_decline": declines[1]},
        )

    # --- §8.2 做空迹象（严格镜像） ---------------------------------------
    mirrored_close_position_max = 1.0 - config.sweep_close_position_threshold

    if (
        supply_ids
        and relative_volume >= config.volume_anomaly_threshold
        and close_position <= mirrored_close_position_max
        and close <= bearish_close_ceiling
    ):
        _emit(
            "bearish_absorption_like", Direction.BEARISH.value,
            dependency_group="price_response",
            thresholds={
                "relative_volume_min": config.volume_anomaly_threshold,
                "close_position_max": mirrored_close_position_max,
                "close_ceiling": bearish_close_ceiling,
            },
            location_ids=supply_ids,
        )

    if (
        high > baseline.prior_high
        and close <= baseline.prior_high
        and close_position <= mirrored_close_position_max
    ):
        _emit(
            "bearish_sweep_reclaim", Direction.BEARISH.value,
            dependency_group="price_response",
            thresholds={
                "close_position_max": mirrored_close_position_max,
                "prior_high": baseline.prior_high,
            },
            location_ids=supply_ids,
        )

    if declines is not None:
        closes = clean["Close"].astype(float)
        prior_rally = max(0.0, float(closes.iloc[position - 5]) - float(closes.iloc[position - 10]))
        recent_rally = max(0.0, float(closes.iloc[position]) - float(closes.iloc[position - 5]))
        if (
            high >= baseline.prior_high
            and relative_volume <= config.exhaustion_volume_ratio
            and close_position <= 0.50
            and prior_rally > 0
            and recent_rally <= 0.5 * prior_rally
        ):
            _emit(
                "buying_exhaustion_like", Direction.BEARISH.value,
                dependency_group="price_response",
                thresholds={
                    "relative_volume_max": config.exhaustion_volume_ratio,
                    "close_position_max": 0.50,
                    "recent_rally_max_ratio": 0.5,
                },
                location_ids=supply_ids,
                extra_inputs={"prior_rally": prior_rally, "recent_rally": recent_rally},
            )

    return found


def _resolve_lifecycle(
    clean: pd.DataFrame,
    evidence: PriceEvidence,
    position: int,
) -> PriceEvidence:
    """§8.1/§8.3: 五日内突破信号 K 高点确认；跌破信号 K 低点失效；
    最后两根尚无未来确认的 K 只能是 pending_confirmation。失效优先于过期。"""
    future = clean.iloc[position + 1 : position + 1 + CONFIRMATION_WINDOW]
    if future.empty:
        return _with_lifecycle(evidence, Lifecycle.PENDING.value, available_at=evidence.signal_at)

    bullish = evidence.direction == Direction.BULLISH.value
    closes = future["Close"].astype(float)

    for stamp, close in zip(future.index, closes, strict=False):
        # 失效先判：invalidation before expiry
        invalidated = close < evidence.signal_low if bullish else close > evidence.signal_high
        if invalidated:
            return _with_lifecycle(
                evidence, Lifecycle.EXPIRED.value,
                available_at=pd.Timestamp(stamp), expires_at=pd.Timestamp(stamp),
            )
        confirmed = close > evidence.signal_high if bullish else close < evidence.signal_low
        if confirmed:
            confirmed_at = pd.Timestamp(stamp)
            return _with_lifecycle(
                evidence, Lifecycle.CONFIRMED.value,
                available_at=confirmed_at,
                # 确认后的证据引用 pending 阶段的 ID，保持 lineage 可追溯
                lineage_ids=(evidence.evidence_id,),
            )

    if len(future) < CONFIRMATION_WINDOW:
        return _with_lifecycle(evidence, Lifecycle.PENDING.value, available_at=evidence.signal_at)
    return _with_lifecycle(
        evidence, Lifecycle.EXPIRED.value,
        available_at=pd.Timestamp(future.index[-1]), expires_at=pd.Timestamp(future.index[-1]),
    )


def _with_lifecycle(
    evidence: PriceEvidence,
    lifecycle: str,
    *,
    available_at: pd.Timestamp,
    expires_at: pd.Timestamp | None = None,
    lineage_ids: tuple[str, ...] = (),
) -> PriceEvidence:
    return PriceEvidence(
        evidence_id=evidence.evidence_id,
        kind=evidence.kind,
        direction=evidence.direction,
        lifecycle=lifecycle,
        dependency_group=evidence.dependency_group,
        signal_at=evidence.signal_at,
        observed_at=evidence.observed_at,
        available_at=available_at,
        expires_at=expires_at,
        signal_high=evidence.signal_high,
        signal_low=evidence.signal_low,
        inputs=evidence.inputs,
        thresholds=evidence.thresholds,
        location_ids=evidence.location_ids,
        lineage_ids=evidence.lineage_ids + lineage_ids,
    )


def _markup_evidence(
    clean: pd.DataFrame,
    parent: PriceEvidence,
    position: int,
) -> PriceEvidence | None:
    """§8.1: markup_confirmation —— 五日内 Close>signal_high 且收盘位于当日振幅上部 35%。
    镜像为 markdown_confirmation。"""
    future = clean.iloc[position + 1 : position + 1 + CONFIRMATION_WINDOW]
    if future.empty:
        return None

    bullish = parent.direction == Direction.BULLISH.value
    kind = "markup_confirmation" if bullish else "markdown_confirmation"

    for stamp, row in future.iterrows():
        high = float(row["High"])
        low = float(row["Low"])
        close = float(row["Close"])
        position_in_bar = _close_position(high, low, close)
        broke = close > parent.signal_high if bullish else close < parent.signal_low
        placed = position_in_bar >= 0.65 if bullish else position_in_bar <= 0.35
        if broke and placed:
            stamp = pd.Timestamp(stamp)
            inputs = {
                "breakout_close": close,
                "close_position": position_in_bar,
                "parent_signal_high": parent.signal_high,
                "parent_signal_low": parent.signal_low,
            }
            thresholds = {"close_position_min": 0.65} if bullish else {"close_position_max": 0.35}
            return PriceEvidence(
                evidence_id=_evidence_id(
                    kind=kind, signal_at=stamp, inputs=inputs,
                    thresholds=thresholds, location_ids=parent.location_ids,
                ),
                kind=kind,
                direction=parent.direction,
                lifecycle=Lifecycle.CONFIRMED.value,
                dependency_group="price_response",
                signal_at=stamp,
                observed_at=stamp,
                available_at=stamp,
                expires_at=None,
                signal_high=high,
                signal_low=low,
                inputs=inputs,
                thresholds=thresholds,
                location_ids=parent.location_ids,
                lineage_ids=(parent.evidence_id,),
            )
    return None


def _layer_direction(evidence: Sequence[PriceEvidence]) -> str:
    """§8.3: 多空同时出现输出 conflict，不能默认判空。"""
    directions = {item.direction for item in evidence}
    bullish = Direction.BULLISH.value in directions
    bearish = Direction.BEARISH.value in directions
    if bullish and bearish:
        return Direction.CONFLICT.value
    if bullish:
        return Direction.BULLISH.value
    if bearish:
        return Direction.BEARISH.value
    return Direction.NEUTRAL.value


def _layer_lifecycle(evidence: Sequence[PriceEvidence]) -> str:
    """失效优先于确认，确认优先于待确认。"""
    lifecycles = {item.lifecycle for item in evidence}
    for candidate in (Lifecycle.EXPIRED, Lifecycle.CONFIRMED, Lifecycle.PENDING):
        if candidate.value in lifecycles:
            return candidate.value
    return Lifecycle.OBSERVED.value


def _not_computable(decision_time: pd.Timestamp, limitations: tuple[str, ...]) -> LayerResult:
    """§8.3: 样本或可追溯位置不足时返回 NOT_COMPUTABLE，不写"无明显信号"。"""
    return LayerResult(
        schema_version=SCHEMA_VERSION,
        layer_id="price_action",
        availability="unavailable",
        direction=Direction.UNKNOWN.value,
        lifecycle=Lifecycle.NOT_COMPUTABLE.value,
        quality="INSUFFICIENT",
        as_of=decision_time,
        valid_from=decision_time,
        expires_at=None,
        target_session="",
        evidence=(),
        evidence_ids=(),
        lineage_ids=(),
        limitations=limitations,
    )


def build_price_action_layer(
    daily: pd.DataFrame,
    *,
    zones: Sequence[Mapping[str, Any]],
    liquidity_pools: Sequence[Mapping[str, Any]],
    market_structure: Mapping[str, Any],
    patterns: Sequence[str],
    decision_time: pd.Timestamp,
    config: PriceActionEvidenceConfig,
) -> LayerResult:
    """把日线、可追溯 zone/pool 和市场结构折叠成一个价格行为 LayerResult。"""
    clean = _clean(daily)
    if len(clean) <= BASELINE_WINDOW:
        return _not_computable(decision_time, ("insufficient_history",))

    traceable_zones = _traceable(zones, "zone_id")
    traceable_pools = _traceable(liquidity_pools, "pool_id")
    untraceable = (len(zones) - len(traceable_zones)) + (len(liquidity_pools) - len(traceable_pools))
    if not traceable_zones and not traceable_pools and untraceable:
        return _not_computable(decision_time, ("untraceable_location",))

    collected: list[PriceEvidence] = []
    for position in range(BASELINE_WINDOW, len(clean)):
        for raw in _detect_at(
            clean, position,
            zones=traceable_zones, liquidity_pools=traceable_pools, config=config,
        ):
            resolved = _resolve_lifecycle(clean, raw, position)
            collected.append(resolved)
            if resolved.lifecycle == Lifecycle.CONFIRMED.value:
                markup = _markup_evidence(clean, raw, position)
                if markup is not None:
                    collected.append(markup)

    if not collected:
        limitations: tuple[str, ...] = ()
        if not traceable_zones and not traceable_pools:
            limitations = ("no_traceable_location",)

        # §8.3: 最后两根K线只能标记 pending_confirmation
        last_two_start = clean.index[-2]
        lifecycle_value = (
            Lifecycle.PENDING.value
            if decision_time >= last_two_start
            else Lifecycle.OBSERVED.value
        )

        return LayerResult(
            schema_version=SCHEMA_VERSION,
            layer_id="price_action",
            availability="available",
            direction=Direction.NEUTRAL.value,
            lifecycle=lifecycle_value,
            quality="VALID",
            as_of=decision_time,
            valid_from=decision_time,
            expires_at=None,
            target_session=str(clean.index[-1].date()),
            evidence=(),
            evidence_ids=(),
            lineage_ids=(),
            limitations=limitations,
        )

    lineage: list[str] = []
    for item in collected:
        lineage.extend(item.lineage_ids)

    # 只用近30天的证据做方向判断，避免超老信号污染
    # 保留所有证据用于审计和显示
    thirty_days_ago = decision_time - pd.Timedelta(days=30)
    recent_evidences = [e for e in collected if e.signal_at >= thirty_days_ago]
    
    # 如果没有近期证据，降为 NEUTRAL 但保留所有历史证据
    if not recent_evidences:
        direction_value = Direction.NEUTRAL.value
        lifecycle_value = Lifecycle.EXPIRED.value
        limitations_value = ("all_signals_expired_over_30d",)
    else:
        direction_value = _layer_direction(recent_evidences)
        lifecycle_value = _layer_lifecycle(recent_evidences)
        limitations_value = ()

    return LayerResult(
        schema_version=SCHEMA_VERSION,
        layer_id="price_action",
        availability="available",
        direction=direction_value,
        lifecycle=lifecycle_value,
        quality="VALID",
        as_of=decision_time,
        valid_from=min(item.available_at for item in collected),
        expires_at=None,
        target_session=str(clean.index[-1].date()),
        evidence=tuple(collected),  # 保留所有证据
        evidence_ids=tuple(item.evidence_id for item in collected),
        lineage_ids=tuple(dict.fromkeys(lineage)),
        limitations=limitations_value,
    )


def evidence_to_dict(evidence: PriceEvidence) -> dict[str, Any]:
    """将 PriceEvidence 转换为可序列化的字典"""
    return evidence.to_dict()

__all__ = ["build_price_action_layer", "PriceEvidence"]
