import unittest

from stock_analysis.fundamental import score_fundamental


class FundamentalScoreTests(unittest.TestCase):
    def test_scores_jg_research_style_components(self):
        score = score_fundamental(
            ticker="KAP",
            purity=10,
            moat=28,
            commercialization=18,
            financial_quality=13,
            industry_position=14,
            valuation=8,
            risk_deduction=7,
            evidence_grade="A",
        )

        self.assertEqual(score.total_score, 84)
        self.assertEqual(score.status, "买入")
        self.assertEqual(score.components["moat"], 28)
        self.assertEqual(score.evidence_grade, "A")

    def test_clamps_component_scores_and_caps_low_evidence_status(self):
        score = score_fundamental(
            ticker="CONCEPT",
            purity=99,
            moat=99,
            commercialization=99,
            financial_quality=99,
            industry_position=99,
            valuation=99,
            risk_deduction=-10,
            evidence_grade="C",
        )

        self.assertEqual(score.total_score, 100)
        self.assertEqual(score.components["purity"], 10)
        self.assertEqual(score.components["risk_deduction"], 0)
        self.assertEqual(score.status, "观察")

    def test_low_total_is_avoid_even_with_good_evidence(self):
        score = score_fundamental(
            ticker="WEAK",
            purity=2,
            moat=8,
            commercialization=5,
            financial_quality=4,
            industry_position=4,
            valuation=2,
            risk_deduction=8,
            evidence_grade="B",
        )

        self.assertEqual(score.total_score, 17)
        self.assertEqual(score.status, "回避")
