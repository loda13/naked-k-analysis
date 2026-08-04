"""SEC EDGAR collector for material corporate events (Forms 8-K and 6-K).

Reads the SEC EDGAR JSON API (``data.sec.gov/submissions/CIK{cik}.json``) to
retrieve recent material-event filings (earnings releases, M&A, officer
changes, etc.). Returns a list of normalized filing metadata with document
URLs; the actual HTML content is left to downstream consumers.

Both forms are collected because they are mutually exclusive by filer type:
domestic issuers file 8-K, foreign private issuers file 6-K and never file
8-K. Collecting only 8-K silently excluded every China ADR — see
``_MATERIAL_EVENT_FORMS``.

The SEC rate-limits anonymous requests to 10/second; this collector fetches
one CIK per call, well under that threshold. The User-Agent header is required
by SEC policy and must carry a real contact address — a placeholder domain
risks being throttled or blocked.

Any ticker with a CIK is supported, including exchange-listed foreign issuers.
ADRs traded OTC (e.g. TCEHY, XIACF) have no CIK and are not in the SEC
database.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import json
from typing import Any

import pandas as pd

from naked_k_news import _as_timestamp, _candidate


GetCallable = Callable[..., Any]

_SOURCE_PROVIDER = "sec_edgar"
_PUBLISHER = "SEC EDGAR"
_USER_AGENT = "naked-k-analysis/3.2.0 cdjudder@gmail.com"

# SEC company tickers → CIK mapping, refreshed ~daily by the SEC.
_TICKER_INDEX_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL_TEMPLATE = "https://data.sec.gov/submissions/CIK{cik}.json"
_DOCUMENT_URL_TEMPLATE = (
    "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
)


# A dot means the ticker carries an exchange suffix (0700.HK, 9992.HK, VOD.L),
# which places the listing outside EDGAR by definition. Verified against the
# live index: of 10432 entries, zero contain a dot — SEC spells share classes
# with a hyphen (BRK-B, BF-A), never a dot. So this is the general rule, not a
# denylist of the suffixes we happened to think of; .L/.T/.TO/.PA are covered
# too. Worth short-circuiting because resolving one costs a ~2MB index download
# to learn what the ticker already said.
def _is_outside_edgar(ticker: str) -> bool:
    return "." in ticker


# Domestic issuers report material events on 8-K; foreign private issuers file
# 6-K instead and never file 8-K at all. Filtering on 8-K alone returned empty
# forever for every China ADR — verified live: PDD 67 6-K / 0 8-K, BABA 339/0,
# JD 188/0, NIO 268/0. Both forms carry the same filingDate / accessionNumber /
# primaryDocument fields, so they share one parse path.
_MATERIAL_EVENT_FORMS = frozenset({"8-K", "6-K"})


def collect_sec_8k_filings(
    ticker: str,
    *,
    now: datetime | pd.Timestamp | None = None,
    lookback_days: int = 30,
    max_items: int = 10,
    get: GetCallable | None = None,
) -> list[dict[str, Any]]:
    """Return normalized, newest-first SEC 8-K filings for the given ticker.

    The ticker must be US-listed with a CIK. OTC ADRs are not included in the
    SEC database. Tickers carrying an exchange suffix (any dot) return empty
    without any network call.
    """
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    if max_items <= 0:
        raise ValueError("max_items must be positive")

    if _is_outside_edgar(ticker):
        return []

    now_utc = _as_timestamp(now)
    cutoff = now_utc - pd.Timedelta(days=lookback_days)

    if get is None:
        import requests

        get = requests.get

    try:
        cik = _resolve_cik(ticker, get)
    except Exception:  # Providers must never abort the caller.
        return []

    if cik is None:
        return []

    try:
        filings = _fetch_recent_filings(cik, get)
    except Exception:
        return []

    candidates: list[dict[str, Any]] = []
    for filing in filings:
        form = filing.get("form")
        if form not in _MATERIAL_EVENT_FORMS:
            continue
        filing_date = filing.get("filingDate")
        if not filing_date:
            continue
        timestamp = pd.Timestamp(filing_date, tz="UTC")
        if not (cutoff <= timestamp <= now_utc):
            continue

        accession = filing.get("accessionNumber", "")
        primary_doc = filing.get("primaryDocument", "")
        if not accession or not primary_doc:
            continue

        # The two SEC hosts disagree on CIK format: data.sec.gov/submissions
        # requires the zero-padded 10-digit form (unpadded is a 404), while
        # www.sec.gov/Archives requires it unpadded (padded is a 301 to the
        # unpadded path). Emitting the padded form here made every document URL
        # a redirect — reachable with -L, but a wasted round trip and a non-200
        # for any consumer that does not follow redirects.
        doc_url = _DOCUMENT_URL_TEMPLATE.format(
            cik=cik.lstrip("0"),
            accession=accession.replace("-", ""),
            document=primary_doc,
        )

        candidates.append(
            _candidate(
                title=f"Form {form} filing on {filing_date}",
                published_at=timestamp,
                url=doc_url,
                summary="",
                source_provider=_SOURCE_PROVIDER,
                publisher=_PUBLISHER,
            )
        )

        if len(candidates) >= max_items:
            break

    candidates.sort(key=lambda item: item["published_at"], reverse=True)
    return [
        {**candidate, "published_at": candidate["published_at"].isoformat()}
        for candidate in candidates
    ]


def _resolve_cik(ticker: str, get: GetCallable) -> str | None:
    """Return the zero-padded 10-digit CIK for the ticker, or None if not found."""
    response = get(
        _TICKER_INDEX_URL,
        headers={"User-Agent": _USER_AGENT},
        timeout=15,
    )
    data = response.json()
    if not isinstance(data, dict):
        return None

    ticker_upper = ticker.upper()
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        if entry.get("ticker", "").upper() == ticker_upper:
            cik_int = entry.get("cik_str")
            if isinstance(cik_int, int):
                return f"{cik_int:010d}"
    return None


def _fetch_recent_filings(cik: str, get: GetCallable) -> list[dict[str, Any]]:
    """Return the 'recent' filings list for the given CIK."""
    url = _SUBMISSIONS_URL_TEMPLATE.format(cik=cik)
    response = get(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        timeout=15,
    )
    data = response.json()
    recent = data.get("filings", {}).get("recent", {})
    if not recent:
        return []

    # SEC returns parallel arrays keyed by field name; zip into dicts.
    keys = list(recent.keys())
    if not keys:
        return []
    length = len(recent[keys[0]])
    return [
        {key: recent[key][i] for key in keys if i < len(recent[key])}
        for i in range(length)
    ]
