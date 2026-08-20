import unittest
from types import SimpleNamespace

import naked_k_config
import naked_k_portfolio


class NakedKPortfolioTests(unittest.TestCase):
    def test_classifies_korean_exchange_ticker_as_kr_market(self):
        self.assertEqual(naked_k_portfolio.classify_market("000660.KS"), "kr")

    def test_hyphenated_us_share_class_counts_as_us_exposure(self):
        report = SimpleNamespace(
            ticker="BRK-B",
            action="买入",
            risk_plan={
                "direction": "long",
                "suggested_gross_pct": 10.0,
                "effective_account_risk_pct": 0.5,
            },
        )

        exposure = naked_k_portfolio.evaluate_portfolio_exposure([report])

        self.assertEqual(exposure["market_gross_pct"], {"us": 10.0})

    def test_evaluates_total_direction_market_and_account_risk_exposure(self):
        config = naked_k_config.PortfolioConfig(
            max_total_gross_pct=45.0,
            max_direction_gross_pct=35.0,
            max_market_gross_pct=30.0,
            max_single_name_gross_pct=25.0,
            max_total_account_risk_pct=1.5,
        )
        reports = [
            SimpleNamespace(
                ticker="0700.HK",
                action="买入",
                risk_plan={"direction": "long", "suggested_gross_pct": 22.0, "effective_account_risk_pct": 0.8},
            ),
            SimpleNamespace(
                ticker="1810.HK",
                action="小仓试错",
                risk_plan={"direction": "long", "suggested_gross_pct": 18.0, "effective_account_risk_pct": 0.6},
            ),
            SimpleNamespace(
                ticker="NVDA",
                action="买入",
                risk_plan={"direction": "long", "suggested_gross_pct": 20.0, "effective_account_risk_pct": 0.7},
            ),
        ]

        exposure = naked_k_portfolio.evaluate_portfolio_exposure(reports, config=config)

        self.assertEqual(exposure["total_gross_pct"], 60.0)
        self.assertEqual(exposure["direction_gross_pct"]["long"], 60.0)
        self.assertEqual(exposure["market_gross_pct"]["hk"], 40.0)
        self.assertEqual(exposure["total_account_risk_pct"], 2.1)
        self.assertEqual(exposure["status"], "over_limit")
        self.assertIn("总仓位暴露超限", exposure["guardrails"])
        self.assertIn("多头方向暴露超限", exposure["guardrails"])
        self.assertIn("hk市场暴露超限", exposure["guardrails"])
        self.assertIn("账户风险暴露超限", exposure["guardrails"])

    def test_allows_flat_portfolio_without_guardrails(self):
        exposure = naked_k_portfolio.evaluate_portfolio_exposure([], config=naked_k_config.PortfolioConfig())

        self.assertEqual(exposure["status"], "within_limits")
        self.assertEqual(exposure["total_gross_pct"], 0.0)
        self.assertEqual(exposure["guardrails"], [])

    def test_defensive_residual_long_exposure_cannot_bypass_direction_cap(self):
        reports = [
            SimpleNamespace(
                ticker=ticker,
                action="减仓",
                risk_plan={
                    "direction": "bearish_defensive",
                    "suggested_gross_pct": 15.0,
                    "effective_account_risk_pct": 0.5,
                },
            )
            for ticker in ("AAA", "BBB")
        ]
        config = naked_k_config.PortfolioConfig(
            max_total_gross_pct=100.0,
            max_direction_gross_pct=20.0,
            max_market_gross_pct=100.0,
            max_single_name_gross_pct=100.0,
            max_total_account_risk_pct=100.0,
        )

        exposure = naked_k_portfolio.evaluate_portfolio_exposure(reports, config)

        self.assertEqual(exposure["total_gross_pct"], 30.0)
        self.assertEqual(exposure["direction_gross_pct"]["long"], 30.0)
        self.assertEqual(exposure["status"], "over_limit")
        self.assertEqual(exposure["guardrails"], ["多头方向暴露超限"])


if __name__ == "__main__":
    unittest.main()
