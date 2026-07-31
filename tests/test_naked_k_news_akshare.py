"""Behavioral tests for the optional AkShare news collector."""

from __future__ import annotations

import unittest

import pandas as pd

import naked_k_news_akshare


NOW = pd.Timestamp("2026-07-31T12:00:00+08:00")

_COLUMNS = ["关键词", "新闻标题", "新闻内容", "发布时间", "文章来源", "新闻链接"]


def news_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=_COLUMNS)


def news_row(
    *,
    title: str,
    published_at: str,
    source: str = "证券时报网",
    url: str = "https://example.com/a",
    content: str = "公告正文",
) -> dict[str, object]:
    return {
        "关键词": "01810",
        "新闻标题": title,
        "新闻内容": content,
        "发布时间": published_at,
        "文章来源": source,
        "新闻链接": url,
    }


class AkshareTickerNormalizationTests(unittest.TestCase):
    def test_hk_ticker_is_zero_padded_to_five_digits(self) -> None:
        """A bare 1810 matches unrelated "1810%" headlines; 01810 does not."""
        calls: list[dict[str, object]] = []

        def fake_fetch(**kwargs: object) -> pd.DataFrame:
            calls.append(kwargs)
            return news_frame([])

        naked_k_news_akshare.collect_akshare_news(
            "1810.HK", now=NOW, fetch=fake_fetch
        )

        self.assertEqual(calls, [{"symbol": "01810"}])

    def test_mainland_and_us_tickers_keep_their_bare_code(self) -> None:
        for ticker, expected in (
            ("600519.SS", "600519"),
            ("001391.SZ", "001391"),
            ("PDD", "PDD"),
        ):
            calls: list[dict[str, object]] = []

            def fake_fetch(**kwargs: object) -> pd.DataFrame:
                calls.append(kwargs)
                return news_frame([])

            with self.subTest(ticker=ticker):
                naked_k_news_akshare.collect_akshare_news(
                    ticker, now=NOW, fetch=fake_fetch
                )
                self.assertEqual(calls, [{"symbol": expected}])


class AkshareNewsCollectionTests(unittest.TestCase):
    def test_naive_publish_time_is_read_as_beijing_time(self) -> None:
        """East Money returns naive Beijing time; treating it as UTC skews 8h."""
        frame = news_frame(
            [news_row(title="小米回购", published_at="2026-07-31 12:00:00")]
        )

        result = naked_k_news_akshare.collect_akshare_news(
            "1810.HK", now=NOW, fetch=lambda **_: frame
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["published_at"], "2026-07-31T04:00:00+00:00")

    def test_items_outside_the_lookback_window_are_dropped(self) -> None:
        frame = news_frame(
            [
                news_row(title="窗口内", published_at="2026-07-28 10:00:00"),
                news_row(title="太旧", published_at="2026-05-29 16:55:00"),
                news_row(title="未来", published_at="2026-08-05 10:00:00"),
            ]
        )

        result = naked_k_news_akshare.collect_akshare_news(
            "1810.HK", now=NOW, lookback_days=30, fetch=lambda **_: frame
        )

        self.assertEqual([item["title"] for item in result], ["窗口内"])

    def test_normalizes_fields_and_clips_long_text(self) -> None:
        frame = news_frame(
            [
                news_row(
                    title="  小米集团回购  " + "长" * 400,
                    published_at="2026-07-30 09:00:00",
                    source="证券时报网",
                    url="https://example.com/xiaomi?utm_source=spam",
                    content="正" * 900,
                )
            ]
        )

        result = naked_k_news_akshare.collect_akshare_news(
            "1810.HK", now=NOW, fetch=lambda **_: frame
        )

        item = result[0]
        self.assertTrue(item["title"].startswith("小米集团回购"))
        self.assertEqual(len(item["title"]), 300)
        self.assertEqual(len(item["summary"]), 500)
        self.assertEqual(item["publisher"], "证券时报网")
        self.assertEqual(item["source_provider"], "akshare_em")
        self.assertNotIn("utm_source", item["url"])

    def test_untitled_and_undated_rows_are_skipped(self) -> None:
        frame = news_frame(
            [
                news_row(title="   ", published_at="2026-07-30 09:00:00"),
                news_row(title="缺时间", published_at=""),
                news_row(title="有效", published_at="2026-07-30 09:00:00"),
            ]
        )

        result = naked_k_news_akshare.collect_akshare_news(
            "1810.HK", now=NOW, fetch=lambda **_: frame
        )

        self.assertEqual([item["title"] for item in result], ["有效"])

    def test_max_items_keeps_the_newest_entries(self) -> None:
        frame = news_frame(
            [
                news_row(
                    title="较旧",
                    published_at="2026-07-20 09:00:00",
                    url="https://example.com/old",
                ),
                news_row(
                    title="最新",
                    published_at="2026-07-30 09:00:00",
                    url="https://example.com/new",
                ),
            ]
        )

        result = naked_k_news_akshare.collect_akshare_news(
            "1810.HK", now=NOW, max_items=1, fetch=lambda **_: frame
        )

        self.assertEqual([item["title"] for item in result], ["最新"])

    def test_rejects_invalid_limits_before_calling_provider(self) -> None:
        for kwargs in ({"lookback_days": 0}, {"max_items": 0}):
            calls: list[object] = []
            with (
                self.subTest(kwargs=kwargs),
                self.assertRaises(ValueError),
            ):
                naked_k_news_akshare.collect_akshare_news(
                    "1810.HK",
                    now=NOW,
                    fetch=lambda **inner: calls.append(inner) or news_frame([]),
                    **kwargs,
                )
            self.assertEqual(calls, [])

    def test_provider_errors_degrade_to_empty_results(self) -> None:
        def broken_fetch(**_: object) -> pd.DataFrame:
            raise ConnectionError("provider unavailable")

        result = naked_k_news_akshare.collect_akshare_news(
            "1810.HK", now=NOW, fetch=broken_fetch
        )

        self.assertEqual(result, [])

    def test_missing_akshare_dependency_degrades_to_empty_results(self) -> None:
        """AkShare is optional; an absent import must not break the report."""
        def missing_loader() -> None:
            raise ImportError("No module named 'akshare'")

        result = naked_k_news_akshare.collect_akshare_news(
            "1810.HK", now=NOW, loader=missing_loader
        )

        self.assertEqual(result, [])

    def test_unexpected_payload_shape_degrades_to_empty_results(self) -> None:
        result = naked_k_news_akshare.collect_akshare_news(
            "1810.HK", now=NOW, fetch=lambda **_: "not a frame"
        )

        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
