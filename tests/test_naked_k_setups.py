import unittest

import naked_k_setups


class NakedKSetupTests(unittest.TestCase):
    def test_classifies_bullish_bos_continuation_setup(self):
        setup = naked_k_setups.classify_trade_setup(
            price_action={"bias": "bullish", "signals": ["收盘突破20日高点", "量价确认"], "warnings": []},
            market_structure={
                "direction": "up",
                "sequence": "HH/HL",
                "latest_event": {"kind": "BOS", "direction": "bullish", "broken_level": 17.0},
            },
            market_regime={"state": "trend", "direction": "bullish", "label": "趋势市场"},
            daily_patterns=[],
        )

        self.assertEqual(setup["key"], "bullish_bos_continuation")
        self.assertEqual(setup["direction"], "long")
        self.assertEqual(setup["quality"], "strong")
        self.assertIn("突破结构高点", setup["thesis"])
        self.assertIn("等待回踩不破突破位", setup["required_confirmation"])

    def test_classifies_bullish_choch_reversal_setup(self):
        setup = naked_k_setups.classify_trade_setup(
            price_action={"bias": "bullish", "signals": ["下破20日低点收回"], "warnings": []},
            market_structure={
                "direction": "transition",
                "prior_direction": "down",
                "sequence": "LH/LL",
                "latest_event": {"kind": "CHoCH", "direction": "bullish", "broken_level": 18.0},
            },
            market_regime={"state": "transition", "direction": "bullish", "label": "结构转换"},
            daily_patterns=["📌看涨Pin"],
        )

        self.assertEqual(setup["key"], "bullish_choch_reversal")
        self.assertEqual(setup["direction"], "long")
        self.assertEqual(setup["quality"], "developing")
        self.assertIn("结构转换", setup["thesis"])
        self.assertIn("等待小周期形成HL", setup["required_confirmation"])

    def test_classifies_failed_breakout_short_setup(self):
        setup = naked_k_setups.classify_trade_setup(
            price_action={
                "bias": "bearish",
                "signals": ["上破20日高点失败"],
                "warnings": ["前高假突破风险", "放量上破失败"],
                "volume_pressure": "派发压力",
            },
            market_structure={"direction": "sideways", "sequence": "mixed", "latest_event": None},
            market_regime={"state": "range", "direction": "neutral", "label": "震荡市场"},
            daily_patterns=["📌看跌Pin"],
        )

        self.assertEqual(setup["key"], "failed_breakout_short")
        self.assertEqual(setup["direction"], "short")
        self.assertEqual(setup["quality"], "strong")
        self.assertIn("上方流动性", setup["thesis"])
        self.assertIn("重新站回假突破高点上方", setup["invalidation_logic"])

    def test_classifies_compression_breakout_watch_setup(self):
        setup = naked_k_setups.classify_trade_setup(
            price_action={"bias": "watch", "signals": ["波幅连续收敛"], "warnings": []},
            market_structure={"direction": "contracting_range", "sequence": "LH/HL", "latest_event": None},
            market_regime={"state": "low_volatility_compression", "direction": "neutral", "label": "低波动压缩"},
            daily_patterns=["🟡双孕线"],
        )

        self.assertEqual(setup["key"], "compression_breakout_watch")
        self.assertEqual(setup["direction"], "watch")
        self.assertEqual(setup["quality"], "developing")
        self.assertIn("等待扩张K收盘确认", setup["required_confirmation"])


if __name__ == "__main__":
    unittest.main()
