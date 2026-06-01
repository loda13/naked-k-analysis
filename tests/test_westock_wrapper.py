import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import westock_wrapper


class WestockWrapperTests(unittest.TestCase):
    def test_uses_env_script_path(self):
        with patch.dict(os.environ, {"WESTOCK_DATA_SCRIPT": "/tmp/westock.js"}):
            cmd = westock_wrapper.build_westock_command("NVDA", "day", 10)

        self.assertEqual(cmd[1], "/tmp/westock.js")
        self.assertEqual(cmd[-3:], ["usNVDA", "day", "10"])

    def test_download_falls_back_to_yfinance_when_westock_empty(self):
        fallback_df = SimpleNamespace(empty=False)
        empty_df = SimpleNamespace(empty=True)

        with patch.object(westock_wrapper, "fetch_kline", return_value=empty_df), patch.object(
            westock_wrapper, "fetch_yfinance", return_value=fallback_df
        ) as fallback:
            result = westock_wrapper.download("NVDA", period="1y", interval="1d")

        self.assertIs(result, fallback_df)
        fallback.assert_called_once()
