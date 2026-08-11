"""Behavioral tests for public-news collection (all network access is faked)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import unittest

import pandas as pd

from naked_k_news import collect_news
from tests.conftest import FakeResponse


NOW = pd.Timestamp("2026-07-20T12:00:00+08:00")
EMPTY_RSS = b"<?xml version='1.0'?><rss><channel></channel></rss>"


def empty_get(*args: object, **kwargs: object) -> FakeResponse:
    return FakeResponse(content=EMPTY_RSS)


def search_with(news: list[dict[str, Any]]):
    class FakeSearch:
        def __init__(self, query: str, **kwargs: object) -> None:
            self.query = query
            self.kwargs = kwargs
            self.news = news

    return FakeSearch


class CollectNewsNormalizationTests(unittest.TestCase):
    def test_normalizes_both_supported_yahoo_shapes(self) -> None:
        class FakeSearch:
            def __init__(self, query: str, **kwargs: object) -> None:
                self.query = query
                self.news = [
                    {
                        "title": "Company wins contract",
                        "publisher": "Wire A",
                        "providerPublishTime": 1784516400,
                        "link": "https://example.com/a?utm_source=yahoo",
                    },
                    {
                        "content": {
                            "title": "Company raises guidance",
                            "summary": "Management raised full-year guidance.",
                            "pubDate": "2026-07-19T08:00:00Z",
                            "provider": {"displayName": "Wire B"},
                            "canonicalUrl": {"url": "https://example.com/b"},
                        }
                    },
                ]

        result = collect_news(
            "测试公司", "TEST", now=NOW, search_factory=FakeSearch, get=empty_get
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["freshness"], "fresh")
        self.assertEqual([item["id"] for item in result["items"]], ["news-01", "news-02"])
        self.assertEqual(
            {key for item in result["items"] for key in item},
            {
                "id",
                "title",
                "publisher",
                "published_at",
                "url",
                "summary",
                "source_provider",
                "freshness",
            },
        )
        for item in result["items"]:
            self.assertEqual(item["source_provider"], "yahoo_finance")
            self.assertIsNotNone(datetime.fromisoformat(item["published_at"]).tzinfo)
        self.assertNotIn("utm_source", result["items"][0]["url"])

    def test_google_rss_uses_endpoint_and_query_params(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []
        rss = b"""<rss><channel><item>
            <title>Google headline</title>
            <link>https://example.com/google?utm_medium=rss&amp;z=2&amp;a=1</link>
            <pubDate>Sun, 19 Jul 2026 08:00:00 GMT</pubDate>
            <source>RSS Wire</source>
            <description>&lt;b&gt;HTML summary&lt;/b&gt;</description>
        </item></channel></rss>"""

        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            calls.append((url, kwargs))
            return FakeResponse(content=rss)

        result = collect_news(
            "测试公司", "TEST", now=NOW, search_factory=search_with([]), get=fake_get
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(calls[0][0], "https://news.google.com/rss/search")
        self.assertIn("params", calls[0][1])
        self.assertIn("测试公司", str(calls[0][1]["params"]))
        item = result["items"][0]
        self.assertEqual(item["source_provider"], "google_news_rss")
        self.assertEqual(item["summary"], "HTML summary")
        self.assertEqual(item["url"], "https://example.com/google?a=1&z=2")

    def test_yahoo_error_keeps_google_results(self) -> None:
        def broken_search(*args: object, **kwargs: object) -> object:
            raise RuntimeError("yahoo unavailable")

        rss = b"""<rss><channel><item><title>Google headline</title>
            <link>https://example.com/google</link>
            <pubDate>Sun, 19 Jul 2026 08:00:00 GMT</pubDate>
            <source>RSS Wire</source><description>summary</description>
        </item></channel></rss>"""
        result = collect_news(
            "测试公司", "TEST", now=NOW, search_factory=broken_search,
            get=lambda *args, **kwargs: FakeResponse(content=rss),
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["items"]), 1)
        self.assertIn("RuntimeError", result["source_errors"])

    def test_google_error_keeps_yahoo_results(self) -> None:
        result = collect_news(
            "测试公司", "TEST", now=NOW,
            search_factory=search_with([{
                "title": "Yahoo headline", "publisher": "Wire",
                "providerPublishTime": 1784516400, "link": "https://example.com/yahoo",
            }]),
            get=lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("google down")),
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["items"]), 1)
        self.assertIn("ConnectionError", result["source_errors"])

    def test_both_source_errors_return_unavailable(self) -> None:
        result = collect_news(
            "测试公司", "TEST", now=NOW,
            search_factory=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError()),
            get=lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError()),
        )

        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["freshness"], "unavailable")
        self.assertEqual(result["items"], [])
        self.assertIn("RuntimeError", result["source_errors"])
        self.assertIn("ConnectionError", result["source_errors"])


class CollectNewsFreshnessTests(unittest.TestCase):
    def test_deduplicates_normalized_titles_and_canonical_urls(self) -> None:
        result = collect_news(
            "测试公司", "TEST", now=NOW, get=empty_get,
            search_factory=search_with([
                {"title": "Alpha Inc beats estimates", "publisher": "A", "providerPublishTime": 1784516400, "link": "https://one.example/a?utm_source=x"},
                {"title": "Alpha Inc beats estimates!", "publisher": "B", "providerPublishTime": 1784512800, "link": "https://two.example/b"},
                {"title": "Different title", "publisher": "C", "providerPublishTime": 1784509200, "link": "HTTPS://ONE.EXAMPLE/a?gclid=abc"},
            ]),
        )

        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["id"], "news-01")

    def test_fresh_items_win_over_fallback_items(self) -> None:
        result = collect_news(
            "测试公司", "TEST", now=NOW, get=empty_get,
            search_factory=search_with([
                {"title": "Fresh", "publisher": "A", "providerPublishTime": 1784516400, "link": "https://example.com/fresh"},
                {"title": "Older", "publisher": "B", "providerPublishTime": int(pd.Timestamp("2026-07-05T00:00:00Z").timestamp()), "link": "https://example.com/older"},
            ]),
        )

        self.assertEqual(result["window_days"], 7)
        self.assertEqual(result["freshness"], "fresh")
        self.assertEqual([item["title"] for item in result["items"]], ["Fresh"])

    def test_uses_low_freshness_fallback_when_no_fresh_items_exist(self) -> None:
        result = collect_news(
            "测试公司", "TEST", now=NOW, get=empty_get,
            search_factory=search_with([{
                "title": "Older", "publisher": "B",
                "providerPublishTime": int(pd.Timestamp("2026-07-05T00:00:00Z").timestamp()),
                "link": "https://example.com/older",
            }]),
        )

        self.assertEqual(result["window_days"], 30)
        self.assertEqual(result["freshness"], "low_freshness")
        self.assertEqual(result["items"][0]["freshness"], "low_freshness")

    def test_excludes_old_and_future_dated_items(self) -> None:
        result = collect_news(
            "测试公司", "TEST", now=NOW, get=empty_get,
            search_factory=search_with([
                {"title": "Old", "publisher": "A", "providerPublishTime": int(pd.Timestamp("2026-06-01T00:00:00Z").timestamp()), "link": "https://example.com/old"},
                {"title": "Future", "publisher": "A", "providerPublishTime": int(pd.Timestamp("2026-07-21T00:00:00Z").timestamp()), "link": "https://example.com/future"},
            ]),
        )

        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["freshness"], "insufficient")
        self.assertEqual(result["items"], [])

    def test_sorts_newest_first_limits_and_clips_public_fields(self) -> None:
        long_title = "T" * 350
        long_summary = "S" * 550
        long_url = "https://example.com/" + ("x" * 600)
        result = collect_news(
            "测试公司", "TEST", now=NOW, max_items=2, get=empty_get,
            search_factory=search_with([
                {"title": "Oldest", "publisher": "A", "providerPublishTime": 1784426400, "link": "https://example.com/oldest"},
                {"title": long_title, "publisher": "B", "providerPublishTime": 1784516400, "link": long_url, "summary": long_summary},
                {"title": "Middle", "publisher": "C", "providerPublishTime": 1784509200, "link": "https://example.com/middle"},
            ]),
        )

        self.assertEqual([item["title"] for item in result["items"]][1], "Middle")
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(len(result["items"][0]["title"]), 300)
        self.assertEqual(len(result["items"][0]["summary"]), 500)
        self.assertEqual(len(result["items"][0]["url"]), 500)

    def test_rejects_invalid_windows_before_network_calls(self) -> None:
        calls: list[str] = []

        def should_not_run(*args: object, **kwargs: object) -> object:
            calls.append("called")
            raise AssertionError("network should not run")

        for kwargs in (
            {"lookback_days": 0},
            {"lookback_days": -1},
            {"fallback_days": 6},
            {"max_items": 0},
            {"max_items": -1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                collect_news("测试公司", "TEST", search_factory=should_not_run, get=should_not_run, **kwargs)
        self.assertEqual(calls, [])
