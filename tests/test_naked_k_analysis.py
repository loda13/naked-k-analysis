import unittest
from unittest.mock import patch

import pandas as pd

import naked_k_analysis


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
