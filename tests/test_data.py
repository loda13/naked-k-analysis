import unittest

from stock_analysis.data import classify_market, normalize_provider_ticker, resolve_technical_timeframes


class DataLayerTests(unittest.TestCase):
    def test_classifies_common_market_tickers(self):
        self.assertEqual(classify_market("0700.HK"), "hk")
        self.assertEqual(classify_market("688256.SS"), "cn")
        self.assertEqual(classify_market("001391.SZ"), "cn")
        self.assertEqual(classify_market("NVDA"), "us")
        self.assertEqual(classify_market("hk00700"), "hk")
        self.assertEqual(classify_market("usNVDA"), "us")

    def test_normalizes_provider_tickers(self):
        self.assertEqual(normalize_provider_ticker("0700.HK"), "hk00700")
        self.assertEqual(normalize_provider_ticker("688256.SS"), "sh688256")
        self.assertEqual(normalize_provider_ticker("001391.SZ"), "sz001391")
        self.assertEqual(normalize_provider_ticker("NVDA"), "usNVDA")
        self.assertEqual(normalize_provider_ticker("hk00700"), "hk00700")

    def test_resolve_technical_timeframes_keeps_real_4h_without_proxy_warning(self):
        resolved = resolve_technical_timeframes(["4h", "daily", "weekly"])

        self.assertEqual(resolved.timeframes, ["4h", "daily", "weekly"])
        self.assertFalse(resolved.uses_daily_proxy_for_4h)
        self.assertEqual(resolved.warnings, [])
