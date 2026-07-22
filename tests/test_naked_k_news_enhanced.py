"""Behavioral tests for the enhanced multi-source news collector."""

from __future__ import annotations

from unittest.mock import patch
import unittest

import pandas as pd

import naked_k_news_enhanced


NOW = pd.Timestamp("2026-07-20T12:00:00+08:00")


def collection_item(
    *,
    title: str,
    published_at: str,
    source_provider: str,
    url: str,
) -> dict[str, object]:
    return {
        "title": title,
        "publisher": "Test Wire",
        "published_at": published_at,
        "url": url,
        "summary": title,
        "source_provider": source_provider,
    }


class EnhancedNewsCollectionTests(unittest.TestCase):
    def test_rejects_invalid_limits_before_calling_any_provider(self) -> None:
        for kwargs in (
            {"lookback_days": 0},
            {"fallback_days": 6, "lookback_days": 7},
            {"max_items": 0},
        ):
            with (
                self.subTest(kwargs=kwargs),
                patch.object(naked_k_news_enhanced, "collect_news") as collect,
                patch.object(naked_k_news_enhanced, "collect_finnhub_news") as finnhub,
                self.assertRaises(ValueError),
            ):
                naked_k_news_enhanced.collect_news_enhanced(
                    "拼多多", "PDD", **kwargs
                )
            collect.assert_not_called()
            finnhub.assert_not_called()

    def test_quality_ranking_survives_deduplication_and_uses_supplied_clock(self) -> None:
        mapping = {
            "PDD": {
                "en": ["Pinduoduo"],
                "zh": ["拼多多"],
                "keywords": ["Temu"],
            }
        }
        finnhub_item = collection_item(
            title="PDD expands Temu operations",
            published_at="2026-07-18T08:00:00+00:00",
            source_provider="finnhub",
            url="https://finnhub.example/pdd",
        )
        newer_yahoo_item = collection_item(
            title="PDD market update",
            published_at="2026-07-19T08:00:00+00:00",
            source_provider="yahoo_finance",
            url="https://yahoo.example/pdd",
        )
        base_result = {
            "items": [newer_yahoo_item],
            "source_errors": [],
        }

        with (
            patch.object(naked_k_news_enhanced, "load_company_names", return_value=mapping),
            patch.object(
                naked_k_news_enhanced,
                "collect_finnhub_news",
                return_value=[finnhub_item],
            ) as finnhub,
            patch.object(
                naked_k_news_enhanced,
                "collect_news",
                return_value=base_result,
            ) as collect,
        ):
            result = naked_k_news_enhanced.collect_news_enhanced(
                "拼多多", "PDD", now=NOW, max_items=2
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["as_of"], NOW.isoformat())
        self.assertEqual(
            [item["source_provider"] for item in result["items"]],
            ["finnhub", "yahoo_finance"],
        )
        self.assertEqual([item["id"] for item in result["items"]], ["news-01", "news-02"])
        finnhub.assert_called_once_with(
            "PDD", now=NOW, lookback_days=30, max_items=4, get=None
        )
        self.assertEqual(collect.call_count, 3)
        self.assertEqual(
            [call.kwargs["ticker"] for call in collect.call_args_list],
            ["Pinduoduo PDD", "拼多多 PDD", "Pinduoduo Temu"],
        )

    def test_short_keywords_use_word_boundaries(self) -> None:
        keywords = ["mi"]

        self.assertEqual(
            naked_k_news_enhanced._calculate_relevance_score(
                "Xiaomi ships one million cars", "", keywords
            ),
            0,
        )
        self.assertEqual(
            naked_k_news_enhanced._calculate_relevance_score(
                "MI launches a handset", "", keywords
            ),
            3,
        )

    def test_irrelevant_search_results_are_filtered(self) -> None:
        base_result = {
            "items": [
                collection_item(
                    title="Unrelated sports result",
                    published_at="2026-07-19T08:00:00+00:00",
                    source_provider="google_news_rss",
                    url="https://example.com/sports",
                )
            ],
            "source_errors": [],
        }
        with (
            patch.object(naked_k_news_enhanced, "load_company_names", return_value={}),
            patch.object(naked_k_news_enhanced, "collect_news", return_value=base_result),
        ):
            result = naked_k_news_enhanced.collect_news_enhanced(
                "测试公司", "TEST", now=NOW, use_finnhub=False
            )

        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["items"], [])


if __name__ == "__main__":
    unittest.main()
