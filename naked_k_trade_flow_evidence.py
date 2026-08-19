"""
naked_k_trade_flow_evidence.py

逐笔成交证据生成器 - 将 TradeFlowSnapshot 转换为智能资金证据

符合 docs/superpowers/specs/2026-08-17-smart-money-dual-evidence-design.md §7
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from naked_k_flow_eastmoney import TradeFlowSnapshot, TradePrint


SCHEMA_VERSION = "evidence.v1"


@dataclass(frozen=True)
class TradeFlowEvidence:
    """逐笔成交证据"""
    evidence_id: str
    schema_version: str
    family: str  # trade_tape
    kind: str  # large_uptick_print_concentration 等
    direction: str  # bullish|bearish|neutral
    observed_at: datetime
    available_at: datetime
    expires_at: datetime | None
    target_session: str  # ISO date
    lifecycle: str  # observed|pending_confirmation|confirmed|invalidated|expired
    quality: str  # VALID|BOOTSTRAP|PARTIAL|STALE|UNAVAILABLE
    availability: str  # available|partial|stale|unavailable

    # 输入和依赖
    lineage_ids: tuple[str, ...]  # 输入快照ID
    dependency_group: str  # trade_tape

    # 统计和阈值
    inputs: dict[str, Any]  # 原始统计值
    thresholds: dict[str, Any]  # 触发阈值
    limitations: tuple[str, ...]  # 限制说明

    # 确认和失效
    confirmation: dict[str, Any] | None
    invalidation: dict[str, Any] | None

    # 可交易性
    tradable_at: datetime | None
    validation_status: str  # UNVALIDATED


def _compute_evidence_id(
    kind: str,
    target_session: str,
    ticker: str,
    observed_at: datetime,
) -> str:
    """生成证据ID"""
    content = f"{kind}:{target_session}:{ticker}:{observed_at.isoformat()}"
    hash_digest = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"evidence-{kind}-{hash_digest}"


def _compute_large_thresholds(
    historical_snapshots: list[TradeFlowSnapshot],
    session_phase: str = "continuous",
) -> dict[str, float | None]:
    """
    计算大额/超大额成交阈值

    使用过去 20 个完整交易日的 99%/99.9% 分位数
    """
    if len(historical_snapshots) < 20:
        return {
            "large_threshold": None,
            "extra_large_threshold": None,
            "method": "INSUFFICIENT_HISTORY",
        }

    # 收集所有符合条件的单笔成交金额
    notionals: list[float] = []
    for snapshot in historical_snapshots:
        if snapshot.status != "OK" or not snapshot.session_complete:
            continue

        for trade in snapshot.trades:
            if trade.session_phase == session_phase:
                notionals.append(trade.notional)

    if len(notionals) < 1000:
        return {
            "large_threshold": None,
            "extra_large_threshold": None,
            "method": "INSUFFICIENT_SAMPLE",
        }

    # 计算分位数（nearest-rank）
    notionals_sorted = sorted(notionals)
    n = len(notionals_sorted)

    large_idx = int(0.99 * n)
    extra_large_idx = int(0.999 * n)

    large_threshold = notionals_sorted[min(large_idx, n - 1)]
    extra_large_threshold = notionals_sorted[min(extra_large_idx, n - 1)]

    return {
        "large_threshold": large_threshold,
        "extra_large_threshold": extra_large_threshold,
        "method": "HISTORICAL_PERCENTILE",
        "sample_size": n,
        "window_days": len(historical_snapshots),
    }


def _compute_bootstrap_thresholds(
    snapshot: TradeFlowSnapshot,
    session_phase: str = "continuous",
) -> dict[str, float | None]:
    """
    Bootstrap 阈值：使用当日分布

    仅在连续交易阶段至少 1000 条记录时可用
    """
    continuous_trades = [
        t for t in snapshot.trades
        if t.session_phase == session_phase
    ]

    if len(continuous_trades) < 1000:
        return {
            "large_threshold": None,
            "extra_large_threshold": None,
            "method": "NOT_COMPUTABLE",
        }

    notionals = [t.notional for t in continuous_trades]
    notionals_sorted = sorted(notionals)
    n = len(notionals_sorted)

    large_idx = int(0.99 * n)
    extra_large_idx = int(0.999 * n)

    return {
        "large_threshold": notionals_sorted[min(large_idx, n - 1)],
        "extra_large_threshold": notionals_sorted[min(extra_large_idx, n - 1)],
        "method": "BOOTSTRAP",
        "sample_size": n,
    }


def generate_trade_flow_evidence(
    snapshot: TradeFlowSnapshot,
    historical_snapshots: list[TradeFlowSnapshot] | None = None,
) -> list[TradeFlowEvidence]:
    """
    从逐笔成交快照生成证据

    Args:
        snapshot: 当日快照
        historical_snapshots: 过去 20 个完整交易日快照（可选，用于计算阈值）

    Returns:
        证据列表
    """
    if snapshot.status != "OK":
        # 数据不可用，返回空
        return []

    # 确定阈值方法
    if historical_snapshots and len(historical_snapshots) >= 20:
        thresholds = _compute_large_thresholds(historical_snapshots)
        quality = "VALID"
    else:
        thresholds = _compute_bootstrap_thresholds(snapshot)
        quality = "BOOTSTRAP" if thresholds["method"] == "BOOTSTRAP" else "PARTIAL"

    if thresholds["large_threshold"] is None:
        # 无法计算阈值
        return []

    # 统计连续交易阶段的成交
    continuous_trades = [
        t for t in snapshot.trades
        if t.session_phase == "continuous"
    ]

    if not continuous_trades:
        return []

    # 计算统计量
    total_notional = sum(t.notional for t in continuous_trades)

    # 大额成交统计
    large_uptick = sum(
        t.notional for t in continuous_trades
        if t.notional >= thresholds["large_threshold"]
        and t.tick_direction == "uptick"
    )
    large_downtick = sum(
        t.notional for t in continuous_trades
        if t.notional >= thresholds["large_threshold"]
        and t.tick_direction == "downtick"
    )
    large_total = large_uptick + large_downtick

    # 超大额成交统计
    extra_large_uptick_count = sum(
        1 for t in continuous_trades
        if t.notional >= thresholds["extra_large_threshold"]
        and t.tick_direction == "uptick"
    )
    extra_large_downtick_count = sum(
        1 for t in continuous_trades
        if t.notional >= thresholds["extra_large_threshold"]
        and t.tick_direction == "downtick"
    )

    # Tick direction 覆盖率
    known_direction_notional = sum(
        t.notional for t in continuous_trades
        if t.tick_direction in ("uptick", "downtick")
    )
    coverage = known_direction_notional / total_notional if total_notional > 0 else 0

    # 计算比率
    large_share = large_total / total_notional if total_notional > 0 else 0
    large_imbalance = (
        (large_uptick - large_downtick) / large_total
        if large_total > 0 else None
    )
    extra_imbalance = (
        (extra_large_uptick_count - extra_large_downtick_count)
        / (extra_large_uptick_count + extra_large_downtick_count)
        if (extra_large_uptick_count + extra_large_downtick_count) > 0 else None
    )

    # 生成证据
    evidences: list[TradeFlowEvidence] = []
    observed_at = snapshot.retrieved_at
    available_at = snapshot.coverage_end or observed_at  # 完整收盘后可用

    inputs = {
        "total_notional": total_notional,
        "trade_count": len(continuous_trades),
        "large_share": large_share,
        "large_imbalance": large_imbalance,
        "extra_imbalance": extra_imbalance,
        "coverage": coverage,
        "large_uptick": large_uptick,
        "large_downtick": large_downtick,
        "extra_large_uptick_count": extra_large_uptick_count,
        "extra_large_downtick_count": extra_large_downtick_count,
    }

    # 检查最小覆盖要求
    meets_minimum_coverage = (
        len(continuous_trades) >= 1000
        and coverage >= 0.9
    )

    limitations = []
    if not snapshot.session_complete:
        limitations.append("session_incomplete")
    if quality == "BOOTSTRAP":
        limitations.append("bootstrap_thresholds")
    if coverage < 0.9:
        limitations.append(f"low_coverage:{coverage:.2%}")

    # 证据1: large_uptick_print_concentration
    if (
        meets_minimum_coverage
        and large_share >= 0.10
        and large_imbalance is not None
        and large_imbalance >= 0.20
    ):
        evidences.append(TradeFlowEvidence(
            evidence_id=_compute_evidence_id(
                "large_uptick_print_concentration",
                snapshot.session_date,
                snapshot.ticker,
                observed_at,
            ),
            schema_version=SCHEMA_VERSION,
            family="trade_tape",
            kind="large_uptick_print_concentration",
            direction="bullish",
            observed_at=observed_at,
            available_at=available_at,
            expires_at=None,  # TODO: 三个交易日后过期
            target_session=snapshot.session_date,
            lifecycle="confirmed" if snapshot.session_complete else "pending_confirmation",
            quality=quality,
            availability="available",
            lineage_ids=(snapshot.normalized_snapshot_id,),
            dependency_group="trade_tape",
            inputs=inputs,
            thresholds={
                **thresholds,
                "large_share_min": 0.10,
                "large_imbalance_min": 0.20,
                "min_trade_count": 1000,
                "min_coverage": 0.90,
                "provisional": True,
            },
            limitations=tuple(limitations),
            confirmation=None,
            invalidation=None,
            tradable_at=available_at,
            validation_status="UNVALIDATED",
        ))

    # 证据2: large_downtick_print_concentration
    if (
        meets_minimum_coverage
        and large_share >= 0.10
        and large_imbalance is not None
        and large_imbalance <= -0.20
    ):
        evidences.append(TradeFlowEvidence(
            evidence_id=_compute_evidence_id(
                "large_downtick_print_concentration",
                snapshot.session_date,
                snapshot.ticker,
                observed_at,
            ),
            schema_version=SCHEMA_VERSION,
            family="trade_tape",
            kind="large_downtick_print_concentration",
            direction="bearish",
            observed_at=observed_at,
            available_at=available_at,
            expires_at=None,
            target_session=snapshot.session_date,
            lifecycle="confirmed" if snapshot.session_complete else "pending_confirmation",
            quality=quality,
            availability="available",
            lineage_ids=(snapshot.normalized_snapshot_id,),
            dependency_group="trade_tape",
            inputs=inputs,
            thresholds={
                **thresholds,
                "large_share_min": 0.10,
                "large_imbalance_max": -0.20,
                "min_trade_count": 1000,
                "min_coverage": 0.90,
                "provisional": True,
            },
            limitations=tuple(limitations),
            confirmation=None,
            invalidation=None,
            tradable_at=available_at,
            validation_status="UNVALIDATED",
        ))

    # 证据3: extra_large_uptick_cluster
    if (
        coverage >= 0.9
        and extra_large_uptick_count >= 3
        and extra_imbalance is not None
        and extra_imbalance >= 0.30
    ):
        evidences.append(TradeFlowEvidence(
            evidence_id=_compute_evidence_id(
                "extra_large_uptick_cluster",
                snapshot.session_date,
                snapshot.ticker,
                observed_at,
            ),
            schema_version=SCHEMA_VERSION,
            family="trade_tape",
            kind="extra_large_uptick_cluster",
            direction="bullish",
            observed_at=observed_at,
            available_at=available_at,
            expires_at=None,
            target_session=snapshot.session_date,
            lifecycle="confirmed" if snapshot.session_complete else "pending_confirmation",
            quality=quality,
            availability="available",
            lineage_ids=(snapshot.normalized_snapshot_id,),
            dependency_group="trade_tape",
            inputs=inputs,
            thresholds={
                **thresholds,
                "min_extra_large_prints": 3,
                "extra_imbalance_min": 0.30,
                "min_coverage": 0.90,
                "provisional": True,
            },
            limitations=tuple(limitations),
            confirmation=None,
            invalidation=None,
            tradable_at=available_at,
            validation_status="UNVALIDATED",
        ))

    # 证据4: extra_large_downtick_cluster
    if (
        coverage >= 0.9
        and extra_large_downtick_count >= 3
        and extra_imbalance is not None
        and extra_imbalance <= -0.30
    ):
        evidences.append(TradeFlowEvidence(
            evidence_id=_compute_evidence_id(
                "extra_large_downtick_cluster",
                snapshot.session_date,
                snapshot.ticker,
                observed_at,
            ),
            schema_version=SCHEMA_VERSION,
            family="trade_tape",
            kind="extra_large_downtick_cluster",
            direction="bearish",
            observed_at=observed_at,
            available_at=available_at,
            expires_at=None,
            target_session=snapshot.session_date,
            lifecycle="confirmed" if snapshot.session_complete else "pending_confirmation",
            quality=quality,
            availability="available",
            lineage_ids=(snapshot.normalized_snapshot_id,),
            dependency_group="trade_tape",
            inputs=inputs,
            thresholds={
                **thresholds,
                "min_extra_large_prints": 3,
                "extra_imbalance_max": -0.30,
                "min_coverage": 0.90,
                "provisional": True,
            },
            limitations=tuple(limitations),
            confirmation=None,
            invalidation=None,
            tradable_at=available_at,
            validation_status="UNVALIDATED",
        ))

    return evidences
