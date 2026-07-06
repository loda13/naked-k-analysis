import unittest

import pandas as pd

import naked_k_patterns


class NakedKPatternTests(unittest.TestCase):
    def test_detects_bullish_engulfing(self):
        frame = pd.DataFrame(
            {
                "Open": [105.0, 99.0],
                "High": [106.0, 108.0],
                "Low": [98.0, 97.0],
                "Close": [100.0, 107.0],
                "Volume": [1000, 1400],
            }
        )

        patterns = naked_k_patterns.detect_kline_patterns(frame)

        self.assertIn("🟢看涨吸收", patterns)

    def test_detects_bearish_pin_bar(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 101.0],
                "High": [102.0, 115.0],
                "Low": [98.0, 100.0],
                "Close": [101.0, 102.0],
                "Volume": [1000, 1600],
            }
        )

        patterns = naked_k_patterns.detect_kline_patterns(frame)

        self.assertIn("📌看跌Pin", patterns)

    def test_detects_inside_bar(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 102.0, 104.0],
                "High": [105.0, 110.0, 108.0],
                "Low": [95.0, 100.0, 102.0],
                "Close": [103.0, 106.0, 103.0],
                "Volume": [1000, 1200, 900],
            }
        )

        pattern = naked_k_patterns.detect_inside_bar(frame)

        self.assertEqual(pattern, "🟡孕线(阳孕阴)")


if __name__ == "__main__":
    unittest.main()
