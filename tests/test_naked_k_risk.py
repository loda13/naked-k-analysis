import unittest

import naked_k_config
import naked_k_risk


class NakedKRiskTests(unittest.TestCase):
    def test_builds_long_risk_plan_with_r_targets_and_position_cap(self):
        plan = naked_k_risk.build_risk_plan(
            action="小仓试错",
            entry_trigger=105.0,
            stop_loss=95.0,
            target_price=130.0,
            account_risk_pct=1.0,
        )

        self.assertEqual(plan["direction"], "long")
        self.assertEqual(plan["status"], "active")
        self.assertEqual(plan["risk_per_share"], 10.0)
        self.assertEqual(plan["risk_pct"], 9.52)
        self.assertEqual(plan["suggested_gross_pct"], 10.5)
        self.assertEqual(plan["targets_by_r"]["1R"], 115.0)
        self.assertEqual(plan["targets_by_r"]["2R"], 125.0)
        self.assertEqual(plan["targets_by_r"]["3R"], 135.0)
        self.assertEqual(plan["target_r_multiple"], 2.5)
        self.assertIn("按1%账户风险", plan["position_size"])

    def test_builds_short_risk_plan_with_downside_r_targets(self):
        plan = naked_k_risk.build_risk_plan(
            action="减仓",
            entry_trigger=100.0,
            stop_loss=110.0,
            target_price=80.0,
            account_risk_pct=1.0,
        )

        self.assertEqual(plan["direction"], "short")
        self.assertEqual(plan["risk_per_share"], 10.0)
        self.assertEqual(plan["targets_by_r"]["1R"], 90.0)
        self.assertEqual(plan["targets_by_r"]["2R"], 80.0)
        self.assertEqual(plan["target_r_multiple"], 2.0)

    def test_blocks_new_risk_when_drawdown_guard_is_hit(self):
        plan = naked_k_risk.build_risk_plan(
            action="买入",
            entry_trigger=105.0,
            stop_loss=100.0,
            target_price=120.0,
            account_risk_pct=1.0,
            current_drawdown_pct=8.0,
            max_drawdown_pct=8.0,
        )

        self.assertEqual(plan["status"], "blocked")
        self.assertEqual(plan["suggested_gross_pct"], 0.0)
        self.assertEqual(plan["effective_account_risk_pct"], 0.0)
        self.assertIn("最大回撤保护", plan["guardrails"])

    def test_reduces_risk_after_consecutive_losses(self):
        plan = naked_k_risk.build_risk_plan(
            action="买入",
            entry_trigger=105.0,
            stop_loss=100.0,
            target_price=120.0,
            account_risk_pct=1.0,
            consecutive_losses=3,
        )

        self.assertEqual(plan["status"], "reduced")
        self.assertEqual(plan["effective_account_risk_pct"], 0.5)
        self.assertLess(plan["suggested_gross_pct"], 20.0)
        self.assertIn("连续亏损降风险", plan["guardrails"])

    def test_uses_risk_config_for_caps_and_loss_guard(self):
        config = naked_k_config.RiskConfig(
            account_risk_pct=0.8,
            max_drawdown_pct=6.0,
            consecutive_loss_limit=2,
            consecutive_loss_risk_multiplier=0.25,
            action_gross_caps={"买入": 12.0, "小仓试错": 6.0, "减仓": 5.0, "回避": 0.0, "观望": 0.0},
        )

        capped = naked_k_risk.build_risk_plan(
            action="买入",
            entry_trigger=100.0,
            stop_loss=99.0,
            target_price=110.0,
            config=config,
        )
        reduced = naked_k_risk.build_risk_plan(
            action="买入",
            entry_trigger=100.0,
            stop_loss=95.0,
            target_price=110.0,
            consecutive_losses=2,
            config=config,
        )

        self.assertEqual(capped["max_gross_pct"], 12.0)
        self.assertEqual(capped["suggested_gross_pct"], 12.0)
        self.assertEqual(capped["base_account_risk_pct"], 0.8)
        self.assertEqual(reduced["status"], "reduced")
        self.assertEqual(reduced["effective_account_risk_pct"], 0.2)


if __name__ == "__main__":
    unittest.main()
