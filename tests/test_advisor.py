import unittest
from datetime import date

from stock_analysis.advisor import build_advice
from stock_analysis.cache import load_wss_context
from stock_analysis.models import NakedKSnapshot, TechnicalSnapshot


class AdvisorTests(unittest.TestCase):
    def test_buy_when_research_accepts_and_technical_bullish(self):
        ctx = load_wss_context("tests/fixtures/wss")

        advice = build_advice(
            "NVDA",
            ctx,
            technical=TechnicalSnapshot(direction="bullish", score=2.0, warnings=[]),
            naked=NakedKSnapshot(
                direction="bullish",
                invalidation=118.5,
                supports=[118.5],
                resistances=[132.0],
            ),
        )

        self.assertEqual(advice.overall_action, "买入")
        self.assertIn("118.5", advice.invalidation)

    def test_avoid_when_research_marks_weak(self):
        ctx = load_wss_context("tests/fixtures/wss")

        advice = build_advice(
            "INTC",
            ctx,
            technical=TechnicalSnapshot(direction="bullish", score=2.0, warnings=[]),
        )

        self.assertEqual(advice.overall_action, "回避")

    def test_missing_research_caps_to_watch(self):
        ctx = load_wss_context("tests/fixtures/wss")

        advice = build_advice(
            "UNKNOWN",
            ctx,
            technical=TechnicalSnapshot(direction="bullish", score=2.0, warnings=[]),
        )

        self.assertEqual(advice.overall_action, "观望")
        self.assertEqual(advice.confidence, "中")

    def test_high_iv_near_earnings_blocks_fresh_buy(self):
        ctx = load_wss_context("tests/fixtures/wss")

        advice = build_advice(
            "NVDA",
            ctx,
            technical=TechnicalSnapshot(direction="bullish", score=2.0, warnings=[]),
            naked=NakedKSnapshot(
                direction="bullish",
                invalidation=118.5,
                supports=[118.5],
                resistances=[132.0],
            ),
            today=date(2026, 6, 5),
        )

        self.assertEqual(advice.overall_action, "观望")
        self.assertEqual(advice.short_term_action, "等财报后再看")
        self.assertIn("财报临近", " ".join(advice.warnings))
