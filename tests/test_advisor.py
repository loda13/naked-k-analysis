import unittest

from stock_analysis.advisor import build_advice
from stock_analysis.models import NakedKSnapshot, TechnicalSnapshot


class AdvisorTests(unittest.TestCase):
    def test_buy_when_jg_technical_and_naked_k_are_bullish(self):
        advice = build_advice(
            "NVDA",
            technical=TechnicalSnapshot(direction="bullish", score=2.0, summary="日线突破确认", warnings=[]),
            naked=NakedKSnapshot(
                direction="bullish",
                score=2.0,
                invalidation=118.5,
                supports=[118.5],
                resistances=[132.0],
                summary="上升趋势",
            ),
        )

        self.assertEqual(advice.overall_action, "买入")
        self.assertEqual(advice.confidence, "高")
        self.assertIn("118.5", advice.invalidation)
        self.assertIn("站稳", " ".join(advice.entry_triggers))
        self.assertEqual(advice.blocked_by, [])
        self.assertEqual(set(advice.evidence), {"technical", "naked_k"})

    def test_bearish_technical_and_naked_k_blocks_new_buy(self):
        advice = build_advice(
            "0700.HK",
            technical=TechnicalSnapshot(direction="bearish", score=-1.5, summary="Vegas通道下方", warnings=[]),
            naked=NakedKSnapshot(
                direction="bearish",
                score=-4.0,
                supports=[],
                resistances=[478.5],
                summary="下降趋势, BoS",
            ),
        )

        self.assertEqual(advice.overall_action, "卖出")
        self.assertEqual(advice.short_term_action, "短线减仓")
        self.assertIn("技术趋势偏空", " ".join(advice.blocked_by))
        self.assertIn("裸K结构偏空", " ".join(advice.blocked_by))

    def test_neutral_technical_with_bullish_naked_k_is_trial_only(self):
        advice = build_advice(
            "BABA",
            technical=TechnicalSnapshot(direction="neutral", score=0.2, summary="无明显共振", warnings=[]),
            naked=NakedKSnapshot(
                direction="bullish",
                score=2.0,
                invalidation=88.0,
                supports=[88.0],
                resistances=[96.0],
                summary="支撑反弹",
            ),
        )

        self.assertEqual(advice.overall_action, "小仓试错")
        self.assertEqual(advice.position_guidance, "小仓")
        self.assertIn("回踩", " ".join(advice.entry_triggers))

    def test_missing_technical_keeps_observation_without_external_warning(self):
        advice = build_advice(
            "UNKNOWN",
            technical=TechnicalSnapshot(warnings=["技术分析无数据"]),
            naked=NakedKSnapshot(warnings=["裸K分析无数据"]),
        )

        self.assertEqual(advice.overall_action, "观望")
        self.assertNotIn("外部研究", " ".join(advice.warnings + advice.blocked_by))
