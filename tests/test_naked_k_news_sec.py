"""Behavioral tests for the SEC EDGAR 8-K collector."""

from __future__ import annotations

import unittest

import pandas as pd

import naked_k_news_sec


NOW = pd.Timestamp("2026-08-01T12:00:00+00:00")


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def json(self) -> object:
        return self.payload


def ticker_index(entries: list[tuple[str, int, str]]) -> dict[str, dict[str, object]]:
    """Build a SEC company_tickers.json-style payload from (ticker, cik, title)."""
    return {
        str(i): {"cik_str": cik, "ticker": ticker, "title": title}
        for i, (ticker, cik, title) in enumerate(entries)
    }


def submissions_payload(filings: list[dict[str, object]]) -> dict[str, object]:
    """Build a SEC submissions JSON payload from a list of filing dicts."""
    if not filings:
        return {"filings": {"recent": {}}}

    keys = list(filings[0].keys())
    recent = {key: [f.get(key) for f in filings] for key in keys}
    return {"filings": {"recent": recent}}


def filing(
    *,
    form: str = "8-K",
    filing_date: str = "2026-07-30",
    accession: str = "0001234567-26-000001",
    primary_doc: str = "test-8k.htm",
) -> dict[str, object]:
    return {
        "form": form,
        "filingDate": filing_date,
        "accessionNumber": accession,
        "primaryDocument": primary_doc,
    }


class SecEdgarCollectionTests(unittest.TestCase):
    def test_returns_normalized_8k_filings_in_the_window(self) -> None:
        calls: list[str] = []

        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            calls.append(url)
            if "company_tickers.json" in url:
                return FakeResponse(ticker_index([("TEST", 1234567, "Test Inc")]))
            return FakeResponse(
                submissions_payload(
                    [
                        filing(filing_date="2026-07-30"),
                        filing(filing_date="2026-07-26"),
                        filing(filing_date="2026-07-20"),  # Outside window
                    ]
                )
            )

        items = naked_k_news_sec.collect_sec_filings(
            "TEST", now=NOW, lookback_days=7, max_items=10, get=fake_get
        )

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["published_at"], "2026-07-30T00:00:00+00:00")
        self.assertEqual(items[1]["published_at"], "2026-07-26T00:00:00+00:00")
        self.assertEqual(items[0]["source_provider"], "sec_edgar")
        self.assertEqual(items[0]["publisher"], "SEC EDGAR")
        self.assertIn("test-8k.htm", items[0]["url"])
        # www.sec.gov/Archives wants the CIK unpadded; the padded form 301s.
        # Assert the path segment, not a bare substring: "0001234567" also
        # occurs inside the accession segment, so a substring check passes even
        # when the CIK segment is wrong.
        self.assertIn("/edgar/data/1234567/", items[0]["url"])
        self.assertNotIn("/edgar/data/0001234567/", items[0]["url"])

    def test_periodic_reports_are_not_collected(self) -> None:
        """Only material-event forms qualify; 10-Q/10-K are periodic, not news."""

        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            if "company_tickers.json" in url:
                return FakeResponse(ticker_index([("TEST", 1234567, "Test Inc")]))
            return FakeResponse(
                submissions_payload(
                    [
                        filing(form="8-K", filing_date="2026-07-30"),
                        filing(form="10-Q", filing_date="2026-07-29"),
                        filing(form="10-K", filing_date="2026-07-28"),
                    ]
                )
            )

        items = naked_k_news_sec.collect_sec_filings(
            "TEST", now=NOW, lookback_days=30, get=fake_get
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Form 8-K filing on 2026-07-30")

    def test_foreign_private_issuers_are_collected_via_6k(self) -> None:
        """FPIs report material events on 6-K and never file 8-K.

        Verified live: PDD has 67 recent 6-K and 0 8-K; BABA 339/0, JD 188/0,
        NIO 268/0. Filtering on 8-K alone returned empty forever for every
        China ADR, which is a large share of the tickers this repo follows.
        """

        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            if "company_tickers.json" in url:
                return FakeResponse(ticker_index([("PDD", 1737806, "PDD Holdings")]))
            return FakeResponse(
                submissions_payload(
                    [
                        filing(
                            form="6-K",
                            filing_date="2026-07-30",
                            primary_doc="tm2615739d1_6k.htm",
                        ),
                        filing(form="10-Q", filing_date="2026-07-29"),
                    ]
                )
            )

        items = naked_k_news_sec.collect_sec_filings(
            "PDD", now=NOW, lookback_days=30, get=fake_get
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Form 6-K filing on 2026-07-30")
        self.assertIn("tm2615739d1_6k.htm", items[0]["url"])
        self.assertEqual(items[0]["source_provider"], "sec_edgar")

    def test_both_material_event_forms_coexist_and_stay_sorted(self) -> None:
        """A dual filer must not have one form silently outrank the other."""

        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            if "company_tickers.json" in url:
                return FakeResponse(ticker_index([("TEST", 1234567, "Test Inc")]))
            return FakeResponse(
                submissions_payload(
                    [
                        filing(form="8-K", filing_date="2026-07-28"),
                        filing(form="6-K", filing_date="2026-07-30"),
                    ]
                )
            )

        items = naked_k_news_sec.collect_sec_filings(
            "TEST", now=NOW, lookback_days=30, get=fake_get
        )

        self.assertEqual(
            [item["title"] for item in items],
            ["Form 6-K filing on 2026-07-30", "Form 8-K filing on 2026-07-28"],
        )

    def test_max_items_truncates_after_windowing(self) -> None:
        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            if "company_tickers.json" in url:
                return FakeResponse(ticker_index([("TEST", 1234567, "Test Inc")]))
            return FakeResponse(
                submissions_payload(
                    [filing(filing_date=f"2026-07-{30-i}") for i in range(10)]
                )
            )

        items = naked_k_news_sec.collect_sec_filings(
            "TEST", now=NOW, lookback_days=30, max_items=3, get=fake_get
        )

        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["published_at"], "2026-07-30T00:00:00+00:00")
        self.assertEqual(items[-1]["published_at"], "2026-07-28T00:00:00+00:00")

    def test_future_filings_are_dropped(self) -> None:
        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            if "company_tickers.json" in url:
                return FakeResponse(ticker_index([("TEST", 1234567, "Test Inc")]))
            return FakeResponse(
                submissions_payload([filing(filing_date="2026-08-05")])
            )

        items = naked_k_news_sec.collect_sec_filings(
            "TEST", now=NOW, lookback_days=30, get=fake_get
        )

        self.assertEqual(items, [])

    def test_ticker_not_found_degrades_to_empty(self) -> None:
        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            if "company_tickers.json" in url:
                return FakeResponse(ticker_index([("OTHER", 9999999, "Other Inc")]))
            raise AssertionError("should not fetch submissions for unknown ticker")

        items = naked_k_news_sec.collect_sec_filings(
            "NOTFOUND", now=NOW, get=fake_get
        )

        self.assertEqual(items, [])

    def test_transport_failure_degrades_to_empty(self) -> None:
        def failing_get(url: str, **kwargs: object) -> FakeResponse:
            raise RuntimeError("network error")

        items = naked_k_news_sec.collect_sec_filings(
            "TEST", now=NOW, get=failing_get
        )

        self.assertEqual(items, [])

    def test_malformed_ticker_index_degrades_to_empty(self) -> None:
        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            if "company_tickers.json" in url:
                return FakeResponse("not a dict")
            raise AssertionError("should not proceed past malformed index")

        items = naked_k_news_sec.collect_sec_filings(
            "TEST", now=NOW, get=fake_get
        )

        self.assertEqual(items, [])

    def test_malformed_submissions_degrades_to_empty(self) -> None:
        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            if "company_tickers.json" in url:
                return FakeResponse(ticker_index([("TEST", 1234567, "Test Inc")]))
            return FakeResponse({"filings": {}})  # Missing 'recent'

        items = naked_k_news_sec.collect_sec_filings(
            "TEST", now=NOW, get=fake_get
        )

        self.assertEqual(items, [])

    def test_filing_missing_required_fields_is_skipped(self) -> None:
        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            if "company_tickers.json" in url:
                return FakeResponse(ticker_index([("TEST", 1234567, "Test Inc")]))
            return FakeResponse(
                submissions_payload(
                    [
                        filing(accession="", filing_date="2026-07-30"),  # No accession
                        filing(primary_doc="", filing_date="2026-07-29"),  # No doc
                        filing(filing_date=""),  # No date
                        filing(filing_date="2026-07-28"),  # Valid
                    ]
                )
            )

        items = naked_k_news_sec.collect_sec_filings(
            "TEST", now=NOW, lookback_days=30, get=fake_get
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["published_at"], "2026-07-28T00:00:00+00:00")

    def test_rejects_invalid_windows_before_touching_network(self) -> None:
        calls: list[str] = []

        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            calls.append(url)
            return FakeResponse({})

        for kwargs in ({"lookback_days": 0}, {"max_items": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                naked_k_news_sec.collect_sec_filings(
                    "TEST", now=NOW, get=fake_get, **kwargs
                )

        self.assertEqual(calls, [])

    def test_suffixed_listings_skip_the_network_entirely(self) -> None:
        """A suffixed ticker has no CIK, so downloading the index is pure waste.

        The index is a ~2MB download and 3 of the 7 default tickers are HK,
        so without this guard every run pays for round trips that can only ever
        answer ``None``. The rule is "contains a dot", not a list of the
        suffixes we thought of, so European and Japanese listings are covered
        by the same check rather than needing to be enumerated later.
        """
        calls: list[str] = []

        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            calls.append(url)
            return FakeResponse({})

        for ticker in (
            "0700.HK",
            "600519.SS",
            "000001.SZ",
            "430047.BJ",
            "005930.KS",
            "VOD.L",  # never enumerated in a suffix denylist
            "7203.T",
            "SHOP.TO",
        ):
            with self.subTest(ticker=ticker):
                items = naked_k_news_sec.collect_sec_filings(
                    ticker, now=NOW, get=fake_get
                )
                self.assertEqual(items, [])

        self.assertEqual(calls, [])

    def test_plain_us_symbols_still_reach_the_network(self) -> None:
        """The skip must key on the dot, not reject every unresolved ticker."""
        calls: list[str] = []

        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            calls.append(url)
            if "company_tickers" in url:
                return FakeResponse(ticker_index([("PDD", 1737806, "PDD Holdings")]))
            return FakeResponse(submissions_payload([filing()]))

        items = naked_k_news_sec.collect_sec_filings("PDD", now=NOW, get=fake_get)

        self.assertEqual(len(items), 1)
        self.assertEqual(len(calls), 2)

    def test_hyphenated_share_classes_are_not_skipped(self) -> None:
        """SEC spells share classes with a hyphen, so BRK-B must still resolve.

        Verified against the live index: of 10432 entries, 544 contain a hyphen
        and zero contain a dot. Keying the skip on the dot is what keeps these
        reachable; a naive "non-alphanumeric means foreign" rule would drop them.
        """
        calls: list[str] = []

        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            calls.append(url)
            if "company_tickers" in url:
                return FakeResponse(ticker_index([("BRK-B", 1067983, "Berkshire")]))
            return FakeResponse(submissions_payload([filing()]))

        items = naked_k_news_sec.collect_sec_filings("BRK-B", now=NOW, get=fake_get)

        self.assertEqual(len(items), 1)
        self.assertEqual(len(calls), 2)


class SecCikResolutionTests(unittest.TestCase):
    def test_resolves_ticker_to_zero_padded_cik(self) -> None:
        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            return FakeResponse(ticker_index([("AAPL", 320193, "Apple Inc")]))

        cik = naked_k_news_sec._resolve_cik("AAPL", fake_get)

        self.assertEqual(cik, "0000320193")

    def test_ticker_match_is_case_insensitive(self) -> None:
        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            return FakeResponse(ticker_index([("AAPL", 320193, "Apple Inc")]))

        self.assertEqual(naked_k_news_sec._resolve_cik("aapl", fake_get), "0000320193")
        self.assertEqual(naked_k_news_sec._resolve_cik("AaPl", fake_get), "0000320193")

    def test_ticker_not_found_returns_none(self) -> None:
        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            return FakeResponse(ticker_index([("AAPL", 320193, "Apple Inc")]))

        self.assertIsNone(naked_k_news_sec._resolve_cik("TSLA", fake_get))

    def test_malformed_index_returns_none(self) -> None:
        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            return FakeResponse("not a dict")

        self.assertIsNone(naked_k_news_sec._resolve_cik("AAPL", fake_get))


if __name__ == "__main__":
    unittest.main()
