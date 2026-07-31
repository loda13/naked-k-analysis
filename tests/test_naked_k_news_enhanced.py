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
                patch.object(naked_k_news_enhanced, "collect_akshare_news") as akshare,
                self.assertRaises(ValueError),
            ):
                naked_k_news_enhanced.collect_news_enhanced(
                    "拼多多", "PDD", **kwargs
                )
            collect.assert_not_called()
            finnhub.assert_not_called()
            akshare.assert_not_called()

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
                naked_k_news_enhanced, "collect_akshare_news", return_value=[]
            ) as akshare,
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
        akshare.assert_called_once_with(
            "PDD", now=NOW, lookback_days=30, max_items=4, fetch=None
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

    def test_short_cjk_keywords_match_without_word_boundaries(self) -> None:
        """CJK runs without spaces, so \\b never matches a 2-3 char name."""
        for keyword, title in (
            ("小米", "小米集团回购股份"),
            ("腾讯", "腾讯控股连续2日回购"),
            ("拼多多", "拼多多旗下Temu被罚"),
        ):
            with self.subTest(keyword=keyword):
                self.assertEqual(
                    naked_k_news_enhanced._calculate_relevance_score(
                        title, "", [keyword]
                    ),
                    3,
                )

    def test_short_cjk_keywords_still_miss_unrelated_titles(self) -> None:
        self.assertEqual(
            naked_k_news_enhanced._calculate_relevance_score(
                "港股通（深）净卖出50.77亿港元", "", ["小米"]
            ),
            0,
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
            patch.object(
                naked_k_news_enhanced, "collect_akshare_news", return_value=[]
            ),
        ):
            result = naked_k_news_enhanced.collect_news_enhanced(
                "测试公司", "TEST", now=NOW, use_finnhub=False
            )

        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["items"], [])

    def test_akshare_outranks_google_but_not_finnhub(self) -> None:
        mapping = {"1810.HK": {"zh": ["小米"], "en": ["Xiaomi"]}}
        published_at = "2026-07-19T08:00:00+00:00"
        akshare_item = collection_item(
            title="小米集团回购股份",
            published_at=published_at,
            source_provider="akshare_em",
            url="https://akshare.example/xiaomi",
        )
        finnhub_item = collection_item(
            title="Xiaomi buys back shares",
            published_at=published_at,
            source_provider="finnhub",
            url="https://finnhub.example/xiaomi",
        )
        google_item = collection_item(
            title="Xiaomi in the press",
            published_at=published_at,
            source_provider="google_news_rss",
            url="https://google.example/xiaomi",
        )

        with (
            patch.object(
                naked_k_news_enhanced, "load_company_names", return_value=mapping
            ),
            patch.object(
                naked_k_news_enhanced,
                "collect_finnhub_news",
                return_value=[finnhub_item],
            ),
            patch.object(
                naked_k_news_enhanced,
                "collect_akshare_news",
                return_value=[akshare_item],
            ),
            patch.object(
                naked_k_news_enhanced,
                "collect_news",
                return_value={"items": [google_item], "source_errors": []},
            ),
        ):
            result = naked_k_news_enhanced.collect_news_enhanced(
                "小米", "1810.HK", now=NOW, max_items=3
            )

        self.assertEqual(
            [item["source_provider"] for item in result["items"]],
            ["finnhub", "akshare_em", "google_news_rss"],
        )

    def test_market_wide_flow_tables_are_filtered_from_akshare(self) -> None:
        """Flow tables list every ticker code in the body, matching the bare code."""
        mapping = {"1810.HK": {"zh": ["小米", "小米集团"], "en": ["Xiaomi"]}}
        noise_item = {
            "title": "港股通（深）净卖出50.77亿港元",
            "publisher": "证券时报网",
            "published_at": "2026-07-19T08:00:00+00:00",
            "url": "https://akshare.example/flows",
            "summary": (
                "00981 中芯国际 港股通(深) 378267.00 -137561.41 -7.74 "
                "00700 腾讯控股 港股通(深) 319273.00 56838.99 1.16 01810"
            ),
            "source_provider": "akshare_em",
        }

        with (
            patch.object(
                naked_k_news_enhanced, "load_company_names", return_value=mapping
            ),
            patch.object(
                naked_k_news_enhanced,
                "collect_akshare_news",
                return_value=[noise_item],
            ),
            patch.object(
                naked_k_news_enhanced,
                "collect_news",
                return_value={"items": [], "source_errors": []},
            ),
        ):
            result = naked_k_news_enhanced.collect_news_enhanced(
                "小米", "1810.HK", now=NOW, use_finnhub=False
            )

        self.assertEqual(result["items"], [])

    def test_flow_tables_naming_the_company_in_the_body_are_still_filtered(self) -> None:
        """Flow-table bodies carry names too, so summed body hits must not qualify."""
        mapping = {
            "0700.HK": {
                "zh": ["腾讯", "腾讯控股"],
                "en": ["Tencent"],
            }
        }
        noise_item = {
            "title": "港股通（深）净卖出50.77亿港元",
            "publisher": "证券时报网",
            "published_at": "2026-07-19T08:00:00+00:00",
            "url": "https://akshare.example/flows",
            "summary": (
                "00981 中芯国际 港股通(深) 378267.00 -137561.41 -7.74 "
                "00700 腾讯控股 港股通(深) 319273.00 56838.99 1.16"
            ),
            "source_provider": "akshare_em",
        }

        with (
            patch.object(
                naked_k_news_enhanced, "load_company_names", return_value=mapping
            ),
            patch.object(
                naked_k_news_enhanced,
                "collect_akshare_news",
                return_value=[noise_item],
            ),
            patch.object(
                naked_k_news_enhanced,
                "collect_news",
                return_value={"items": [], "source_errors": []},
            ),
        ):
            result = naked_k_news_enhanced.collect_news_enhanced(
                "腾讯", "0700.HK", now=NOW, use_finnhub=False
            )

        self.assertEqual(result["items"], [])

    def test_akshare_items_need_a_company_name_in_the_title(self) -> None:
        """A ticker that doubles as jargon (PDD) must not qualify on its own."""
        mapping = {"PDD": {"zh": ["拼多多"], "en": ["Pinduoduo"], "keywords": ["Temu"]}}
        acronym_collision = collection_item(
            title="无问芯穹发布PDD跨集群异构推理架构 单Token成本可降低37.5%",
            published_at="2026-07-19T08:00:00+00:00",
            source_provider="akshare_em",
            url="https://akshare.example/infra",
        )
        genuine = collection_item(
            title="拼多多旗下Temu被欧盟罚款2亿欧元",
            published_at="2026-07-18T08:00:00+00:00",
            source_provider="akshare_em",
            url="https://akshare.example/pdd",
        )

        with (
            patch.object(
                naked_k_news_enhanced, "load_company_names", return_value=mapping
            ),
            patch.object(
                naked_k_news_enhanced,
                "collect_akshare_news",
                return_value=[acronym_collision, genuine],
            ),
            patch.object(
                naked_k_news_enhanced,
                "collect_news",
                return_value={"items": [], "source_errors": []},
            ),
        ):
            result = naked_k_news_enhanced.collect_news_enhanced(
                "拼多多", "PDD", now=NOW, use_finnhub=False
            )

        self.assertEqual(
            [item["title"] for item in result["items"]],
            ["拼多多旗下Temu被欧盟罚款2亿欧元"],
        )

    def test_akshare_items_are_dropped_without_any_company_name(self) -> None:
        """Without a name to match on, the title gate cannot vet flow tables."""
        item = collection_item(
            title="某只股票的公告",
            published_at="2026-07-19T08:00:00+00:00",
            source_provider="akshare_em",
            url="https://akshare.example/unknown",
        )

        with (
            patch.object(naked_k_news_enhanced, "load_company_names", return_value={}),
            patch.object(
                naked_k_news_enhanced, "collect_akshare_news", return_value=[item]
            ),
            patch.object(
                naked_k_news_enhanced,
                "collect_news",
                return_value={"items": [], "source_errors": []},
            ),
        ):
            result = naked_k_news_enhanced.collect_news_enhanced(
                "", "600519.SS", now=NOW, use_finnhub=False
            )

        self.assertEqual(result["items"], [])

    def test_other_providers_keep_the_looser_summary_match(self) -> None:
        """The title gate is AkShare-specific; Google may still match on body."""
        mapping = {"1810.HK": {"zh": ["小米"], "en": ["Xiaomi"]}}
        body_match = collection_item(
            title="Handset market share shifts in Q2",
            published_at="2026-07-19T08:00:00+00:00",
            source_provider="google_news_rss",
            url="https://google.example/handsets",
        )
        body_match["summary"] = "Xiaomi gained share against its rivals."

        with (
            patch.object(
                naked_k_news_enhanced, "load_company_names", return_value=mapping
            ),
            patch.object(
                naked_k_news_enhanced,
                "collect_news",
                return_value={"items": [body_match], "source_errors": []},
            ),
        ):
            result = naked_k_news_enhanced.collect_news_enhanced(
                "小米", "1810.HK", now=NOW, use_finnhub=False, use_akshare=False
            )

        self.assertEqual(len(result["items"]), 1)

    def test_akshare_can_be_disabled(self) -> None:
        with (
            patch.object(naked_k_news_enhanced, "load_company_names", return_value={}),
            patch.object(
                naked_k_news_enhanced, "collect_akshare_news"
            ) as akshare,
            patch.object(
                naked_k_news_enhanced,
                "collect_news",
                return_value={"items": [], "source_errors": []},
            ),
        ):
            naked_k_news_enhanced.collect_news_enhanced(
                "小米",
                "1810.HK",
                now=NOW,
                use_finnhub=False,
                use_akshare=False,
            )

        akshare.assert_not_called()

    def test_akshare_failure_does_not_abort_collection(self) -> None:
        mapping = {"1810.HK": {"zh": ["小米"], "en": ["Xiaomi"]}}
        google_item = collection_item(
            title="Xiaomi ships more phones",
            published_at="2026-07-19T08:00:00+00:00",
            source_provider="google_news_rss",
            url="https://google.example/xiaomi",
        )

        def broken(*args: object, **kwargs: object) -> list[dict[str, object]]:
            raise ConnectionError("provider unavailable")

        with (
            patch.object(
                naked_k_news_enhanced, "load_company_names", return_value=mapping
            ),
            patch.object(
                naked_k_news_enhanced, "collect_akshare_news", side_effect=broken
            ),
            patch.object(
                naked_k_news_enhanced,
                "collect_news",
                return_value={"items": [google_item], "source_errors": []},
            ),
        ):
            result = naked_k_news_enhanced.collect_news_enhanced(
                "小米", "1810.HK", now=NOW, use_finnhub=False
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            [item["source_provider"] for item in result["items"]],
            ["google_news_rss"],
        )
        self.assertIn("ConnectionError", result["source_errors"])


if __name__ == "__main__":
    unittest.main()
