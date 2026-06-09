import unittest
from unittest.mock import patch

import pandas as pd

import naked_k_analysis
from stock_analysis.naked_k import analyze_naked_k


class NakedKAnalysisDataTests(unittest.TestCase):
    def test_fetch_data_uses_shared_download_wrapper(self):
        frame = pd.DataFrame(
            {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [100.0]},
            index=pd.to_datetime(["2026-06-01"]),
        )

        with patch.object(naked_k_analysis.yf, "download", return_value=frame) as download:
            result = naked_k_analysis.fetch_data("0700.HK", days=30, interval="1d")

        self.assertIs(result, frame)
        download.assert_called_once()

    def test_analyze_one_returns_data_source_audit(self):
        frame = pd.DataFrame(
            {
                "Open": [10 + i * 0.1 for i in range(80)],
                "High": [10.5 + i * 0.1 for i in range(80)],
                "Low": [9.5 + i * 0.1 for i in range(80)],
                "Close": [10.2 + i * 0.1 for i in range(80)],
                "Volume": [1000 + i for i in range(80)],
            },
            index=pd.date_range("2026-01-01", periods=80, freq="D"),
        )
        frame.attrs.update({"source": "yahoo_chart", "rows": 80, "latest": "2026-03-21", "interval": "1d"})

        with patch.object(naked_k_analysis, "fetch_data", return_value=frame):
            result = naked_k_analysis.analyze_one("NVDA", as_json=True)

        self.assertEqual(result["data_source"]["source"], "yahoo_chart")
        self.assertEqual(result["data_source"]["rows"], 80)

    def test_analyze_naked_k_calculates_risk_reward_from_nearest_levels(self):
        payload = {
            "price": 100.0,
            "score": 2.0,
            "supports": [{"price": 92.0}, {"price": 80.0}],
            "resistances": [{"price": 116.0}, {"price": 130.0}],
            "reasons": ["实体支撑反弹"],
            "data_source": {"source": "fixture", "rows": 120, "latest": "2026-06-01"},
        }

        with patch.object(naked_k_analysis, "analyze_one", return_value=payload):
            snapshot = analyze_naked_k("NVDA")

        self.assertEqual(snapshot.invalidation, 92.0)
        self.assertEqual(snapshot.risk_reward, 2.0)
