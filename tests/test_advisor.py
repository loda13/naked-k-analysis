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
        self.assertIn("站稳", " ".join(advice.entry_triggers))
        self.assertEqual(advice.blocked_by, [])

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
        self.assertIn("缺少WSS研究缓存", " ".join(advice.blocked_by))

    def test_research_quality_details_are_in_evidence(self):
        ctx = load_wss_context("tests/fixtures/wss")

        advice = build_advice(
            "NVDA",
            ctx,
            technical=TechnicalSnapshot(direction="neutral", score=0.0, warnings=[]),
        )

        research_text = " ".join(advice.evidence["research"])
        self.assertIn("护城河: CUDA生态和开发者锁定", research_text)
        self.assertIn("商业验证: 云厂商AI资本开支持续验证", research_text)
        self.assertIn("风险扣分: 出口限制和供应链集中", research_text)

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
        self.assertIn("财报临近", " ".join(advice.blocked_by))
