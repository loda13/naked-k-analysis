import unittest
from contextlib import redirect_stdout
import io
import json
from unittest.mock import patch

import pandas as pd

import ma_analysis
from ma_analysis import resample_4h


class MaAnalysisTests(unittest.TestCase):
    def test_resample_4h_aggregates_hourly_ohlcv(self):
        df = pd.DataFrame(
            {
                "Open": [10, 11, 12, 13, 14, 15, 16, 17],
                "High": [11, 12, 13, 14, 15, 16, 17, 18],
                "Low": [9, 10, 11, 12, 13, 14, 15, 16],
                "Close": [10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.5, 17.5],
                "Volume": [100, 200, 300, 400, 500, 600, 700, 800],
            },
            index=pd.date_range("2026-06-01 09:00", periods=8, freq="h"),
        )

        result = resample_4h(df)

        self.assertEqual(len(result), 2)
        self.assertEqual(float(result.iloc[0]["Open"]), 10.0)
        self.assertEqual(float(result.iloc[0]["High"]), 14.0)
        self.assertEqual(float(result.iloc[0]["Low"]), 9.0)
        self.assertEqual(float(result.iloc[0]["Close"]), 13.5)
        self.assertEqual(float(result.iloc[0]["Volume"]), 1000.0)

    def test_analyze_json_skips_4h_when_hourly_data_is_insufficient(self):
        tiny_hourly = pd.DataFrame(
            {"Open": [10], "High": [11], "Low": [9], "Close": [10.5], "Volume": [100]},
            index=pd.to_datetime(["2026-06-01 09:00"]),
        )

        stream = io.StringIO()
        with patch.object(ma_analysis, "find_ath", return_value=None), patch.object(
            ma_analysis.yf, "download", return_value=tiny_hourly
        ), redirect_stdout(stream):
            ma_analysis.analyze("0700.HK", ["4h"], output_json=True)

        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["error"], "no_data")
