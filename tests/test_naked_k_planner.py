import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import naked_k_analysis
import naked_k_planner
import naked_k_trade


class NakedKPlannerTests(unittest.TestCase):
    def _sample_frame(self):
        return pd.DataFrame(
            {
                "Open": [100.0, 140.0, 101.0, 100.0, 94.0],
                "High": [102.0, 140.0, 102.0, 101.0, 107.0],
                "Low": [98.0, 110.0, 95.0, 94.0, 93.0],
                "Close": [101.0, 120.0, 100.0, 95.0, 106.0],
                "Volume": [1000, 1000, 1000, 1000, 1200],
            },
            index=pd.to_datetime(["2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"]),
        )

    def test_planner_builds_instrument_report_directly(self):
        daily = self._sample_frame()
        weekly = daily.copy()

        report = naked_k_planner.build_trade_plan("测试", "TEST", daily, weekly, previous=None)

        self.assertIsInstance(report, naked_k_planner.InstrumentReport)
        self.assertEqual(report.name, "测试")
        self.assertEqual(report.ticker, "TEST")
        self.assertIn(report.action, {"买入", "小仓试错", "观望", "减仓", "回避"})
        self.assertIn("裸K结构", report.rationale)

    def test_planner_attaches_contextual_candle_behavior(self):
        daily = pd.DataFrame(
            {
                "Open": [100.0, 99.0, 98.0, 97.0, 96.0, 95.0],
                "High": [102.0, 101.0, 100.0, 99.0, 98.0, 101.5],
                "Low": [96.0, 95.5, 95.2, 95.0, 94.8, 90.0],
                "Close": [99.0, 98.0, 97.0, 96.0, 95.0, 100.5],
                "Volume": [1000, 980, 1020, 990, 1010, 2200],
            },
            index=pd.date_range("2026-06-01", periods=6, freq="D"),
        )

        report = naked_k_planner.build_trade_plan("测试", "TEST", daily, daily.copy(), previous=None)

        self.assertTrue(report.candle_context)
        self.assertEqual(report.candle_context[0]["direction"], "bullish")
        self.assertIn("行为上下文", report.rationale)

    def test_planner_attaches_ai_assistant_payload_without_overriding_signal(self):
        daily = self._sample_frame()

        report = naked_k_planner.build_trade_plan("测试", "TEST", daily, daily.copy(), previous=None)

        self.assertEqual(report.ai_assistant["engine_plan"]["action"], report.action)
        self.assertEqual(report.ai_assistant["engine_plan"]["entry_trigger"], report.entry_trigger)
        self.assertIn("change_action", report.ai_assistant["signal_boundary"]["forbidden"])

    def test_analysis_build_trade_plan_delegates_to_planner(self):
        daily = self._sample_frame()
        weekly = daily.copy()
        sentinel = naked_k_planner.InstrumentReport(
            name="sentinel",
            ticker="TEST",
            action="观望",
            entry_trigger=1.0,
            stop_loss=0.9,
            target_price=None,
            risk_per_share=0.1,
            reward_to_risk=None,
            signal_state="watching",
            resistance=1.1,
            support=0.9,
            position_size="0%-10%",
            rationale="sentinel",
            daily_patterns=[],
            weekly_patterns=[],
            weekly_context="sentinel",
            data_sources={"daily": "fixture", "weekly": "fixture"},
            latest_k_dates={"daily": "2026-06-26", "weekly": "2026-06-26"},
            latest_closes={"daily": 1.0, "weekly": 1.0},
            review={"status": "观察中", "error_type": None, "note": "sentinel"},
            improvement="sentinel",
        )

        with patch("naked_k_planner.build_trade_plan", return_value=sentinel) as planner:
            report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, weekly, previous=None)

        self.assertIs(report, sentinel)
        planner.assert_called_once()

    def test_analysis_uses_planner_report_model_without_legacy_builder(self):
        self.assertIs(naked_k_analysis.InstrumentReport, naked_k_planner.InstrumentReport)
        self.assertFalse(hasattr(naked_k_analysis, "_legacy_build_trade_plan"))

    def test_planner_has_no_runtime_dependency_on_cli_module(self):
        planner_source = Path(naked_k_planner.__file__).read_text(encoding="utf-8")

        self.assertNotIn("naked_k_analysis", planner_source)

    def test_analysis_reexports_trade_helpers_from_core_module(self):
        self.assertIs(naked_k_analysis.build_breakout_trigger, naked_k_trade.build_breakout_trigger)
        self.assertIs(naked_k_analysis.analyze_price_action_context, naked_k_trade.analyze_price_action_context)
        self.assertIs(naked_k_analysis.review_previous_call, naked_k_trade.review_previous_call)


if __name__ == "__main__":
    unittest.main()
