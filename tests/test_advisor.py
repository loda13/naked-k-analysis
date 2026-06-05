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

    def test_horizon_actions_follow_separate_timeframe_directions(self):
        advice = build_advice(
            "0700.HK",
            technical=TechnicalSnapshot(
                direction="neutral",
                score=0.0,
                timeframe_scores={"short": -1.5, "medium": 2.0, "long": -1.2},
                timeframe_directions={"short": "bearish", "medium": "bullish", "long": "bearish"},
                evidence_sections={
                    "trend": ["周线Vegas通道下方"],
                    "momentum": ["日线MACD零轴上"],
                    "cost": ["日线FRVP价值区上方"],
                },
                warnings=[],
            ),
            naked=NakedKSnapshot(direction="neutral", score=0.0),
        )

        self.assertEqual(advice.short_term_action, "短线减仓")
        self.assertEqual(advice.medium_term_action, "波段买入")
        self.assertEqual(advice.long_term_action, "等待趋势修复")
        self.assertIn("趋势:", " ".join(advice.evidence["technical"]))

    def test_bullish_short_and_long_without_daily_confirmation_is_trial_only(self):
        advice = build_advice(
            "9992.HK",
            technical=TechnicalSnapshot(
                direction="bullish",
                score=2.5,
                timeframe_scores={"short": 1.5, "medium": 0.0, "long": 1.0},
                timeframe_directions={"short": "bullish", "medium": "neutral", "long": "bullish"},
            ),
            naked=NakedKSnapshot(direction="bullish", score=1.0, invalidation=174.85),
        )

        self.assertEqual(advice.overall_action, "小仓试错")
        self.assertEqual(advice.position_guidance, "小仓")
        self.assertIn("日线买点", advice.medium_term_action)

    def test_overall_bearish_risk_prevents_short_trial_language(self):
        advice = build_advice(
            "NVDA",
            technical=TechnicalSnapshot(
                direction="bearish",
                score=-1.5,
                timeframe_scores={"short": -1.0, "medium": -1.0, "long": 0.5},
                timeframe_directions={"short": "neutral", "medium": "neutral", "long": "neutral"},
            ),
            naked=NakedKSnapshot(direction="bullish", score=1.5, invalidation=210.49),
        )

        self.assertEqual(advice.overall_action, "减仓")
        self.assertEqual(advice.short_term_action, "短线反弹观察")

    def test_overheated_far_invalidation_blocks_standard_buy(self):
        advice = build_advice(
            "MRVL",
            technical=TechnicalSnapshot(
                direction="bullish",
                score=3.0,
                current_price=316.0,
                timeframe_scores={"short": 2.0, "medium": 1.0, "long": 0.0},
                timeframe_directions={"short": "bullish", "medium": "bullish", "long": "neutral"},
                risk_flags=["高位过热"],
            ),
            naked=NakedKSnapshot(
                direction="bullish",
                score=6.0,
                current_price=316.0,
                invalidation=170.0,
                supports=[170.0],
            ),
        )

        self.assertEqual(advice.overall_action, "观望")
        self.assertEqual(advice.short_term_action, "观望")
        self.assertEqual(advice.medium_term_action, "等待日线买点")
        self.assertEqual(advice.position_guidance, "空仓等待")
        self.assertIn("高位过热", " ".join(advice.blocked_by))
        self.assertIn("失效线距离过远", " ".join(advice.blocked_by))

    def test_advice_carries_data_source_audit(self):
        advice = build_advice(
            "NVDA",
            technical=TechnicalSnapshot(
                direction="bullish",
                score=2.0,
                data_sources={"medium": {"source": "yahoo_chart", "rows": 250, "latest": "2026-06-01"}},
            ),
            naked=NakedKSnapshot(
                direction="bullish",
                score=2.0,
                data_source={"source": "yahoo_chart", "rows": 365, "latest": "2026-06-01"},
            ),
        )

        self.assertEqual(advice.data_sources["technical"]["medium"]["source"], "yahoo_chart")
        self.assertEqual(advice.data_sources["naked_k"]["source"], "yahoo_chart")

    def test_unreliable_medium_data_blocks_buy_signal(self):
        advice = build_advice(
            "NVDA",
            technical=TechnicalSnapshot(
                direction="bullish",
                score=2.0,
                current_price=120.0,
                timeframe_scores={"medium": 2.0},
                timeframe_directions={"medium": "bullish"},
                data_sources={"medium": {"source": "yahoo_chart", "rows": 35, "latest": "2026-06-01"}},
            ),
            naked=NakedKSnapshot(
                direction="bullish",
                score=2.0,
                current_price=120.0,
                invalidation=112.0,
                data_source={"source": "yahoo_chart", "rows": 120, "latest": "2026-06-01"},
            ),
        )

        self.assertEqual(advice.overall_action, "观望")
        self.assertEqual(advice.short_term_action, "观望")
        self.assertEqual(advice.medium_term_action, "等待数据修复")
        self.assertEqual(advice.position_guidance, "空仓等待")
        self.assertIn("中期(日线)数据行数不足", " ".join(advice.warnings))
        self.assertIn("关键数据质量不足", " ".join(advice.blocked_by))
        self.assertIn("数据恢复", " ".join(advice.entry_triggers))

    def test_stale_naked_k_data_blocks_trial_signal(self):
        advice = build_advice(
            "BABA",
            technical=TechnicalSnapshot(
                direction="neutral",
                score=0.0,
                data_sources={"medium": {"source": "tencent", "rows": 250, "latest": "2026-06-01"}},
            ),
            naked=NakedKSnapshot(
                direction="bullish",
                score=2.0,
                invalidation=88.0,
                data_source={"source": "tencent", "rows": 240, "latest": "2020-01-01"},
            ),
        )

        self.assertEqual(advice.overall_action, "观望")
        self.assertEqual(advice.short_term_action, "观望")
        self.assertEqual(advice.medium_term_action, "等待数据修复")
        self.assertIn("裸K数据过旧", " ".join(advice.warnings))
        self.assertIn("关键数据质量不足", " ".join(advice.blocked_by))
        self.assertIn("数据恢复", " ".join(advice.entry_triggers))
