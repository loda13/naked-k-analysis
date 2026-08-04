"""SEC EDGAR collector for material US-listed company events (Form 8-K).

Reads the SEC EDGAR JSON API (``data.sec.gov/submissions/CIK{cik}.json``) to
retrieve recent Form 8-K filings, which report material corporate events
(earnings releases, M&A, officer changes, etc.). Returns a list of normalized
filing metadata with document URLs; the actual HTML content is left to
downstream consumers.

The SEC rate-limits anonymous requests to 10/second; this collector fetches
one CIK per call, well under that threshold. The User-Agent header is required
by SEC policy.

Only US-listed tickers with a CIK are supported. ADRs traded OTC (e.g. TCEHY,
XIACF) are not included in the SEC database.
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
_USER_AGENT = "naked-k-analysis/3.2.0 loda@example.com"

# SEC company tickers → CIK mapping, refreshed ~daily by the SEC.
_TICKER_INDEX_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL_TEMPLATE = "https://data.sec.gov/submissions/CIK{cik}.json"
_DOCUMENT_URL_TEMPLATE = (
    "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
)

# Exchange suffixes that place a listing outside EDGAR by definition. Resolving
# one still costs a ~2MB index download to learn what the suffix already says,
# and the default ticker pool is all-HK, so the guard pays for itself per run.
_NON_US_SUFFIXES = (".HK", ".SS", ".SZ", ".BJ", ".KS", ".KQ")


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
    SEC database. Tickers carrying a non-US exchange suffix return empty
    without any network call.
    """
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    if max_items <= 0:
        raise ValueError("max_items must be positive")

    if ticker.upper().endswith(_NON_US_SUFFIXES):
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
        if filing.get("form") != "8-K":
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

        doc_url = _DOCUMENT_URL_TEMPLATE.format(
            cik=cik, accession=accession.replace("-", ""), document=primary_doc
        )

        candidates.append(
            _candidate(
                title=f"Form 8-K filing on {filing_date}",
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
