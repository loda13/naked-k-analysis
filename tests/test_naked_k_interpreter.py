import unittest
from types import SimpleNamespace

import naked_k_interpreter


class NakedKInterpreterTests(unittest.TestCase):
    def test_builds_professional_trader_brief_without_indicator_signals(self):
        report = SimpleNamespace(
            action="小仓试错",
            entry_trigger=105.0,
            stop_loss=99.0,
            target_price=117.0,
            reward_to_risk=2.0,
            position_size="最高约10.0%仓位",
            price_action={
                "bias": "bullish",
                "signals": ["下破20日低点收回", "放量下破收回"],
                "warnings": [],
                "volume_pressure": "承接增强",
            },
            market_structure={
                "direction": "transition",
                "latest_event": {"kind": "CHoCH", "direction": "bullish", "broken_level": 104.0},
                "last_swing_low": {"price": 98.0},
                "last_swing_high": {"price": 116.0},
            },
            market_regime={"label": "结构转换", "state": "transition", "direction": "bullish"},
            trade_setup={
                "name": "多头CHoCH反转试错",
                "direction": "long",
                "confidence_score": 6,
                "quality": "medium",
                "thesis": "下降结构被打断，空头追击失败",
            },
            price_zones={
                "nearest_support": {"label": "需求区", "lower": 97.5, "upper": 100.0},
                "nearest_resistance": {"label": "供给区", "lower": 116.0, "upper": 118.0},
            },
            risk_plan={
                "risk_level": "medium",
                "effective_account_risk_pct": 0.5,
                "target_r_multiple": 2.0,
            },
            timeframe_context={
                "alignment": "aligned_long",
                "decision_filter": "大周期方向与中周期结构支持日线多头机会，等待小周期触发确认",
            },
        )

        brief = naked_k_interpreter.build_trader_brief(report)

        self.assertIn("当前市场状态", brief)
        self.assertIn("多空力量分析", brief)
        self.assertIn("关键价格区域", brief)
        self.assertIn("可能交易路径", brief)
        self.assertIn("交易计划", brief)
        self.assertIn("风险点", brief)
        self.assertIn("空头追击失败", brief["多空力量分析"])
        self.assertIn("胜率估计", brief["交易计划"])
        self.assertIn("失效位置", brief["交易计划"])
        joined = " ".join(str(value) for value in brief.values())
        self.assertNotIn("MACD", joined)
        self.assertNotIn("RSI", joined)


if __name__ == "__main__":
    unittest.main()
