import unittest

from stock_analysis.advisor import build_advice
from stock_analysis.models import TechnicalSnapshot


class AdvisorTests(unittest.TestCase):
    def test_buy_when_jg_core_technical_is_bullish_and_daily_confirmed(self):
        advice = build_advice(
            "NVDA",
            technical=TechnicalSnapshot(
                direction="bullish",
                score=2.0,
                current_price=120.0,
                summary="日线突破确认",
                supports=[118.5],
                resistances=[132.0],
                timeframe_scores={"medium": 2.0},
                timeframe_directions={"medium": "bullish"},
                warnings=[],
            ),
        )

        self.assertEqual(advice.overall_action, "买入")
        self.assertEqual(advice.confidence, "高")
        self.assertEqual(advice.position_guidance, "标准仓")
        self.assertEqual(advice.invalidation, "暂无明确失效线")
        self.assertEqual(advice.current_price, 120.0)
        self.assertEqual(set(advice.evidence), {"technical"})

    def test_bearish_technical_triggers_reduction(self):
        advice = build_advice(
            "0700.HK",
            technical=TechnicalSnapshot(direction="bearish", score=-1.5, summary="Vegas通道下方", warnings=[]),
        )

        self.assertEqual(advice.overall_action, "减仓")
        self.assertEqual(advice.short_term_action, "短线减仓")
        self.assertIn("技术趋势偏空", " ".join(advice.blocked_by))

    def test_neutral_technical_stays_observation(self):
        advice = build_advice(
            "BABA",
            technical=TechnicalSnapshot(direction="neutral", score=0.2, summary="无明显共振", warnings=[]),
        )

        self.assertEqual(advice.overall_action, "观望")
        self.assertEqual(advice.position_guidance, "空仓等待")
        self.assertIn("街哥技术信号未形成共振", " ".join(advice.blocked_by))

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
        )

        self.assertEqual(advice.short_term_action, "短线减仓")
        self.assertEqual(advice.medium_term_action, "波段买入")
        self.assertEqual(advice.long_term_action, "等待趋势修复")
        self.assertIn("趋势:", " ".join(advice.evidence["technical"]))

    def test_timeframe_state_describes_weekly_daily_and_4h_alignment(self):
        advice = build_advice(
            "NVDA",
            technical=TechnicalSnapshot(
                direction="bullish",
                score=3.0,
                timeframe_scores={"short": 1.2, "medium": 1.4, "long": 1.1},
                timeframe_directions={"short": "bullish", "medium": "bullish", "long": "bullish"},
            ),
        )

        self.assertEqual(advice.timeframe_state, "周线多头，日线买点确认，4H触发偏多")

    def test_timeframe_state_warns_when_daily_rebounds_against_weekly_bearish_trend(self):
        advice = build_advice(
            "TSLA",
            technical=TechnicalSnapshot(
                direction="neutral",
                score=0.0,
                timeframe_scores={"short": 1.0, "medium": 1.0, "long": -1.5},
                timeframe_directions={"short": "bullish", "medium": "bullish", "long": "bearish"},
            ),
        )

        self.assertEqual(advice.timeframe_state, "周线空头但日线反弹，4H只按反弹节奏处理")

    def test_bullish_short_and_long_without_daily_confirmation_is_trial_only(self):
        advice = build_advice(
            "9992.HK",
            technical=TechnicalSnapshot(
                direction="bullish",
                score=2.5,
                timeframe_scores={"short": 1.5, "medium": 0.0, "long": 1.0},
                timeframe_directions={"short": "bullish", "medium": "neutral", "long": "bullish"},
            ),
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
                timeframe_scores={"short": 1.0, "medium": -1.0, "long": 0.5},
                timeframe_directions={"short": "bullish", "medium": "neutral", "long": "neutral"},
            ),
        )

        self.assertEqual(advice.overall_action, "减仓")
        self.assertEqual(advice.short_term_action, "短线反弹观察")

    def test_overheated_technical_signal_blocks_standard_buy(self):
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
        )

        self.assertEqual(advice.overall_action, "小仓试错")
        self.assertEqual(advice.position_guidance, "小仓")
        self.assertIn("高位过热", " ".join(advice.blocked_by))

    def test_advice_carries_technical_data_source_audit_only(self):
        advice = build_advice(
            "NVDA",
            technical=TechnicalSnapshot(
                direction="bullish",
                score=2.0,
                data_sources={"medium": {"source": "yahoo_chart", "rows": 250, "latest": "2026-06-01"}},
            ),
        )

        self.assertEqual(advice.data_sources["technical"]["medium"]["source"], "yahoo_chart")

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
        )

        self.assertEqual(advice.overall_action, "观望")
        self.assertEqual(advice.short_term_action, "观望")
        self.assertEqual(advice.medium_term_action, "等待数据修复")
        self.assertEqual(advice.position_guidance, "空仓等待")
        self.assertIn("中期(日线)数据行数不足", " ".join(advice.warnings))
        self.assertIn("关键数据质量不足", " ".join(advice.blocked_by))
        self.assertIn("数据恢复", " ".join(advice.entry_triggers))
