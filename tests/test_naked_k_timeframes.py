import unittest

import pandas as pd

import naked_k_timeframes


class NakedKTimeframeTests(unittest.TestCase):
    def _frame(self, closes):
        rows = []
        for close in closes:
            rows.append(
                {
                    "Open": close - 1,
                    "High": close + 2,
                    "Low": close - 2,
                    "Close": close,
                    "Volume": 1000,
                }
            )
        return pd.DataFrame(rows, index=pd.date_range("2025-01-01", periods=len(rows), freq="D"))

    def test_builds_direction_structure_opportunity_trigger_framework(self):
        monthly = self._frame([10, 11, 12, 13, 14, 15])
        weekly = self._frame([14, 15, 16, 17, 18, 19])
        daily = self._frame([18, 19, 20, 21, 22, 24])
        intraday_status = {"status": "盘中确认", "note": "最近有效1h收盘站上触发位"}

        context = naked_k_timeframes.build_timeframe_context(
            monthly=monthly,
            weekly=weekly,
            daily=daily,
            intraday_status=intraday_status,
        )

        self.assertEqual(context["alignment"], "aligned_long")
        self.assertEqual(context["macro"]["role"], "长期方向")
        self.assertEqual(context["structure"]["role"], "主要结构")
        self.assertEqual(context["opportunity"]["role"], "交易机会")
        self.assertEqual(context["trigger"]["role"], "入场触发")
        self.assertIn("大周期方向", context["framework"])
        self.assertIn("中周期结构", context["framework"])
        self.assertIn("小周期触发", context["framework"])

    def test_marks_conflict_when_daily_trigger_fights_higher_timeframes(self):
        monthly = self._frame([20, 21, 22, 23, 24, 25])
        weekly = self._frame([24, 25, 26, 27, 28, 29])
        daily = self._frame([29, 28, 27, 26, 25, 23])

        context = naked_k_timeframes.build_timeframe_context(monthly=monthly, weekly=weekly, daily=daily)

        self.assertEqual(context["alignment"], "conflict")
        self.assertIn("日线机会与高周期方向冲突", context["decision_filter"])


if __name__ == "__main__":
    unittest.main()
