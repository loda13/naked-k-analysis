"""
tests/test_naked_k_smart_money_fusion.py

双证据融合层测试
"""

import unittest
from datetime import datetime, timezone, timedelta

from naked_k_smart_money_fusion import (
    LayerResult,
    ParticipationState,
    FusionResult,
    fuse_dual_evidence,
    _compute_layer_state,
    _check_time_alignment,
)


class TestLayerStateComputation(unittest.TestCase):
    """测试单层状态计算"""

    def test_no_evidence_returns_formal_neutral(self):
        """无证据时返回 FORMAL_NEUTRAL"""
        state, direction = _compute_layer_state([], "VALID", ())
        self.assertEqual(state, ParticipationState.FORMAL_NEUTRAL)
        self.assertEqual(direction, "neutral")

    def test_provisional_when_pending_confirmation(self):
        """pending_confirmation 时返回 PROVISIONAL"""

        class MockEvidence:
            direction = "bullish"
            lifecycle = "pending_confirmation"
            thresholds = {}

        evidences = [MockEvidence()]
        state, direction = _compute_layer_state(evidences, "VALID", ())
        self.assertEqual(state, ParticipationState.PROVISIONAL)
        self.assertEqual(direction, "bullish")

    def test_formal_bullish_when_confirmed(self):
        """confirmed 且无 provisional 标记时返回 FORMAL_BULLISH"""

        class MockEvidence:
            direction = "bullish"
            lifecycle = "confirmed"
            thresholds = {"provisional": False}

        evidences = [MockEvidence()]
        state, direction = _compute_layer_state(evidences, "VALID", ())
        self.assertEqual(state, ParticipationState.FORMAL_BULLISH)
        self.assertEqual(direction, "bullish")

    def test_conflict_when_both_directions(self):
        """多空证据同时存在时返回 CONFLICT"""

        class MockEvidenceBullish:
            direction = "bullish"
            lifecycle = "confirmed"
            thresholds = {}

        class MockEvidenceBearish:
            direction = "bearish"
            lifecycle = "confirmed"
            thresholds = {}

        evidences = [MockEvidenceBullish(), MockEvidenceBearish()]
        state, direction = _compute_layer_state(evidences, "VALID", ())
        self.assertEqual(state, ParticipationState.FORMAL_CONFLICT)
        self.assertEqual(direction, "conflict")


class TestTimeAlignment(unittest.TestCase):
    """测试时间对齐检查"""

    def test_aligned_when_overlapping(self):
        """有效期重叠时对齐"""
        now = datetime.now(timezone.utc)

        layer1 = LayerResult(
            layer="trade_flow",
            state=ParticipationState.FORMAL_BULLISH,
            direction="bullish",
            evidences=(),
            quality="VALID",
            limitations=(),
            decision_time=now,
            target_session="2026-08-19",
            valid_from=now,
            valid_until=now + timedelta(days=3),
        )

        layer2 = LayerResult(
            layer="price_action",
            state=ParticipationState.FORMAL_BULLISH,
            direction="bullish",
            evidences=(),
            quality="VALID",
            limitations=(),
            decision_time=now,
            target_session="2026-08-19",
            valid_from=now + timedelta(days=1),
            valid_until=now + timedelta(days=5),
        )

        self.assertTrue(_check_time_alignment(layer1, layer2))

    def test_misaligned_when_session_gap_too_large(self):
        """会话日期相差太远时不对齐"""
        now = datetime.now(timezone.utc)

        layer1 = LayerResult(
            layer="trade_flow",
            state=ParticipationState.FORMAL_BULLISH,
            direction="bullish",
            evidences=(),
            quality="VALID",
            limitations=(),
            decision_time=now,
            target_session="2026-08-19",
            valid_from=now,
            valid_until=now + timedelta(days=3),
        )

        layer2 = LayerResult(
            layer="price_action",
            state=ParticipationState.FORMAL_BULLISH,
            direction="bullish",
            evidences=(),
            quality="VALID",
            limitations=(),
            decision_time=now,
            target_session="2026-08-30",  # 11天后
            valid_from=now + timedelta(days=1),
            valid_until=now + timedelta(days=5),
        )

        self.assertFalse(_check_time_alignment(layer1, layer2))


class TestDualEvidenceFusion(unittest.TestCase):
    """测试双证据融合"""

    def test_aligned_bullish_when_both_formal_bullish(self):
        """两层都是 FORMAL_BULLISH 且时间对齐时返回 ALIGNED_BULLISH"""
        now = datetime.now(timezone.utc)

        tf_layer = LayerResult(
            layer="trade_flow",
            state=ParticipationState.FORMAL_BULLISH,
            direction="bullish",
            evidences=(),
            quality="VALID",
            limitations=(),
            decision_time=now,
            target_session="2026-08-19",
            valid_from=now,
            valid_until=now + timedelta(days=3),
        )

        pa_layer = LayerResult(
            layer="price_action",
            state=ParticipationState.FORMAL_BULLISH,
            direction="bullish",
            evidences=(),
            quality="VALID",
            limitations=(),
            decision_time=now,
            target_session="2026-08-19",
            valid_from=now,
            valid_until=now + timedelta(days=10),
        )

        fusion = fuse_dual_evidence(tf_layer, pa_layer)

        self.assertEqual(fusion.result, FusionResult.ALIGNED_BULLISH)
        self.assertEqual(fusion.direction, "bullish")
        self.assertTrue(fusion.aligned)
        self.assertEqual(fusion.confidence, "high")
        self.assertTrue(fusion.advisory_only)

    def test_conflict_when_opposite_directions(self):
        """两层方向相反时返回 CONFLICT"""
        now = datetime.now(timezone.utc)

        tf_layer = LayerResult(
            layer="trade_flow",
            state=ParticipationState.FORMAL_BULLISH,
            direction="bullish",
            evidences=(),
            quality="VALID",
            limitations=(),
            decision_time=now,
            target_session="2026-08-19",
            valid_from=now,
            valid_until=now + timedelta(days=3),
        )

        pa_layer = LayerResult(
            layer="price_action",
            state=ParticipationState.FORMAL_BEARISH,
            direction="bearish",
            evidences=(),
            quality="VALID",
            limitations=(),
            decision_time=now,
            target_session="2026-08-19",
            valid_from=now,
            valid_until=now + timedelta(days=10),
        )

        fusion = fuse_dual_evidence(tf_layer, pa_layer)

        self.assertEqual(fusion.result, FusionResult.CONFLICT)
        self.assertEqual(fusion.direction, "conflict")
        self.assertFalse(fusion.aligned)

    def test_provisional_when_time_misaligned(self):
        """时间未对齐时降级为 PROVISIONAL"""
        now = datetime.now(timezone.utc)

        tf_layer = LayerResult(
            layer="trade_flow",
            state=ParticipationState.FORMAL_BULLISH,
            direction="bullish",
            evidences=(),
            quality="VALID",
            limitations=(),
            decision_time=now,
            target_session="2026-08-19",
            valid_from=now,
            valid_until=now + timedelta(days=1),  # 短有效期
        )

        pa_layer = LayerResult(
            layer="price_action",
            state=ParticipationState.FORMAL_BULLISH,
            direction="bullish",
            evidences=(),
            quality="VALID",
            limitations=(),
            decision_time=now,
            target_session="2026-08-19",
            valid_from=now + timedelta(days=5),  # 晚很多
            valid_until=now + timedelta(days=10),
        )

        fusion = fuse_dual_evidence(tf_layer, pa_layer)

        self.assertEqual(fusion.result, FusionResult.PROVISIONAL)
        self.assertIn("time_misaligned", fusion.limitations)

    def test_flow_only_when_price_action_neutral(self):
        """仅成交层有信号时返回 FLOW_ONLY"""
        now = datetime.now(timezone.utc)

        tf_layer = LayerResult(
            layer="trade_flow",
            state=ParticipationState.FORMAL_BULLISH,
            direction="bullish",
            evidences=(),
            quality="VALID",
            limitations=(),
            decision_time=now,
            target_session="2026-08-19",
            valid_from=now,
            valid_until=now + timedelta(days=3),
        )

        pa_layer = LayerResult(
            layer="price_action",
            state=ParticipationState.FORMAL_NEUTRAL,
            direction="neutral",
            evidences=(),
            quality="VALID",
            limitations=(),
            decision_time=now,
            target_session="2026-08-19",
            valid_from=now,
            valid_until=now + timedelta(days=10),
        )

        fusion = fuse_dual_evidence(tf_layer, pa_layer)

        self.assertEqual(fusion.result, FusionResult.FLOW_ONLY)
        self.assertEqual(fusion.direction, "bullish")
        self.assertEqual(fusion.confidence, "medium")

    def test_price_action_only_when_trade_flow_unavailable(self):
        """仅价格行为层有信号时返回 PRICE_ACTION_ONLY"""
        now = datetime.now(timezone.utc)

        pa_layer = LayerResult(
            layer="price_action",
            state=ParticipationState.FORMAL_BULLISH,
            direction="bullish",
            evidences=(),
            quality="VALID",
            limitations=(),
            decision_time=now,
            target_session="2026-08-19",
            valid_from=now,
            valid_until=now + timedelta(days=10),
        )

        fusion = fuse_dual_evidence(None, pa_layer)

        self.assertEqual(fusion.result, FusionResult.PRICE_ACTION_ONLY)
        self.assertEqual(fusion.direction, "bullish")

    def test_neutral_when_both_neutral(self):
        """两层都是 neutral 时返回 NEUTRAL"""
        now = datetime.now(timezone.utc)

        tf_layer = LayerResult(
            layer="trade_flow",
            state=ParticipationState.FORMAL_NEUTRAL,
            direction="neutral",
            evidences=(),
            quality="VALID",
            limitations=(),
            decision_time=now,
            target_session="2026-08-19",
            valid_from=now,
            valid_until=now + timedelta(days=3),
        )

        pa_layer = LayerResult(
            layer="price_action",
            state=ParticipationState.FORMAL_NEUTRAL,
            direction="neutral",
            evidences=(),
            quality="VALID",
            limitations=(),
            decision_time=now,
            target_session="2026-08-19",
            valid_from=now,
            valid_until=now + timedelta(days=10),
        )

        fusion = fuse_dual_evidence(tf_layer, pa_layer)

        self.assertEqual(fusion.result, FusionResult.NEUTRAL)
        self.assertEqual(fusion.direction, "neutral")


if __name__ == "__main__":
    unittest.main()
