import unittest

import pandas as pd

import naked_k_context


class NakedKContextTests(unittest.TestCase):
    def test_contextualizes_liquidity_sweep_pin_bar_with_structure_volume_and_zone(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 99.0, 98.0, 97.0, 96.0, 95.0],
                "High": [102.0, 101.0, 100.0, 99.0, 98.0, 101.5],
                "Low": [96.0, 95.5, 95.2, 95.0, 94.8, 90.0],
                "Close": [99.0, 98.0, 97.0, 96.0, 95.0, 100.5],
                "Volume": [1000, 980, 1020, 990, 1010, 2200],
            },
            index=pd.date_range("2026-06-01", periods=6, freq="D"),
        )
        price_action = {
            "bias": "bullish",
            "signals": ["下破5日低点收回", "放量下破收回"],
            "volume_pressure": "承接增强",
            "volatility_state": "宽幅震荡",
        }
        market_structure = {
            "sequence": "LH/LL",
            "latest_event": {"kind": "CHoCH", "direction": "bullish", "broken_level": 99.0},
        }
        price_zones = {
            "nearest_support": {"label": "需求区", "lower": 89.5, "upper": 95.5, "midpoint": 92.5},
            "liquidity_pools": [{"kind": "sell_side_liquidity", "label": "下方卖方流动性池", "midpoint": 95.0}],
        }

        contexts = naked_k_context.build_candle_behavior_context(
            frame,
            price_action=price_action,
            market_structure=market_structure,
            price_zones=price_zones,
        )

        sweep = contexts[0]
        self.assertEqual(sweep["behavior"], "liquidity_sweep")
        self.assertEqual(sweep["direction"], "bullish")
        self.assertEqual(sweep["location"], "support_liquidity")
        self.assertEqual(sweep["volume_context"], "volume_absorption")
        self.assertEqual(sweep["structure_context"], "bullish_choch")
        self.assertGreaterEqual(sweep["quality_score"], 8)
        self.assertIn("空头突破失败", sweep["interpretation"])

    def test_contextualizes_inside_bar_as_compression_not_trade_signal(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 104.0, 103.0],
                "High": [105.0, 110.0, 108.0],
                "Low": [95.0, 100.0, 102.0],
                "Close": [103.0, 106.0, 103.0],
                "Volume": [1000, 1200, 700],
            },
            index=pd.date_range("2026-06-01", periods=3, freq="D"),
        )

        contexts = naked_k_context.build_candle_behavior_context(
            frame,
            price_action={"bias": "watch", "signals": ["波幅连续收敛"], "volume_state": "缩量"},
            market_structure={"sequence": "range"},
            price_zones={},
        )

        inside = contexts[0]
        self.assertEqual(inside["behavior"], "inside_bar")
        self.assertEqual(inside["direction"], "watch")
        self.assertEqual(inside["volatility_context"], "compression")
        self.assertIn("等待母线高低点被收盘突破", inside["confirmation"])


if __name__ == "__main__":
    unittest.main()
