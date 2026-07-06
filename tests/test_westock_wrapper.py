import os
import inspect
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

import westock_wrapper


class WestockWrapperTests(unittest.TestCase):
    def test_wrapper_no_longer_imports_legacy_stock_analysis_package(self):
        source = inspect.getsource(westock_wrapper)

        self.assertNotIn("stock_analysis", source)

    def test_convert_ticker_normalizes_common_markets_locally(self):
        self.assertEqual(westock_wrapper.convert_ticker("0700.HK"), "hk00700")
        self.assertEqual(westock_wrapper.convert_ticker("600703.SS"), "sh600703")
        self.assertEqual(westock_wrapper.convert_ticker("001391.SZ"), "sz001391")
        self.assertEqual(westock_wrapper.convert_ticker("NVDA"), "usNVDA")

    def test_uses_env_script_path(self):
        with patch.dict(os.environ, {"WESTOCK_DATA_SCRIPT": "/tmp/westock.js"}):
            cmd = westock_wrapper.build_westock_command("NVDA", "day", 10)

        self.assertEqual(cmd[1], "/tmp/westock.js")
        self.assertEqual(cmd[-3:], ["usNVDA", "day", "10"])

    def test_download_falls_back_to_yfinance_when_westock_empty(self):
        fallback_df = SimpleNamespace(empty=False)
        empty_df = SimpleNamespace(empty=True)

        with patch.object(westock_wrapper, "fetch_kline", return_value=empty_df), patch.object(
            westock_wrapper, "fetch_tencent_kline", return_value=empty_df
        ), patch.object(westock_wrapper, "fetch_yahoo_chart", return_value=empty_df), patch.object(
            westock_wrapper, "fetch_yfinance", return_value=fallback_df
        ) as fallback:
            result = westock_wrapper.download("NVDA", period="1y", interval="1d")

        self.assertIs(result, fallback_df)
        fallback.assert_called_once()

    def test_download_uses_yahoo_chart_before_yfinance_when_tencent_empty(self):
        empty_df = pd.DataFrame()
        yahoo_df = pd.DataFrame(
            {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [100.0]},
            index=pd.to_datetime(["2026-06-01"]),
        )

        with patch.object(westock_wrapper, "fetch_kline", return_value=empty_df), patch.object(
            westock_wrapper, "fetch_tencent_kline", return_value=empty_df
        ), patch.object(westock_wrapper, "fetch_yahoo_chart", return_value=yahoo_df), patch.object(
            westock_wrapper, "fetch_yfinance"
        ) as fallback:
            result = westock_wrapper.download("NVDA", period="1y", interval="1d")

        self.assertIs(result, yahoo_df)
        fallback.assert_not_called()
        self.assertEqual(result.attrs["source"], "yahoo_chart")
        self.assertEqual(result.attrs["rows"], 1)
        self.assertEqual(result.attrs["latest"], "2026-06-01")

    def test_download_skips_tencent_kline_for_us_ticker(self):
        empty_df = pd.DataFrame()
        yahoo_df = pd.DataFrame(
            {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [100.0]},
            index=pd.to_datetime(["2026-06-01"]),
        )

        with patch.object(westock_wrapper, "fetch_kline", return_value=empty_df), patch.object(
            westock_wrapper, "fetch_tencent_kline"
        ) as tencent, patch.object(westock_wrapper, "fetch_yahoo_chart", return_value=yahoo_df):
            result = westock_wrapper.download("NVDA", period="1y", interval="1d")

        self.assertIs(result, yahoo_df)
        tencent.assert_not_called()

    def test_fetch_tencent_kline_parses_hk_daily_rows(self):
        payload = {
            "code": 0,
            "data": {
                "hk00700": {
                    "day": [
                        ["2026-05-29", "430.000", "438.000", "439.000", "429.000", "12345.000", {}],
                        ["2026-06-01", "438.000", "440.000", "445.000", "437.000", "23456.000", {}],
                    ]
                }
            },
        }

        response = SimpleNamespace(text=json.dumps(payload), raise_for_status=lambda: None)
        with patch("requests.get", return_value=response):
            df = westock_wrapper.fetch_tencent_kline("0700.HK", period="day", limit=2)

        self.assertEqual(list(df.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertEqual(df.index[0].strftime("%Y-%m-%d"), "2026-05-29")
        self.assertEqual(float(df.iloc[-1]["Close"]), 440.0)
        self.assertEqual(float(df.iloc[-1]["Volume"]), 23456.0)

    def test_fetch_tencent_kline_uses_backup_domain_when_primary_fails(self):
        payload = {
            "code": 0,
            "data": {
                "hk00700": {
                    "day": [
                        ["2026-06-01", "438.000", "440.000", "445.000", "437.000", "23456.000", {}],
                    ]
                }
            },
        }

        response = SimpleNamespace(text=json.dumps(payload), raise_for_status=lambda: None)
        with patch("requests.get", side_effect=[RuntimeError("dns"), response]) as get:
            df = westock_wrapper.fetch_tencent_kline("0700.HK", period="day", limit=1)

        self.assertFalse(df.empty)
        self.assertEqual(get.call_count, 2)

    def test_fetch_yahoo_chart_parses_daily_rows(self):
        payload = {
            "chart": {
                "result": [
                    {
                        "timestamp": [1780272000, 1780358400],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [432.4, 438.0],
                                    "high": [442.0, 445.0],
                                    "low": [430.0, 437.0],
                                    "close": [438.4, 440.0],
                                    "volume": [21445870, 23456000],
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }

        response = SimpleNamespace(json=lambda: payload, raise_for_status=lambda: None)
        with patch("requests.get", return_value=response):
            df = westock_wrapper.fetch_yahoo_chart("0700.HK", period="5d", interval="1d")

        self.assertEqual(list(df.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertEqual(float(df.iloc[-1]["Close"]), 440.0)
        self.assertEqual(float(df.iloc[-1]["Volume"]), 23456000.0)

    def test_fetch_kline_skips_missing_default_westock_script(self):
        with patch.dict(os.environ, {}, clear=True), patch("os.path.exists", return_value=False), patch(
            "subprocess.run"
        ) as run:
            df = westock_wrapper.fetch_kline("0700.HK", period="day", limit=10)

        self.assertTrue(df.empty)
        run.assert_not_called()

    def test_download_uses_tencent_before_yfinance_when_westock_empty(self):
        empty_df = pd.DataFrame()
        tencent_df = pd.DataFrame(
            {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [100.0]},
            index=pd.to_datetime(["2026-06-01"]),
        )

        with patch.object(westock_wrapper, "fetch_kline", return_value=empty_df), patch.object(
            westock_wrapper, "fetch_tencent_kline", return_value=tencent_df
        ), patch.object(westock_wrapper, "fetch_yfinance") as fallback:
            result = westock_wrapper.download("0700.HK", period="1y", interval="1d")

        self.assertIs(result, tencent_df)
        self.assertEqual(result.attrs["source"], "tencent")
        fallback.assert_not_called()

    def test_download_uses_tencent_hourly_for_hk_1h(self):
        empty_df = pd.DataFrame()
        hourly_df = pd.DataFrame(
            {"Open": [1.0] * 180, "High": [2.0] * 180, "Low": [0.5] * 180, "Close": [1.5] * 180, "Volume": [100.0] * 180},
            index=pd.date_range("2026-05-01 10:00", periods=180, freq="h"),
        )

        with patch.object(westock_wrapper, "fetch_kline", return_value=empty_df), patch.object(
            westock_wrapper, "fetch_tencent_kline", return_value=hourly_df
        ) as tencent, patch.object(westock_wrapper, "fetch_yahoo_chart") as yahoo:
            result = westock_wrapper.download("0700.HK", period="60d", interval="1h")

        self.assertIs(result, hourly_df)
        self.assertEqual(tencent.call_args.args[1], "m60")
        yahoo.assert_not_called()

    def test_download_falls_back_to_yahoo_when_tencent_hourly_is_too_short(self):
        empty_df = pd.DataFrame()
        tiny_tencent_df = pd.DataFrame(
            {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [100.0]},
            index=pd.to_datetime(["2026-06-01 10:00"]),
        )
        yahoo_df = pd.DataFrame(
            {"Open": [1.0] * 180, "High": [2.0] * 180, "Low": [0.5] * 180, "Close": [1.5] * 180, "Volume": [100.0] * 180},
            index=pd.date_range("2026-05-01 10:00", periods=180, freq="h"),
        )

        with patch.object(westock_wrapper, "fetch_kline", return_value=empty_df), patch.object(
            westock_wrapper, "fetch_tencent_kline", return_value=tiny_tencent_df
        ), patch.object(westock_wrapper, "fetch_yahoo_chart", return_value=yahoo_df) as yahoo:
            result = westock_wrapper.download("0700.HK", period="60d", interval="1h")

        self.assertIs(result, yahoo_df)
        yahoo.assert_called_once()
