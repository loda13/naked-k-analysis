"""
naked_k_smart_money_fusion.py

双证据融合层 - 将价格行为证据与成交证据融合

符合 docs/superpowers/specs/2026-08-17-smart-money-dual-evidence-design.md §9
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class ParticipationState(Enum):
    """单层参与状态"""
    FORMAL_BULLISH = "formal_bullish"
    FORMAL_BEARISH = "formal_bearish"
    FORMAL_NEUTRAL = "formal_neutral"
    FORMAL_CONFLICT = "formal_conflict"
    PROVISIONAL = "provisional"
    UNKNOWN = "unknown"
    INACTIVE = "inactive"


class FusionResult(Enum):
    """融合结果"""
    ALIGNED_BULLISH = "aligned_bullish"
    ALIGNED_BEARISH = "aligned_bearish"
    CONFLICT = "conflict"
    FLOW_ONLY = "flow_only"
    PRICE_ACTION_ONLY = "price_action_only"
    NEUTRAL = "neutral"
    PROVISIONAL = "provisional"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class LayerResult:
    """单层证据汇总结果"""
    layer: str  # trade_flow | price_action
    state: ParticipationState
    direction: str | None  # bullish|bearish|neutral|conflict
    evidences: tuple[Any, ...]  # 触发的证据列表
    quality: str  # VALID|BOOTSTRAP|PARTIAL|STALE|UNAVAILABLE
    limitations: tuple[str, ...]
    decision_time: datetime
    target_session: str  # ISO date
    valid_from: datetime | None
    valid_until: datetime | None


@dataclass(frozen=True)
class DualEvidenceFusion:
    """双证据融合结果"""
    result: FusionResult
    direction: str | None  # bullish|bearish|neutral|conflict|None
    trade_flow_layer: LayerResult | None
    price_action_layer: LayerResult | None
    quality: str  # VALID|BOOTSTRAP|PARTIAL|PROVISIONAL
    limitations: tuple[str, ...]
    aligned: bool  # 是否跨层对齐
    confidence: str  # high|medium|low
    advisory_only: bool  # 是否仅供参考
    explanation: str
    confirmation_criteria: str | None
    invalidation_criteria: str | None


def _compute_layer_state(
    evidences: list[Any],
    quality: str,
    limitations: tuple[str, ...],
) -> tuple[ParticipationState, str | None]:
    """
    计算单层参与状态

    Args:
        evidences: 该层检测到的证据列表
        quality: 数据质量
        limitations: 限制说明

    Returns:
        (ParticipationState, direction)
    """
    if not evidences:
        if quality in ("STALE", "UNAVAILABLE"):
            return ParticipationState.INACTIVE, None
        return ParticipationState.FORMAL_NEUTRAL, "neutral"

    # 检查是否有 provisional 标记
    has_provisional = any(
        getattr(e, "thresholds", {}).get("provisional", False)
        or getattr(e, "lifecycle", "") == "pending_confirmation"
        or "bootstrap" in limitations
        for e in evidences
    )

    if has_provisional:
        # 计算方向
        bullish_count = sum(1 for e in evidences if getattr(e, "direction", "") == "bullish")
        bearish_count = sum(1 for e in evidences if getattr(e, "direction", "") == "bearish")

        if bullish_count > 0 and bearish_count > 0:
            return ParticipationState.PROVISIONAL, "conflict"
        elif bullish_count > 0:
            return ParticipationState.PROVISIONAL, "bullish"
        elif bearish_count > 0:
            return ParticipationState.PROVISIONAL, "bearish"
        else:
            return ParticipationState.PROVISIONAL, "neutral"

    # 统计多空方向
    bullish_count = sum(1 for e in evidences if getattr(e, "direction", "") == "bullish")
    bearish_count = sum(1 for e in evidences if getattr(e, "direction", "") == "bearish")

    if bullish_count > 0 and bearish_count > 0:
        return ParticipationState.FORMAL_CONFLICT, "conflict"
    elif bullish_count > 0:
        return ParticipationState.FORMAL_BULLISH, "bullish"
    elif bearish_count > 0:
        return ParticipationState.FORMAL_BEARISH, "bearish"
    else:
        return ParticipationState.FORMAL_NEUTRAL, "neutral"


def _check_time_alignment(
    layer1: LayerResult | None,
    layer2: LayerResult | None,
    max_session_gap_days: int = 3,
) -> bool:
    """
    检查两层证据的时间是否对齐

    要求：
    1. 有效区间在 decision_time 重叠
    2. target_session 相差不超过 max_session_gap_days
    """
    if not layer1 or not layer2:
        return False

    # 检查 target_session 差距
    try:
        date1 = datetime.fromisoformat(layer1.target_session)
        date2 = datetime.fromisoformat(layer2.target_session)
        session_gap = abs((date1 - date2).days)
        if session_gap > max_session_gap_days:
            return False
    except (ValueError, TypeError):
        return False

    # 检查有效期重叠
    if layer1.valid_from and layer1.valid_until and layer2.valid_from and layer2.valid_until:
        # 两个区间重叠
        overlap = (
            layer1.valid_from <= layer2.valid_until
            and layer2.valid_from <= layer1.valid_until
        )
        return overlap

    # 有效期信息不完整，保守认为不对齐
    return False


def fuse_dual_evidence(
    trade_flow_layer: LayerResult | None,
    price_action_layer: LayerResult | None,
) -> DualEvidenceFusion:
    """
    融合双层证据

    优先级：
    1. 任一层为 FORMAL_CONFLICT → conflict
    2. 任一层为 PROVISIONAL → provisional（保留方向）
    3. 其他按融合矩阵映射

    Args:
        trade_flow_layer: 成交证据层结果
        price_action_layer: 价格行为证据层结果

    Returns:
        融合结果
    """
    limitations: list[str] = []

    # 收集 limitations
    if trade_flow_layer:
        limitations.extend(trade_flow_layer.limitations)
    if price_action_layer:
        limitations.extend(price_action_layer.limitations)

    # 优先级 1: FORMAL_CONFLICT
    if trade_flow_layer and trade_flow_layer.state == ParticipationState.FORMAL_CONFLICT:
        return DualEvidenceFusion(
            result=FusionResult.CONFLICT,
            direction="conflict",
            trade_flow_layer=trade_flow_layer,
            price_action_layer=price_action_layer,
            quality="VALID",
            limitations=tuple(limitations),
            aligned=False,
            confidence="low",
            advisory_only=True,
            explanation="成交证据层内部出现多空冲突",
            confirmation_criteria=None,
            invalidation_criteria=None,
        )

    if price_action_layer and price_action_layer.state == ParticipationState.FORMAL_CONFLICT:
        return DualEvidenceFusion(
            result=FusionResult.CONFLICT,
            direction="conflict",
            trade_flow_layer=trade_flow_layer,
            price_action_layer=price_action_layer,
            quality="VALID",
            limitations=tuple(limitations),
            aligned=False,
            confidence="low",
            advisory_only=True,
            explanation="价格行为证据层内部出现多空冲突",
            confirmation_criteria=None,
            invalidation_criteria=None,
        )

    # 优先级 2: PROVISIONAL
    if (trade_flow_layer and trade_flow_layer.state == ParticipationState.PROVISIONAL) or \
       (price_action_layer and price_action_layer.state == ParticipationState.PROVISIONAL):

        # 保留方向
        direction = None
        if trade_flow_layer and trade_flow_layer.state == ParticipationState.PROVISIONAL:
            direction = trade_flow_layer.direction
        elif price_action_layer and price_action_layer.state == ParticipationState.PROVISIONAL:
            direction = price_action_layer.direction

        return DualEvidenceFusion(
            result=FusionResult.PROVISIONAL,
            direction=direction,
            trade_flow_layer=trade_flow_layer,
            price_action_layer=price_action_layer,
            quality="PROVISIONAL",
            limitations=tuple(limitations),
            aligned=False,
            confidence="low",
            advisory_only=True,
            explanation="证据处于 pending_confirmation 或使用 bootstrap 阈值",
            confirmation_criteria=None,
            invalidation_criteria=None,
        )

    # 优先级 3: 融合矩阵
    tf_state = trade_flow_layer.state if trade_flow_layer else ParticipationState.UNKNOWN
    pa_state = price_action_layer.state if price_action_layer else ParticipationState.UNKNOWN

    # 检查时间对齐
    time_aligned = _check_time_alignment(trade_flow_layer, price_action_layer)

    # 融合矩阵
    if tf_state == ParticipationState.FORMAL_BULLISH:
        if pa_state == ParticipationState.FORMAL_BULLISH:
            if not time_aligned:
                limitations.append("time_misaligned")
                return DualEvidenceFusion(
                    result=FusionResult.PROVISIONAL,
                    direction="bullish",
                    trade_flow_layer=trade_flow_layer,
                    price_action_layer=price_action_layer,
                    quality="PROVISIONAL",
                    limitations=tuple(limitations),
                    aligned=False,
                    confidence="medium",
                    advisory_only=True,
                    explanation="大额成交与价格响应方向一致，但时间未对齐",
                    confirmation_criteria=None,
                    invalidation_criteria=None,
                )
            return DualEvidenceFusion(
                result=FusionResult.ALIGNED_BULLISH,
                direction="bullish",
                trade_flow_layer=trade_flow_layer,
                price_action_layer=price_action_layer,
                quality="VALID",
                limitations=tuple(limitations),
                aligned=True,
                confidence="high",
                advisory_only=True,
                explanation="大额成交代理与K线响应同时符合专业资金进场迹象",
                confirmation_criteria="突破信号K高点",
                invalidation_criteria="跌破信号K低点",
            )
        elif pa_state == ParticipationState.FORMAL_BEARISH:
            return DualEvidenceFusion(
                result=FusionResult.CONFLICT,
                direction="conflict",
                trade_flow_layer=trade_flow_layer,
                price_action_layer=price_action_layer,
                quality="VALID",
                limitations=tuple(limitations),
                aligned=False,
                confidence="low",
                advisory_only=True,
                explanation="成交显示看涨，价格行为显示看跌",
                confirmation_criteria=None,
                invalidation_criteria=None,
            )
        else:  # FORMAL_NEUTRAL, UNKNOWN, INACTIVE
            return DualEvidenceFusion(
                result=FusionResult.FLOW_ONLY,
                direction="bullish",
                trade_flow_layer=trade_flow_layer,
                price_action_layer=price_action_layer,
                quality=trade_flow_layer.quality if trade_flow_layer else "UNAVAILABLE",
                limitations=tuple(limitations),
                aligned=False,
                confidence="medium",
                advisory_only=True,
                explanation="仅成交层显示看涨迹象",
                confirmation_criteria=None,
                invalidation_criteria=None,
            )

    elif tf_state == ParticipationState.FORMAL_BEARISH:
        if pa_state == ParticipationState.FORMAL_BULLISH:
            return DualEvidenceFusion(
                result=FusionResult.CONFLICT,
                direction="conflict",
                trade_flow_layer=trade_flow_layer,
                price_action_layer=price_action_layer,
                quality="VALID",
                limitations=tuple(limitations),
                aligned=False,
                confidence="low",
                advisory_only=True,
                explanation="成交显示看跌，价格行为显示看涨",
                confirmation_criteria=None,
                invalidation_criteria=None,
            )
        elif pa_state == ParticipationState.FORMAL_BEARISH:
            if not time_aligned:
                limitations.append("time_misaligned")
                return DualEvidenceFusion(
                    result=FusionResult.PROVISIONAL,
                    direction="bearish",
                    trade_flow_layer=trade_flow_layer,
                    price_action_layer=price_action_layer,
                    quality="PROVISIONAL",
                    limitations=tuple(limitations),
                    aligned=False,
                    confidence="medium",
                    advisory_only=True,
                    explanation="大额成交与价格响应方向一致，但时间未对齐",
                    confirmation_criteria=None,
                    invalidation_criteria=None,
                )
            return DualEvidenceFusion(
                result=FusionResult.ALIGNED_BEARISH,
                direction="bearish",
                trade_flow_layer=trade_flow_layer,
                price_action_layer=price_action_layer,
                quality="VALID",
                limitations=tuple(limitations),
                aligned=True,
                confidence="high",
                advisory_only=True,
                explanation="大额成交代理与K线响应同时符合专业资金离场迹象",
                confirmation_criteria="跌破信号K低点",
                invalidation_criteria="突破信号K高点",
            )
        else:  # FORMAL_NEUTRAL, UNKNOWN, INACTIVE
            return DualEvidenceFusion(
                result=FusionResult.FLOW_ONLY,
                direction="bearish",
                trade_flow_layer=trade_flow_layer,
                price_action_layer=price_action_layer,
                quality=trade_flow_layer.quality if trade_flow_layer else "UNAVAILABLE",
                limitations=tuple(limitations),
                aligned=False,
                confidence="medium",
                advisory_only=True,
                explanation="仅成交层显示看跌迹象",
                confirmation_criteria=None,
                invalidation_criteria=None,
            )

    elif tf_state == ParticipationState.FORMAL_NEUTRAL:
        if pa_state in (ParticipationState.FORMAL_BULLISH, ParticipationState.FORMAL_BEARISH):
            return DualEvidenceFusion(
                result=FusionResult.PRICE_ACTION_ONLY,
                direction=price_action_layer.direction if price_action_layer else None,
                trade_flow_layer=trade_flow_layer,
                price_action_layer=price_action_layer,
                quality=price_action_layer.quality if price_action_layer else "UNAVAILABLE",
                limitations=tuple(limitations),
                aligned=False,
                confidence="medium",
                advisory_only=True,
                explanation="仅价格行为层显示方向性迹象",
                confirmation_criteria=None,
                invalidation_criteria=None,
            )
        elif pa_state == ParticipationState.FORMAL_NEUTRAL:
            return DualEvidenceFusion(
                result=FusionResult.NEUTRAL,
                direction="neutral",
                trade_flow_layer=trade_flow_layer,
                price_action_layer=price_action_layer,
                quality="VALID",
                limitations=tuple(limitations),
                aligned=True,
                confidence="low",
                advisory_only=True,
                explanation="两层均无明确方向性迹象",
                confirmation_criteria=None,
                invalidation_criteria=None,
            )
        else:  # UNKNOWN, INACTIVE
            return DualEvidenceFusion(
                result=FusionResult.UNAVAILABLE,
                direction=None,
                trade_flow_layer=trade_flow_layer,
                price_action_layer=price_action_layer,
                quality="UNAVAILABLE",
                limitations=tuple(limitations),
                aligned=False,
                confidence="low",
                advisory_only=True,
                explanation="数据不可用",
                confirmation_criteria=None,
                invalidation_criteria=None,
            )

    else:  # tf_state == UNKNOWN or INACTIVE
        if pa_state in (ParticipationState.FORMAL_BULLISH, ParticipationState.FORMAL_BEARISH):
            return DualEvidenceFusion(
                result=FusionResult.PRICE_ACTION_ONLY,
                direction=price_action_layer.direction if price_action_layer else None,
                trade_flow_layer=trade_flow_layer,
                price_action_layer=price_action_layer,
                quality=price_action_layer.quality if price_action_layer else "UNAVAILABLE",
                limitations=tuple(limitations),
                aligned=False,
                confidence="medium",
                advisory_only=True,
                explanation="仅价格行为层显示方向性迹象",
                confirmation_criteria=None,
                invalidation_criteria=None,
            )
        else:
            return DualEvidenceFusion(
                result=FusionResult.UNAVAILABLE,
                direction=None,
                trade_flow_layer=trade_flow_layer,
                price_action_layer=price_action_layer,
                quality="UNAVAILABLE",
                limitations=tuple(limitations),
                aligned=False,
                confidence="low",
                advisory_only=True,
                explanation="数据不可用",
                confirmation_criteria=None,
                invalidation_criteria=None,
            )
