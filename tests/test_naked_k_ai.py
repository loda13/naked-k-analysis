import unittest
from types import SimpleNamespace

import naked_k_ai


class NakedKAITests(unittest.TestCase):
    def _report(self):
        return SimpleNamespace(
            name="测试",
            ticker="TEST",
            action="小仓试错",
            entry_trigger=105.0,
            stop_loss=99.0,
            target_price=117.0,
            reward_to_risk=2.0,
            position_size="最高约10.0%仓位",
            signal_state="planned_long",
            price_action={"bias": "bullish", "signals": ["下破20日低点收回"], "warnings": []},
            market_structure={"latest_event": {"kind": "CHoCH", "direction": "bullish"}},
            market_regime={"state": "transition", "label": "结构转换"},
            trade_setup={"key": "bullish_choch_reversal", "name": "多头CHoCH反转试错"},
            price_zones={"nearest_support": {"label": "需求区", "lower": 98.0, "upper": 100.0}},
            risk_plan={"risk_level": "medium", "target_r_multiple": 2.0},
            timeframe_context={"alignment": "aligned_long"},
            trader_brief={"交易计划": "当前机会：小仓试错；胜率估计：约55%，仅作交易计划分层"},
            candle_context=[
                {
                    "behavior": "liquidity_sweep",
                    "direction": "bullish",
                    "quality_score": 8,
                    "interpretation": "空头突破失败",
                }
            ],
            review={"status": "观察中", "error_type": None, "note": "测试"},
        )

    def test_builds_ai_payload_with_strict_signal_boundary(self):
        payload = naked_k_ai.build_ai_analysis_payload(self._report())

        self.assertEqual(payload["schema_version"], "naked-k-ai-assistant-v1")
        self.assertEqual(payload["signal_boundary"]["signal_source"], "deterministic_price_action_engine")
        self.assertIn("change_action", payload["signal_boundary"]["forbidden"])
        self.assertEqual(payload["engine_plan"]["action"], "小仓试错")
        self.assertEqual(payload["engine_plan"]["entry_trigger"], 105.0)
        self.assertEqual(payload["engine_plan"]["stop_loss"], 99.0)
        joined = str(payload)
        self.assertNotIn("MACD", joined)
        self.assertNotIn("RSI", joined)

    def test_calibrates_setup_statistics_from_realized_r_samples(self):
        samples = [
            {"setup": "bullish_choch_reversal", "regime": "transition", "r_multiple": 2.0},
            {"setup": "bullish_choch_reversal", "regime": "transition", "r_multiple": -1.0},
            {"setup": "bullish_choch_reversal", "regime": "trend", "r_multiple": 1.0},
            {"setup": "failed_breakout_short", "regime": "range", "r_multiple": -0.5},
        ]

        stats = naked_k_ai.calibrate_historical_edge(
            samples,
            setup_key="bullish_choch_reversal",
            regime="transition",
            min_samples=2,
        )

        self.assertEqual(stats["sample_count"], 2)
        self.assertEqual(stats["win_rate"], 50.0)
        self.assertEqual(stats["average_r"], 0.5)
        self.assertEqual(stats["confidence_source"], "historical_samples")

    def test_attributes_failure_from_review_and_price_context(self):
        attribution = naked_k_ai.attribute_plan_outcome(
            self._report(),
            {"status": "未命中", "error_type": "假突破", "note": "盘中上破但收盘未站稳触发位"},
        )

        self.assertEqual(attribution["failure_type"], "failed_breakout")
        self.assertIn("触发后没有收盘确认", attribution["lesson"])

    def test_builds_ai_assistant_brief_with_calibrated_stats(self):
        assistant = naked_k_ai.build_ai_trading_assistant(
            self._report(),
            historical_samples=[
                {"setup": "bullish_choch_reversal", "regime": "transition", "r_multiple": 2.0},
                {"setup": "bullish_choch_reversal", "regime": "transition", "r_multiple": -1.0},
            ],
            min_samples=2,
        )

        self.assertEqual(assistant["calibrated_edge"]["confidence_source"], "historical_samples")
        self.assertIn("AI只做解释", assistant["assistant_notes"][0])
        self.assertIn("样本校准胜率", assistant["assistant_notes"][1])


if __name__ == "__main__":
    unittest.main()
