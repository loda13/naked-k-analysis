"""Collect small, normalized public-news metadata for a stock symbol."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from html import unescape
import re
from typing import Any
from unicodedata import normalize
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree.ElementTree import fromstring

import pandas as pd


GetCallable = Callable[..., Any]
SearchFactory = Callable[..., Any]

_GOOGLE_RSS_URL = "https://news.google.com/rss/search"


def collect_news(
    name: str,
    ticker: str,
    *,
    now: datetime | pd.Timestamp | None = None,
    lookback_days: int = 7,
    fallback_days: int = 30,
    max_items: int = 12,
    search_factory: SearchFactory | None = None,
    get: GetCallable | None = None,
) -> dict[str, Any]:
    """Return normalized, deduplicated, newest-first public news metadata."""
    _validate_windows(lookback_days, fallback_days, max_items)
    as_of = _as_timestamp(now)
    now_utc = _to_utc(as_of)
    query = f"{name} {ticker}".strip()
    source_errors: list[str] = []
    candidates: list[dict[str, Any]] = []

    try:
        if search_factory is None:
            from yfinance import Search

            search_factory = Search
        search = search_factory(
            query,
            max_results=max_items * 2,
            news_count=max_items * 2,
            raise_errors=False,
        )
        candidates.extend(_yahoo_candidates(search.news))
    except Exception as exc:  # Providers must never abort the caller.
        source_errors.append(type(exc).__name__)

    try:
        if get is None:
            import requests

            get = requests.get
        response = get(
            _GOOGLE_RSS_URL,
            params={"q": query},
            timeout=20,
        )
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()
        candidates.extend(_google_candidates(response.content))
    except Exception as exc:  # Providers must never abort the caller.
        source_errors.append(type(exc).__name__)

    selected, window_days, collection_freshness = _select_candidates(
        candidates, now_utc, lookback_days, fallback_days, max_items
    )
    if selected:
        status = "ok"
    elif len(source_errors) == 2:
        status = "unavailable"
        collection_freshness = "unavailable"
    else:
        status = "insufficient"
        collection_freshness = "insufficient"

    items = [
        {
            "id": f"news-{index:02d}",
            "title": item["title"],
            "publisher": item["publisher"],
            "published_at": item["published_at"].isoformat(),
            "url": item["url"],
            "summary": item["summary"],
            "source_provider": item["source_provider"],
            "freshness": collection_freshness,
        }
        for index, item in enumerate(selected, start=1)
    ]
    return {
        "status": status,
        "name": name,
        "ticker": ticker,
        "as_of": as_of.isoformat(),
        "window_days": window_days,
        "freshness": collection_freshness,
        "items": items,
        "source_errors": source_errors,
    }


def _validate_windows(lookback_days: int, fallback_days: int, max_items: int) -> None:
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    if fallback_days < lookback_days:
        raise ValueError("fallback_days must be at least lookback_days")
    if max_items <= 0:
        raise ValueError("max_items must be positive")


def _as_timestamp(value: datetime | pd.Timestamp | None) -> pd.Timestamp:
    timestamp = pd.Timestamp.now(tz="UTC") if value is None else pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp


def _to_utc(value: Any) -> datetime | None:
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            timestamp = pd.Timestamp(value, unit="s")
        else:
            timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(timestamp):
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime().astimezone(timezone.utc)


def _yahoo_candidates(news: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for entry in news or []:
        if not isinstance(entry, dict):
            continue
        content = entry.get("content")
        payload = content if isinstance(content, dict) else entry
        provider = payload.get("provider")
        canonical_url = payload.get("canonicalUrl")
        candidates.append(
            _candidate(
                title=payload.get("title"),
                publisher=(provider.get("displayName") if isinstance(provider, dict) else None)
                or payload.get("publisher"),
                published_at=payload.get("pubDate") or payload.get("providerPublishTime"),
                url=(canonical_url.get("url") if isinstance(canonical_url, dict) else None)
                or payload.get("link"),
                summary=payload.get("summary"),
                source_provider="yahoo_finance",
            )
        )
    return [candidate for candidate in candidates if candidate is not None]


def _google_candidates(content: bytes | str) -> list[dict[str, Any]]:
    root = fromstring(content)
    candidates: list[dict[str, Any]] = []
    for item in root.iter():
        if _local_name(item.tag) != "item":
            continue
        fields = {
            _local_name(child.tag): child.text or ""
            for child in item
        }
        candidates.append(
            _candidate(
                title=fields.get("title"),
                publisher=fields.get("source"),
                published_at=fields.get("pubDate"),
                url=fields.get("link"),
                summary=_strip_html(fields.get("description", "")),
                source_provider="google_news_rss",
            )
        )
    return [candidate for candidate in candidates if candidate is not None]


def _candidate(
    *,
    title: Any,
    publisher: Any,
    published_at: Any,
    url: Any,
    summary: Any,
    source_provider: str,
) -> dict[str, Any] | None:
    timestamp = _to_utc(published_at)
    clean_title = _clip(str(title or "").strip(), 300)
    if not clean_title or timestamp is None:
        return None
    return {
        "title": clean_title,
        "publisher": _clip(str(publisher or "").strip(), 300),
        "published_at": timestamp,
        "url": _clip(_canonical_url(str(url or "")), 500),
        "summary": _clip(str(summary or "").strip(), 500),
        "source_provider": source_provider,
    }


def _select_candidates(
    candidates: list[dict[str, Any]],
    now_utc: datetime,
    lookback_days: int,
    fallback_days: int,
    max_items: int,
) -> tuple[list[dict[str, Any]], int, str]:
    past_candidates = [
        candidate for candidate in candidates
        if candidate["published_at"] <= now_utc
        and candidate["published_at"] >= now_utc - pd.Timedelta(days=fallback_days)
    ]
    fresh_cutoff = now_utc - pd.Timedelta(days=lookback_days)
    fresh = [candidate for candidate in past_candidates if candidate["published_at"] >= fresh_cutoff]
    if fresh:
        return _deduplicate(fresh, max_items), lookback_days, "fresh"
    fallback = [candidate for candidate in past_candidates if candidate["published_at"] < fresh_cutoff]
    if fallback:
        return _deduplicate(fallback, max_items), fallback_days, "low_freshness"
    return [], lookback_days, "insufficient"


def _deduplicate(candidates: list[dict[str, Any]], max_items: int) -> list[dict[str, Any]]:
    ordered = sorted(candidates, key=lambda item: item["published_at"], reverse=True)
    seen_titles: set[str] = set()
    seen_urls: set[str] = set()
    selected: list[dict[str, Any]] = []
    for candidate in ordered:
        normalized_title = _dedupe_title(candidate["title"])
        canonical_url = candidate["url"]
        if ((normalized_title and normalized_title in seen_titles)
                or (canonical_url and canonical_url in seen_urls)):
            continue
        if normalized_title:
            seen_titles.add(normalized_title)
        if canonical_url:
            seen_urls.add(canonical_url)
        selected.append(candidate)
        if len(selected) == max_items:
            break
    return selected


def _canonical_url(url: str) -> str:
    parts = urlsplit(url)
    filtered_query = [
        (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not (key.lower().startswith("utm_") or key.lower() in {"gclid", "fbclid"})
    ]
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path,
        urlencode(sorted(filtered_query)),
        "",
    ))


def _dedupe_title(title: str) -> str:
    normalized = normalize("NFKC", title).lower()
    normalized = re.sub(r"[^\w\s]", "", normalized)
    return " ".join(normalized.split())


def _strip_html(value: str) -> str:
    return " ".join(re.sub(r"<[^>]*>", "", unescape(value)).split())


def _clip(value: str, limit: int) -> str:
    return value[:limit]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
