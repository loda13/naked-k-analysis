"""Behavioral tests for the optional Finnhub news collector."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
from unittest.mock import patch
import unittest

import naked_k_news_finnhub
from tests.conftest import FakeResponse


class FinnhubNewsCollectionTests(unittest.TestCase):
    def test_supplied_clock_controls_request_date_range(self) -> None:
        self.assertIn(
            "now",
            inspect.signature(
                naked_k_news_finnhub.collect_finnhub_news
            ).parameters,
        )
        calls: list[tuple[str, dict[str, object]]] = []

        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            calls.append((url, kwargs))
            return FakeResponse([])

        now = datetime(
            2026, 7, 20, 12, tzinfo=timezone(timedelta(hours=8))
        )
        with patch.dict("os.environ", {"FINNHUB_API_KEY": "test-key"}, clear=True):
            naked_k_news_finnhub.collect_finnhub_news(
                "PDD", lookback_days=10, now=now, get=fake_get
            )

        params = calls[0][1]["params"]
        self.assertEqual(params["from"], "2026-07-10")
        self.assertEqual(params["to"], "2026-07-20")

    def test_missing_api_key_skips_network(self) -> None:
        calls: list[object] = []

        with patch.dict("os.environ", {}, clear=True):
            result = naked_k_news_finnhub.collect_finnhub_news(
                "PDD", get=lambda *args, **kwargs: calls.append((args, kwargs))
            )

        self.assertEqual(result, [])
        self.assertEqual(calls, [])

    def test_explicitly_unavailable_mapping_skips_network(self) -> None:
        calls: list[object] = []

        with patch.dict("os.environ", {"FINNHUB_API_KEY": "test-key"}, clear=True):
            result = naked_k_news_finnhub.collect_finnhub_news(
                "9992.HK", get=lambda *args, **kwargs: calls.append((args, kwargs))
            )

        self.assertEqual(result, [])
        self.assertEqual(calls, [])

    def test_maps_ticker_and_normalizes_valid_items(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []
        payload = [
            {
                "datetime": 1784426400,
                "headline": "  Tencent reports results  ",
                "source": "Newswire",
                "url": "https://example.com/tencent",
                "summary": "Quarterly results",
            },
            {"datetime": 1784426400, "headline": ""},
            {"headline": "Missing timestamp"},
            "invalid",
        ]

        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            calls.append((url, kwargs))
            return FakeResponse(payload)

        with patch.dict("os.environ", {"FINNHUB_API_KEY": "test-key"}, clear=True):
            result = naked_k_news_finnhub.collect_finnhub_news(
                "0700.HK", lookback_days=10, max_items=4, get=fake_get
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Tencent reports results")
        self.assertEqual(result[0]["source_provider"], "finnhub")
        self.assertTrue(result[0]["published_at"].endswith("+00:00"))
        self.assertEqual(calls[0][0], "https://finnhub.io/api/v1/company-news")
        self.assertEqual(calls[0][1]["params"]["symbol"], "TCEHY")
        self.assertEqual(calls[0][1]["params"]["token"], "test-key")
        self.assertEqual(calls[0][1]["timeout"], 15)

    def test_rejects_invalid_limits_before_calling_provider(self) -> None:
        for kwargs in ({"lookback_days": 0}, {"max_items": 0}):
            calls: list[object] = []
            with (
                self.subTest(kwargs=kwargs),
                patch.dict("os.environ", {"FINNHUB_API_KEY": "test-key"}, clear=True),
                self.assertRaises(ValueError),
            ):
                naked_k_news_finnhub.collect_finnhub_news(
                    "PDD",
                    get=lambda *args, **call_kwargs: calls.append((args, call_kwargs)),
                    **kwargs,
                )
            self.assertEqual(calls, [])

    def test_provider_errors_degrade_to_empty_results(self) -> None:
        with patch.dict("os.environ", {"FINNHUB_API_KEY": "test-key"}, clear=True):
            result = naked_k_news_finnhub.collect_finnhub_news(
                "PDD",
                get=lambda *args, **kwargs: (_ for _ in ()).throw(
                    ConnectionError("provider unavailable")
                ),
            )

        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
