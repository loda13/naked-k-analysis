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
        self.assertEqual(westock_wrapper.convert_ticker("000660.KS"), "kr000660")
        self.assertEqual(westock_wrapper.convert_ticker("NVDA"), "usNVDA")
        self.assertEqual(westock_wrapper.convert_ticker("688256.SS"), "sh688256")
        self.assertEqual(westock_wrapper.convert_ticker("430139.BJ"), "bj430139")
        self.assertEqual(westock_wrapper.convert_ticker("9992.HK"), "hk09992")

    def test_convert_ticker_needs_no_hand_maintained_lookup_table(self):
        """The old TICKER_MAP's 11 entries all agreed with the rule below it.

        Keeping it implied new symbols had to be registered first, which was
        never true. Asserted so it does not grow back.
        """
        self.assertFalse(hasattr(westock_wrapper, "TICKER_MAP"))

    def test_convert_ticker_is_case_and_whitespace_insensitive(self):
        self.assertEqual(westock_wrapper.convert_ticker(" 0700.hk "), "hk00700")
        self.assertEqual(westock_wrapper.convert_ticker("nvda"), "usNVDA")

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

    def test_fetch_tencent_kline_reads_qfq_key_for_a_shares(self):
        """A-shares answer a qfq request under ``qfqday``, not ``day``.

        Verified live: sh688256 returns ``day`` first_close=1009.450 but
        ``qfqday`` first_close=676.477 over the same 90 bars. Reading the wrong
        key yields un-adjusted prices with synthetic ex-rights gaps.
        """
        payload = {
            "code": 0,
            "data": {
                "sh688256": {
                    "qfqday": [
                        ["2026-05-29", "670.000", "676.477", "680.000", "665.000", "1000.000", {}],
                    ]
                }
            },
        }

        response = SimpleNamespace(text=json.dumps(payload), raise_for_status=lambda: None)
        with patch("requests.get", return_value=response):
            df = westock_wrapper.fetch_tencent_kline("688256.SS", period="day", limit=1)

        self.assertFalse(df.empty)
        self.assertEqual(float(df.iloc[-1]["Close"]), 676.477)
        self.assertEqual(df.attrs["adjustment"], "qfq")

    def test_fetch_tencent_kline_prefers_qfq_key_over_unadjusted_day(self):
        """When both keys are present the adjusted series must win.

        Defensive only: probed live across 8 symbols x day/week/month and no
        response carried both keys, so this is not covering a real regression.
        Pinned anyway because the basis label is derived from which key answered.
        """
        payload = {
            "code": 0,
            "data": {
                "sh600519": {
                    "day": [
                        ["2026-05-29", "1420.000", "1420.000", "1430.000", "1410.000", "500.000", {}],
                    ],
                    "qfqday": [
                        ["2026-05-29", "1391.976", "1391.976", "1400.000", "1385.000", "500.000", {}],
                    ],
                }
            },
        }

        response = SimpleNamespace(text=json.dumps(payload), raise_for_status=lambda: None)
        with patch("requests.get", return_value=response):
            df = westock_wrapper.fetch_tencent_kline("600519.SS", period="day", limit=1)

        self.assertEqual(float(df.iloc[-1]["Close"]), 1391.976)
        self.assertEqual(df.attrs["adjustment"], "qfq")

    def test_fetch_tencent_kline_marks_hk_day_key_as_split_only(self):
        """HK answers under plain ``day`` and that series is dividend-raw.

        Verified live twice over: hk00700 returns byte-identical rows for
        ``''``/``qfq``/``hfq`` (the mode is ignored), and across 489 bars spanning
        two dividends it tracks Yahoo's un-adjusted close to a 0.0027% mean while
        diverging from adjclose by 1.33% on 430 bars. So the label follows what
        the data *is*, not what the request asked for.
        """
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
        with patch("requests.get", return_value=response):
            df = westock_wrapper.fetch_tencent_kline("0700.HK", period="day", limit=1)

        self.assertEqual(df.attrs["adjustment"], "split_only")

    def test_hk_tencent_and_yahoo_share_one_basis_so_no_conflict_is_raised(self):
        """The common HK fallback (tencent -> yahoo) must not warn spuriously.

        Both are split_only, so a mid-run switch is safe and must stay quiet;
        otherwise the warning fires on every ordinary run and gets ignored.
        """
        self.assertTrue(
            westock_wrapper.adjustments_comparable("split_only", "split_only")
        )

    def test_fetch_yahoo_chart_reports_split_only_adjustment(self):
        """Yahoo's quote OHLC is split-adjusted but not dividend-adjusted."""
        payload = {
            "chart": {
                "result": [
                    {
                        "timestamp": [1780272000],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [432.4],
                                    "high": [442.0],
                                    "low": [430.0],
                                    "close": [438.4],
                                    "volume": [21445870],
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

        self.assertEqual(df.attrs["adjustment"], "split_only")

    def test_download_propagates_adjustment_from_the_winning_source(self):
        empty_df = pd.DataFrame()
        tencent_df = pd.DataFrame(
            {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [100.0]},
            index=pd.to_datetime(["2026-06-01"]),
        )
        tencent_df.attrs["adjustment"] = "qfq"

        with patch.object(westock_wrapper, "fetch_kline", return_value=empty_df), patch.object(
            westock_wrapper, "fetch_tencent_kline", return_value=tencent_df
        ), patch.object(westock_wrapper, "fetch_yfinance"):
            result = westock_wrapper.download("0700.HK", period="1y", interval="1d")

        self.assertEqual(result.attrs["source"], "tencent")
        self.assertEqual(result.attrs["adjustment"], "qfq")

    def test_download_labels_unknown_adjustment_when_source_is_silent(self):
        """A source that never set the field must not inherit a stale label."""
        empty_df = pd.DataFrame()
        bare_df = pd.DataFrame(
            {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [100.0]},
            index=pd.to_datetime(["2026-06-01"]),
        )

        with patch.object(westock_wrapper, "fetch_kline", return_value=empty_df), patch.object(
            westock_wrapper, "fetch_tencent_kline", return_value=empty_df
        ), patch.object(westock_wrapper, "fetch_yahoo_chart", return_value=empty_df), patch.object(
            westock_wrapper, "fetch_yfinance", return_value=bare_df
        ):
            result = westock_wrapper.download("NVDA", period="1y", interval="1d")

        self.assertEqual(result.attrs["adjustment"], "unknown")

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

    def test_fetch_yfinance_reports_split_only_adjustment(self):
        """``auto_adjust=False`` keeps Yahoo's split-adjusted, dividend-raw OHLC."""
        frame = pd.DataFrame(
            {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [100.0]},
            index=pd.to_datetime(["2026-06-01"]),
        )

        with patch("yfinance.download", return_value=frame) as download:
            result = westock_wrapper.fetch_yfinance("NVDA", period="1y", interval="1d")

        self.assertEqual(result.attrs["adjustment"], "split_only")
        self.assertFalse(download.call_args.kwargs["auto_adjust"])


class TencentRowLimitTests(unittest.TestCase):
    """The limit sent to Tencent was computed in trading days for every interval.

    Verified live: the endpoint returns rows for limit<=2000 and an empty payload
    for limit>=2001 (binary-searched on sh600519 month). A 10y monthly request
    computed 10*250=2500, tripped that cap, and silently fell through to Yahoo —
    which is how a single ticker ended up with qfq daily/weekly and split_only
    monthly in one run.
    """

    def _limit_for(self, interval, period):
        captured = {}

        def fake_tencent(ticker, ws_period, limit):
            captured['limit'] = limit
            captured['ws_period'] = ws_period
            return pd.DataFrame()

        with patch.object(westock_wrapper, "fetch_kline", return_value=pd.DataFrame()), patch.object(
            westock_wrapper, "fetch_tencent_kline", side_effect=fake_tencent
        ), patch.object(westock_wrapper, "fetch_yahoo_chart", return_value=pd.DataFrame()), patch.object(
            westock_wrapper, "fetch_yfinance", return_value=pd.DataFrame()
        ):
            westock_wrapper.download("688256.SS", period=period, interval=interval)

        return captured

    def test_monthly_limit_is_counted_in_months_not_trading_days(self):
        captured = self._limit_for("1mo", "10y")

        self.assertEqual(captured['ws_period'], 'month')
        self.assertLessEqual(captured['limit'], westock_wrapper.TENCENT_MAX_ROWS)
        # 10 years of monthly bars is ~120, not 2500.
        self.assertGreaterEqual(captured['limit'], 120)
        self.assertLess(captured['limit'], 300)

    def test_weekly_limit_is_counted_in_weeks_not_trading_days(self):
        captured = self._limit_for("1wk", "5y")

        self.assertEqual(captured['ws_period'], 'week')
        # 5 years of weekly bars is ~260, not 1250.
        self.assertGreaterEqual(captured['limit'], 260)
        self.assertLess(captured['limit'], 600)

    def test_daily_limit_still_uses_trading_days(self):
        captured = self._limit_for("1d", "18mo")

        self.assertEqual(captured['ws_period'], 'day')
        self.assertGreaterEqual(captured['limit'], 378)

    def test_every_request_is_clamped_below_the_live_cap(self):
        """limit>=2001 returns an empty payload, so never ask for more."""
        for interval, period in (
            ("1d", "max"),
            ("1d", "20y"),
            ("1wk", "max"),
            ("1mo", "max"),
            ("1h", "5y"),
        ):
            with self.subTest(interval=interval, period=period):
                captured = self._limit_for(interval, period)
                self.assertLessEqual(captured['limit'], westock_wrapper.TENCENT_MAX_ROWS)
                self.assertGreater(captured['limit'], 0)

    def test_cap_matches_the_live_boundary(self):
        self.assertEqual(westock_wrapper.TENCENT_MAX_ROWS, 2000)


class AdjustmentConventionTests(unittest.TestCase):
    """The fallback chain may hand different price bases to different timeframes."""

    def test_known_adjustments_declare_split_and_dividend_handling(self):
        self.assertEqual(
            westock_wrapper.ADJUSTMENT_PROPERTIES["raw"], (False, False)
        )
        self.assertEqual(
            westock_wrapper.ADJUSTMENT_PROPERTIES["split_only"], (True, False)
        )
        self.assertEqual(westock_wrapper.ADJUSTMENT_PROPERTIES["qfq"], (True, True))
        self.assertEqual(westock_wrapper.ADJUSTMENT_PROPERTIES["hfq"], (True, True))

    def test_same_label_is_comparable(self):
        self.assertTrue(westock_wrapper.adjustments_comparable("qfq", "qfq"))

    def test_differing_labels_are_not_comparable(self):
        """qfq and hfq both adjust, but anchor the scale at opposite ends."""
        self.assertFalse(westock_wrapper.adjustments_comparable("qfq", "hfq"))
        self.assertFalse(westock_wrapper.adjustments_comparable("qfq", "split_only"))
        self.assertFalse(westock_wrapper.adjustments_comparable("raw", "split_only"))

    def test_unknown_is_never_comparable_even_with_itself(self):
        """Two silent sources may still disagree; absence of a label is not a match."""
        self.assertFalse(westock_wrapper.adjustments_comparable("unknown", "unknown"))
        self.assertFalse(westock_wrapper.adjustments_comparable("unknown", "qfq"))

    def test_describe_adjustment_is_human_readable_for_the_report(self):
        self.assertIn("未复权", westock_wrapper.describe_adjustment("raw"))
        self.assertIn("前复权", westock_wrapper.describe_adjustment("qfq"))
        self.assertIn("后复权", westock_wrapper.describe_adjustment("hfq"))
        self.assertIn("拆股", westock_wrapper.describe_adjustment("split_only"))
        self.assertIn("未知", westock_wrapper.describe_adjustment("unknown"))

    def test_describe_adjustment_tolerates_unrecognized_label(self):
        self.assertIn("未知", westock_wrapper.describe_adjustment("something-else"))

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
