"""Behavioral tests for the optional Sina rolling-newswire collector."""

from __future__ import annotations

import unittest

import pandas as pd

import naked_k_news_sina
from tests.conftest import FakeResponse


NOW = pd.Timestamp("2026-07-31T12:00:00+08:00")


def feed_payload(rows: list[dict[str, object]]) -> dict[str, object]:
    """Wrap rows in the endpoint's nested envelope."""
    return {
        "result": {
            "data": {
                "feed": {
                    "list": [
                        {"create_time": row["时间"], "rich_text": row["内容"]}
                        for row in rows
                    ]
                }
            }
        }
    }


def news_row(
    *, content: str, published_at: str = "2026-07-31 11:30:00"
) -> dict[str, object]:
    return {"时间": published_at, "内容": content}


def get_returning(rows: list[dict[str, object]]):
    """Serve ``rows`` on page 1 and an empty page after, halting the walk."""

    def _get(url: str, **kwargs: object) -> FakeResponse:
        params = kwargs.get("params") or {}
        page = str(params.get("page", "1"))
        return FakeResponse(feed_payload(rows if page == "1" else []))

    return _get


def get_paging(pages: list[list[dict[str, object]]]):
    """Serve one list of rows per page, then empty pages."""

    def _get(url: str, **kwargs: object) -> FakeResponse:
        params = kwargs.get("params") or {}
        index = int(str(params.get("page", "1"))) - 1
        rows = pages[index] if 0 <= index < len(pages) else []
        return FakeResponse(feed_payload(rows))

    return _get


def collect(rows: list[dict[str, object]], **kwargs: object) -> list[dict[str, object]]:
    """Run the collector over a single page of rows."""
    kwargs.setdefault("now", NOW)
    return naked_k_news_sina.collect_sina_rolling_news(
        kwargs.pop("ticker", "1810.HK"),
        kwargs.pop("name", "小米"),
        get=get_returning(rows),
        **kwargs,
    )


class SinaKeywordBuildTests(unittest.TestCase):
    def test_hk_ticker_is_zero_padded_and_bare_code_excluded(self) -> None:
        """A bare 1810 matches prose like "利润暴增1810%" in a market-wide digest."""
        keywords = naked_k_news_sina._match_keywords("1810.HK", "小米", None)

        self.assertIn("01810", keywords)
        self.assertNotIn("1810", keywords)

    def test_mainland_and_us_tickers_keep_their_bare_code(self) -> None:
        for ticker, expected in (
            ("600519.SS", "600519"),
            ("001391.SZ", "001391"),
            ("PDD", "pdd"),
        ):
            with self.subTest(ticker=ticker):
                self.assertIn(
                    expected, naked_k_news_sina._match_keywords(ticker, "", None)
                )

    def test_aliases_are_included_and_deduplicated(self) -> None:
        keywords = naked_k_news_sina._match_keywords(
            "1810.HK", "小米", ["小米集团", "小米", "Xiaomi"]
        )

        self.assertEqual(len(keywords), len(set(keywords)))
        self.assertIn("小米集团", keywords)
        self.assertIn("xiaomi", keywords)

    def test_short_ascii_names_are_dropped(self) -> None:
        """A two-letter latin token matches far too much digest prose."""
        self.assertEqual(naked_k_news_sina._match_keywords("", "MI", None), [])

    def test_short_cjk_names_are_kept(self) -> None:
        """Two-character Chinese issuer names are specific enough to keep."""
        self.assertIn("腾讯", naked_k_news_sina._match_keywords("", "腾讯", None))

    def test_no_keywords_skips_the_network_entirely(self) -> None:
        calls: list[object] = []

        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            calls.append(url)
            return FakeResponse(feed_payload([]))

        items = naked_k_news_sina.collect_sina_rolling_news(
            "", "", now=NOW, get=fake_get
        )

        self.assertEqual(items, [])
        self.assertEqual(calls, [])


class SinaHeadlineSplitTests(unittest.TestCase):
    def test_bracketed_payload_splits_into_headline_and_body(self) -> None:
        title, summary = naked_k_news_sina._split_headline(
            "【小米新车定价25.99万】小米今日发布新车，起售价25.99万元。"
        )

        self.assertEqual(title, "小米新车定价25.99万")
        self.assertEqual(summary, "小米今日发布新车，起售价25.99万元。")

    def test_unbracketed_payload_becomes_its_own_title(self) -> None:
        """Most live rows are bare one-liners with no bracketed headline."""
        title, summary = naked_k_news_sina._split_headline("腾讯回购股份1亿港元。")

        self.assertEqual(title, "腾讯回购股份1亿港元。")
        self.assertEqual(summary, "")

    def test_multiline_body_is_preserved(self) -> None:
        title, summary = naked_k_news_sina._split_headline("【腾讯公告】第一行\n第二行")

        self.assertEqual(title, "腾讯公告")
        self.assertEqual(summary, "第一行\n第二行")

    def test_blank_payload_yields_empty_pair(self) -> None:
        for value in ("", "   ", None):
            with self.subTest(value=value):
                self.assertEqual(naked_k_news_sina._split_headline(value), ("", ""))


class SinaAttributionTests(unittest.TestCase):
    def test_headline_hit_is_collected(self) -> None:
        items = collect([news_row(content="【小米新车定价25.99万】小米今日发布。")])

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "小米新车定价25.99万")

    def test_body_only_hit_is_rejected(self) -> None:
        """Digest bodies name-drop unrelated issuers, so a body hit proves nothing."""
        items = collect(
            [news_row(content="【某公司季度业绩】报告提到小米作为对比样本。")]
        )

        self.assertEqual(items, [])

    def test_unrelated_item_is_rejected(self) -> None:
        items = collect([news_row(content="【美联储决议】维持利率不变。")])

        self.assertEqual(items, [])

    def test_zero_padded_code_in_headline_matches(self) -> None:
        items = collect(
            [news_row(content="港交所：小米集团(01810.HK)于7月31日回购了170万股。")],
            name="",
        )

        self.assertEqual(len(items), 1)

    def test_percentage_figure_does_not_match_bare_code(self) -> None:
        items = collect([news_row(content="【某公司利润暴增1810%】年报显示。")], name="")

        self.assertEqual(items, [])


class SinaNormalizationTests(unittest.TestCase):
    def test_naive_timestamp_is_read_as_beijing_and_converted_to_utc(self) -> None:
        items = collect(
            [news_row(content="【小米公告】正文。", published_at="2026-07-31 11:30:00")]
        )

        self.assertEqual(items[0]["published_at"], "2026-07-31T03:30:00+00:00")

    def test_provider_and_publisher_are_tagged(self) -> None:
        items = collect([news_row(content="【小米公告】正文。")])

        self.assertEqual(items[0]["source_provider"], "sina")
        self.assertEqual(items[0]["publisher"], "新浪财经")

    def test_url_is_empty_because_the_feed_has_no_permalink(self) -> None:
        items = collect([news_row(content="【小米公告】正文。")])

        self.assertEqual(items[0]["url"], "")

    def test_items_are_returned_newest_first(self) -> None:
        items = collect(
            [
                news_row(content="【小米公告A】", published_at="2026-07-31 09:00:00"),
                news_row(content="【小米公告B】", published_at="2026-07-31 11:00:00"),
            ]
        )

        self.assertEqual(
            [item["title"] for item in items], ["小米公告B", "小米公告A"]
        )

    def test_max_items_truncates_after_sorting(self) -> None:
        items = collect(
            [
                news_row(content="【小米公告A】", published_at="2026-07-31 09:00:00"),
                news_row(content="【小米公告B】", published_at="2026-07-31 11:00:00"),
            ],
            max_items=1,
        )

        self.assertEqual([item["title"] for item in items], ["小米公告B"])


class SinaWindowTests(unittest.TestCase):
    def test_items_older_than_the_lookback_are_dropped(self) -> None:
        items = collect(
            [
                news_row(content="【小米旧闻】", published_at="2026-07-20 09:00:00"),
                news_row(content="【小米新闻】", published_at="2026-07-31 09:00:00"),
            ],
            lookback_days=7,
        )

        self.assertEqual([item["title"] for item in items], ["小米新闻"])

    def test_future_items_are_dropped(self) -> None:
        """A clock-skewed row must not front-run the supplied as-of time."""
        items = collect(
            [news_row(content="【小米未来】", published_at="2026-08-05 09:00:00")]
        )

        self.assertEqual(items, [])

    def test_paging_continues_until_a_page_falls_before_the_cutoff(self) -> None:
        """20 rows span minutes, so the window is only meaningful if pages walk back."""
        pages = [
            [news_row(content="【小米公告A】", published_at="2026-07-31 11:00:00")],
            [news_row(content="【小米公告B】", published_at="2026-07-31 08:00:00")],
            [news_row(content="【小米公告C】", published_at="2026-07-20 08:00:00")],
            [news_row(content="【小米公告D】", published_at="2026-07-19 08:00:00")],
        ]

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, lookback_days=7, get=get_paging(pages)
        )

        # C is past the cutoff and stops the walk, so D is never requested.
        self.assertEqual(
            [item["title"] for item in items], ["小米公告A", "小米公告B"]
        )

    def test_paging_stops_at_an_empty_page(self) -> None:
        requested: list[str] = []

        def _get(url: str, **kwargs: object) -> FakeResponse:
            params = kwargs.get("params") or {}
            page = str(params.get("page", "1"))
            requested.append(page)
            rows = (
                [news_row(content="【小米公告】", published_at="2026-07-31 11:00:00")]
                if page == "1"
                else []
            )
            return FakeResponse(feed_payload(rows))

        naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, get=_get
        )

        self.assertEqual(requested, ["1", "2"])

    def test_paging_is_bounded(self) -> None:
        """A feed that never reaches the cutoff must not page forever.

        The ceiling is asserted as a literal rather than against ``_MAX_PAGES``,
        so raising the constant fails here instead of silently widening the walk.
        """
        requested: list[str] = []

        def _get(url: str, **kwargs: object) -> FakeResponse:
            params = kwargs.get("params") or {}
            requested.append(str(params.get("page")))
            return FakeResponse(
                feed_payload(
                    [news_row(content="【小米公告】", published_at="2026-07-31 11:00:00")]
                )
            )

        naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, get=_get
        )

        self.assertEqual(len(requested), 20)
        self.assertEqual(requested[0], "1")
        self.assertEqual(requested[-1], "20")

    def test_duplicate_rows_across_pages_are_collapsed(self) -> None:
        """The live feed repeats rows across page boundaries as it advances."""
        row = news_row(content="【小米公告】", published_at="2026-07-31 11:00:00")
        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, get=get_paging([[row], [row], []])
        )

        self.assertEqual(len(items), 1)

    def test_rejects_invalid_windows_before_touching_the_network(self) -> None:
        calls: list[object] = []

        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            calls.append(url)
            return FakeResponse(feed_payload([]))

        for kwargs in ({"lookback_days": 0}, {"max_items": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                naked_k_news_sina.collect_sina_rolling_news(
                    "1810.HK", "小米", now=NOW, get=fake_get, **kwargs
                )

        self.assertEqual(calls, [])


class SinaDegradationTests(unittest.TestCase):
    def test_transport_failure_degrades_to_empty(self) -> None:
        def failing_get(url: str, **kwargs: object) -> FakeResponse:
            raise RuntimeError("boom")

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, get=failing_get
        )

        self.assertEqual(items, [])

    def test_partial_failure_keeps_earlier_pages(self) -> None:
        """A mid-walk outage must not discard what already arrived."""

        def _get(url: str, **kwargs: object) -> FakeResponse:
            params = kwargs.get("params") or {}
            if str(params.get("page")) == "1":
                return FakeResponse(
                    feed_payload(
                        [
                            news_row(
                                content="【小米公告】", published_at="2026-07-31 11:00:00"
                            )
                        ]
                    )
                )
            raise RuntimeError("boom")

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, get=_get
        )

        self.assertEqual(len(items), 1)

    def test_malformed_envelope_degrades_to_empty(self) -> None:
        for payload in ({}, {"result": {}}, {"result": {"data": {"feed": {}}}}, None):
            with self.subTest(payload=payload):
                items = naked_k_news_sina.collect_sina_rolling_news(
                    "1810.HK",
                    "小米",
                    now=NOW,
                    get=lambda url, **kw: FakeResponse(payload),
                )
                self.assertEqual(items, [])

    def test_non_list_feed_degrades_to_empty(self) -> None:
        payload = {"result": {"data": {"feed": {"list": "nope"}}}}

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, get=lambda url, **kw: FakeResponse(payload)
        )

        self.assertEqual(items, [])

    def test_unparseable_timestamp_row_is_skipped(self) -> None:
        items = collect(
            [
                news_row(content="【小米公告A】", published_at="not-a-date"),
                news_row(content="【小米公告B】", published_at="2026-07-31 11:00:00"),
            ]
        )

        self.assertEqual([item["title"] for item in items], ["小米公告B"])

    def test_blank_content_row_is_skipped(self) -> None:
        items = collect(
            [news_row(content=""), news_row(content="【小米公告】正文。")]
        )

        self.assertEqual(len(items), 1)


if __name__ == "__main__":
    unittest.main()
