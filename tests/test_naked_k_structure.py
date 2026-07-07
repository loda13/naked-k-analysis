import unittest

import pandas as pd

import naked_k_structure


class NakedKStructureTests(unittest.TestCase):
    def test_detects_bullish_hh_hl_sequence_and_bos(self):
        frame = pd.DataFrame(
            {
                "Open": [9.0, 10.5, 10.0, 12.5, 12.0, 14.5, 14.0, 15.5, 15.0, 18.0],
                "High": [10.0, 12.0, 11.0, 14.0, 13.0, 16.0, 15.0, 17.0, 16.0, 19.0],
                "Low": [8.0, 9.0, 8.5, 10.0, 9.5, 12.0, 11.0, 13.0, 12.5, 15.0],
                "Close": [9.0, 11.0, 10.0, 13.0, 12.0, 15.0, 14.0, 16.0, 15.0, 18.5],
                "Volume": [1000, 1200, 950, 1300, 980, 1400, 1000, 1500, 1050, 1800],
            },
            index=pd.date_range("2026-06-01", periods=10, freq="D"),
        )

        structure = naked_k_structure.analyze_market_structure(frame, swing_window=1)

        self.assertEqual(structure["direction"], "up")
        self.assertEqual(structure["sequence"], "HH/HL")
        self.assertEqual(structure["latest_event"]["kind"], "BOS")
        self.assertEqual(structure["latest_event"]["direction"], "bullish")
        self.assertEqual(structure["last_swing_high"]["price"], 17.0)
        self.assertEqual(structure["last_swing_low"]["price"], 12.5)

    def test_detects_bullish_choch_after_lower_high_lower_low_sequence(self):
        frame = pd.DataFrame(
            {
                "Open": [19.0, 20.0, 18.0, 19.0, 17.0, 18.0, 16.0, 17.0, 15.0, 19.0],
                "High": [20.0, 21.0, 19.0, 20.0, 18.0, 19.0, 17.0, 18.0, 16.0, 20.5],
                "Low": [18.0, 19.0, 16.5, 18.0, 15.0, 17.0, 14.0, 16.0, 13.5, 15.0],
                "Close": [19.0, 20.0, 17.0, 19.0, 16.0, 18.0, 15.0, 17.0, 14.5, 20.2],
                "Volume": [1000, 1100, 1300, 1000, 1350, 950, 1400, 900, 1450, 2100],
            },
            index=pd.date_range("2026-06-01", periods=10, freq="D"),
        )

        structure = naked_k_structure.analyze_market_structure(frame, swing_window=1)

        self.assertEqual(structure["prior_direction"], "down")
        self.assertEqual(structure["latest_event"]["kind"], "CHoCH")
        self.assertEqual(structure["latest_event"]["direction"], "bullish")
        self.assertEqual(structure["latest_event"]["broken_level"], 18.0)

    def test_classifies_low_volatility_compression_regime(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0, 102.5, 103.0, 103.2, 103.4],
                "High": [110.0, 109.0, 108.0, 107.0, 106.0, 105.0, 104.5],
                "Low": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 101.5],
                "Close": [105.0, 104.0, 104.0, 103.5, 103.0, 102.5, 103.5],
                "Volume": [1000, 980, 960, 940, 920, 900, 880],
            },
            index=pd.date_range("2026-06-01", periods=7, freq="D"),
        )

        regime = naked_k_structure.classify_market_regime(frame)

        self.assertEqual(regime["state"], "low_volatility_compression")
        self.assertEqual(regime["label"], "低波动压缩")
        self.assertLessEqual(regime["range_ratio"], 0.7)

    def test_classifies_trend_regime_from_market_structure(self):
        frame = pd.DataFrame(
            {
                "Open": [9.0, 10.5, 10.0, 12.5, 12.0, 14.5, 14.0, 15.5, 15.0, 18.0],
                "High": [10.0, 12.0, 11.0, 14.0, 13.0, 16.0, 15.0, 17.0, 16.0, 19.0],
                "Low": [8.0, 9.0, 8.5, 10.0, 9.5, 12.0, 11.0, 13.0, 12.5, 15.0],
                "Close": [9.0, 11.0, 10.0, 13.0, 12.0, 15.0, 14.0, 16.0, 15.0, 18.5],
                "Volume": [1000, 1200, 950, 1300, 980, 1400, 1000, 1500, 1050, 1800],
            },
            index=pd.date_range("2026-06-01", periods=10, freq="D"),
        )
        structure = naked_k_structure.analyze_market_structure(frame, swing_window=1)

        regime = naked_k_structure.classify_market_regime(frame, structure)

        self.assertEqual(regime["state"], "trend")
        self.assertEqual(regime["direction"], "bullish")
        self.assertEqual(regime["label"], "趋势市场")


if __name__ == "__main__":
    unittest.main()
