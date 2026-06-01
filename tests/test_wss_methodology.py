import unittest

from stock_analysis.wss_methodology import interpret_timeframe, summarize_methodology


class WssMethodologyTests(unittest.TestCase):
    def test_macd_reads_zero_axis_before_cross(self):
        item = {
            "tf": "日线",
            "macd": {"zone": "零轴下", "hist_dir": "绿柱", "cross": "金叉"},
        }

        summary = interpret_timeframe(item)

        self.assertLess(summary.index("零轴下"), summary.index("绿柱"))
        self.assertLess(summary.index("绿柱"), summary.index("金叉"))
        self.assertIn("金叉只作节奏确认", summary)

    def test_rsi_is_context_aware_in_strong_trend(self):
        item = {
            "tf": "周线",
            "arrangement": "多头🟢",
            "rsi": 73,
            "rsi_signal": "超买",
        }

        summary = interpret_timeframe(item)

        self.assertIn("强趋势", summary)
        self.assertIn("不直接按超买卖出", summary)

    def test_summarize_methodology_uses_timeframe_items(self):
        payload = {
            "timeframes": [
                {
                    "tf": "日线",
                    "macd": {"zone": "零轴上", "hist_dir": "红柱", "cross": None},
                    "rsi": 56,
                    "rsi_signal": "偏强",
                    "boll_signal": "接近上轨",
                }
            ]
        }

        summaries = summarize_methodology(payload)

        self.assertEqual(len(summaries), 1)
        self.assertIn("日线", summaries[0])
        self.assertIn("MACD零轴上", summaries[0])
        self.assertIn("BOLL", summaries[0])
