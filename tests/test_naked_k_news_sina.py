"""Behavioral tests for the optional Sina rolling-newswire collector."""

from __future__ import annotations

import unittest

import pandas as pd

import naked_k_news_sina


NOW = pd.Timestamp("2026-07-31T12:00:00+08:00")

_COLUMNS = ["时间", "内容"]


def news_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=_COLUMNS)


def news_row(*, content: str, published_at: str = "2026-07-31 11:30:00") -> dict[str, object]:
    return {"时间": published_at, "内容": content}


def fetch_returning(frame: pd.DataFrame):
    def _fetch(**_kwargs: object) -> pd.DataFrame:
        return frame

    return _fetch


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
        keywords = naked_k_news_sina._match_keywords("", "MI", None)

        self.assertEqual(keywords, [])

    def test_short_cjk_names_are_kept(self) -> None:
        """Two-character Chinese issuer names are specific enough to keep."""
        self.assertIn("腾讯", naked_k_news_sina._match_keywords("", "腾讯", None))

    def test_no_keywords_skips_the_provider_call(self) -> None:
        calls: list[object] = []

        def fake_fetch(**kwargs: object) -> pd.DataFrame:
            calls.append(kwargs)
            return news_frame([])

        items = naked_k_news_sina.collect_sina_rolling_news(
            "", "", now=NOW, fetch=fake_fetch
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
        title, summary = naked_k_news_sina._split_headline("腾讯回购股份1亿港元。")

        self.assertEqual(title, "腾讯回购股份1亿港元。")
        self.assertEqual(summary, "")

    def test_multiline_body_is_preserved(self) -> None:
        title, summary = naked_k_news_sina._split_headline(
            "【腾讯公告】第一行\n第二行"
        )

        self.assertEqual(title, "腾讯公告")
        self.assertEqual(summary, "第一行\n第二行")

    def test_blank_payload_yields_empty_pair(self) -> None:
        for value in ("", "   ", None):
            with self.subTest(value=value):
                self.assertEqual(naked_k_news_sina._split_headline(value), ("", ""))


class SinaAttributionTests(unittest.TestCase):
    def test_headline_hit_is_collected(self) -> None:
        frame = news_frame([news_row(content="【小米新车定价25.99万】小米今日发布。")])

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, fetch=fetch_returning(frame)
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "小米新车定价25.99万")

    def test_body_only_hit_is_rejected(self) -> None:
        """Digest bodies name-drop unrelated issuers, so a body hit proves nothing."""
        frame = news_frame(
            [news_row(content="【某公司季度业绩】报告提到小米作为对比样本。")]
        )

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, fetch=fetch_returning(frame)
        )

        self.assertEqual(items, [])

    def test_unrelated_item_is_rejected(self) -> None:
        frame = news_frame([news_row(content="【美联储决议】维持利率不变。")])

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, fetch=fetch_returning(frame)
        )

        self.assertEqual(items, [])

    def test_zero_padded_code_in_headline_matches(self) -> None:
        frame = news_frame([news_row(content="【01810 盘中异动】股价上涨。")])

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "", now=NOW, fetch=fetch_returning(frame)
        )

        self.assertEqual(len(items), 1)

    def test_percentage_figure_does_not_match_bare_code(self) -> None:
        frame = news_frame([news_row(content="【某公司利润暴增1810%】年报显示。")])

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "", now=NOW, fetch=fetch_returning(frame)
        )

        self.assertEqual(items, [])


class SinaNormalizationTests(unittest.TestCase):
    def test_naive_timestamp_is_read_as_beijing_and_converted_to_utc(self) -> None:
        frame = news_frame(
            [news_row(content="【小米公告】正文。", published_at="2026-07-31 11:30:00")]
        )

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, fetch=fetch_returning(frame)
        )

        self.assertEqual(items[0]["published_at"], "2026-07-31T03:30:00+00:00")

    def test_provider_and_publisher_are_tagged(self) -> None:
        frame = news_frame([news_row(content="【小米公告】正文。")])

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, fetch=fetch_returning(frame)
        )

        self.assertEqual(items[0]["source_provider"], "sina")
        self.assertEqual(items[0]["publisher"], "新浪财经")

    def test_url_is_empty_because_the_feed_exposes_no_permalink(self) -> None:
        frame = news_frame([news_row(content="【小米公告】正文。")])

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, fetch=fetch_returning(frame)
        )

        self.assertEqual(items[0]["url"], "")

    def test_items_are_returned_newest_first(self) -> None:
        frame = news_frame(
            [
                news_row(content="【小米公告A】正文。", published_at="2026-07-30 09:00:00"),
                news_row(content="【小米公告B】正文。", published_at="2026-07-31 09:00:00"),
            ]
        )

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, fetch=fetch_returning(frame)
        )

        self.assertEqual(
            [item["title"] for item in items], ["小米公告B", "小米公告A"]
        )

    def test_max_items_caps_the_result(self) -> None:
        frame = news_frame(
            [
                news_row(content=f"【小米公告{index}】正文。", published_at="2026-07-31 09:00:00")
                for index in range(5)
            ]
        )

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, max_items=2, fetch=fetch_returning(frame)
        )

        self.assertEqual(len(items), 2)


class SinaWindowTests(unittest.TestCase):
    def test_items_outside_the_lookback_window_are_dropped(self) -> None:
        frame = news_frame(
            [news_row(content="【小米公告】正文。", published_at="2026-07-01 09:00:00")]
        )

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, lookback_days=7, fetch=fetch_returning(frame)
        )

        self.assertEqual(items, [])

    def test_future_timestamps_are_dropped(self) -> None:
        frame = news_frame(
            [news_row(content="【小米公告】正文。", published_at="2026-08-05 09:00:00")]
        )

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, fetch=fetch_returning(frame)
        )

        self.assertEqual(items, [])

    def test_non_positive_windows_are_rejected(self) -> None:
        for kwargs in ({"lookback_days": 0}, {"max_items": 0}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    naked_k_news_sina.collect_sina_rolling_news(
                        "1810.HK", "小米", now=NOW, **kwargs
                    )


class SinaDegradationTests(unittest.TestCase):
    def test_provider_failure_degrades_to_empty_list(self) -> None:
        def failing_fetch(**_kwargs: object) -> pd.DataFrame:
            raise RuntimeError("network down")

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, fetch=failing_fetch
        )

        self.assertEqual(items, [])

    def test_missing_dependency_degrades_to_empty_list(self) -> None:
        def failing_loader():
            raise ImportError("No module named 'akshare'")

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, loader=failing_loader
        )

        self.assertEqual(items, [])

    def test_non_dataframe_payload_degrades_to_empty_list(self) -> None:
        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, fetch=lambda **_: {"内容": "not a frame"}
        )

        self.assertEqual(items, [])

    def test_malformed_timestamp_row_is_skipped(self) -> None:
        frame = news_frame(
            [
                news_row(content="【小米公告A】正文。", published_at="not-a-date"),
                news_row(content="【小米公告B】正文。", published_at="2026-07-31 09:00:00"),
            ]
        )

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, fetch=fetch_returning(frame)
        )

        self.assertEqual([item["title"] for item in items], ["小米公告B"])

    def test_blank_content_row_is_skipped(self) -> None:
        frame = news_frame(
            [
                news_row(content=""),
                news_row(content="【小米公告】正文。"),
            ]
        )

        items = naked_k_news_sina.collect_sina_rolling_news(
            "1810.HK", "小米", now=NOW, fetch=fetch_returning(frame)
        )

        self.assertEqual(len(items), 1)


if __name__ == "__main__":
    unittest.main()
