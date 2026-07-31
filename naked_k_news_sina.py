"""Sina rolling-newswire collector for minute-level breaking coverage.

Reads Sina's global live feed (the ``zhibo.sina.com.cn`` endpoint behind
https://finance.sina.com.cn/7x24). Unlike the per-symbol East Money feed in
:mod:`naked_k_news_akshare`, this is a market-wide digest: every item is scanned
against the symbol's aliases, so attribution happens here rather than in the
caller's relevance gate.

The endpoint is paged directly rather than through ``akshare``:
``akshare.stock_info_global_sina`` hardcodes ``page_size=20``, and the feed is
busy enough that 20 rows span only ten-odd minutes — far too narrow for a
multi-day lookback. Paging back until the cutoff is what makes the window
meaningful. Any provider failure degrades to an empty list so the caller still
renders a pure technical report.

The feed carries no per-item URL or publisher, and packs headline and body into
one ``【标题】正文`` string, so both are split out here.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import re
from typing import Any

import pandas as pd

from naked_k_news import _as_timestamp, _candidate


FetchCallable = Callable[..., Any]
LoaderCallable = Callable[[], FetchCallable]
GetCallable = Callable[..., Any]

_BEIJING_TZ = "Asia/Shanghai"
_SOURCE_PROVIDER = "sina"
_PUBLISHER = "新浪财经"

_FEED_URL = "https://zhibo.sina.com.cn/api/zhibo/feed"
# zhibo_id 152 is the 7x24 global finance channel.
_ZHIBO_ID = "152"
_PAGE_SIZE = 100
# The feed runs ~100 items per 45 minutes, so 20 pages reaches roughly a day.
# Deep history is East Money's job; this source exists for recency.
_MAX_PAGES = 20

# Sina packs the headline in full-width brackets ahead of the body, e.g.
# "【小米新车定价25.99万】小米今日发布...". Items without brackets are plain
# one-liners that serve as their own title.
_HEADLINE_PATTERN = re.compile(r"^\s*【([^】]{1,300})】\s*(.*)$", re.DOTALL)


def collect_sina_rolling_news(
    ticker: str,
    name: str = "",
    *,
    now: datetime | pd.Timestamp | None = None,
    lookback_days: int = 7,
    max_items: int = 20,
    aliases: list[str] | None = None,
    get: GetCallable | None = None,
) -> list[dict[str, Any]]:
    """Return normalized, newest-first Sina newswire items mentioning the symbol.

    Sina publishes naive Beijing timestamps, so they are localized explicitly.
    The feed is a reverse-chronological stream with no date filter, so pages are
    walked until one falls entirely before the cutoff.
    """
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    if max_items <= 0:
        raise ValueError("max_items must be positive")

    now_utc = _as_timestamp(now)
    cutoff = now_utc - pd.Timedelta(days=lookback_days)
    keywords = _match_keywords(ticker, name, aliases)
    if not keywords:
        return []

    if get is None:
        import requests

        get = requests.get

    candidates: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    for page in range(1, _MAX_PAGES + 1):
        try:
            rows = _fetch_page(get, page)
        except Exception:  # Providers must never abort the caller.
            break
        if not rows:
            break

        page_exhausted = False
        for row in rows:
            timestamp = _beijing_to_utc(row.get("时间"))
            if timestamp is None:
                continue
            if timestamp < cutoff:
                # Reverse-chronological, so this page has run past the window.
                page_exhausted = True
                continue
            if timestamp > now_utc:
                continue
            key = (str(row.get("时间")), str(row.get("内容"))[:60])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            candidate = _row_candidate(row, keywords)
            if candidate is not None:
                candidates.append(candidate)

        if page_exhausted:
            break

    candidates.sort(key=lambda item: item["published_at"], reverse=True)
    return [
        {**candidate, "published_at": candidate["published_at"].isoformat()}
        for candidate in candidates[:max_items]
    ]


def _fetch_page(get: GetCallable, page: int) -> list[dict[str, Any]]:
    """Return one page of raw feed rows in the frame's column vocabulary."""
    response = get(
        _FEED_URL,
        params={
            "page": str(page),
            "page_size": str(_PAGE_SIZE),
            "zhibo_id": _ZHIBO_ID,
            "tag_id": "0",
            "dire": "f",
            "dpc": "1",
            "pagesize": str(_PAGE_SIZE),
            "type": "1",
        },
        timeout=15,
    )
    payload = response.json()
    items = payload["result"]["data"]["feed"]["list"]
    if not isinstance(items, list):
        return []
    return [
        {"时间": item.get("create_time"), "内容": item.get("rich_text")}
        for item in items
        if isinstance(item, dict)
    ]


def _match_keywords(
    ticker: str, name: str, aliases: list[str] | None
) -> list[str]:
    """Build the lowercase alias set used to attribute a digest item to a symbol.

    The bare numeric code is deliberately excluded: this is a market-wide feed,
    so a digit run like ``1810`` collides with figures such as "利润暴增1810%".
    Hong Kong codes are matched only in their zero-padded five-digit form, which
    does not occur incidentally.
    """
    keywords: list[str] = []
    symbol = (ticker or "").strip().upper()

    if symbol.endswith(".HK"):
        keywords.append(symbol[:-3].zfill(5))
    elif symbol.endswith((".SS", ".SZ", ".BJ")):
        keywords.append(symbol[:-3])
    elif symbol:
        keywords.append(symbol)

    for value in [name, *(aliases or [])]:
        cleaned = (value or "").strip()
        # One- and two-character names match far too much prose in a digest.
        if len(cleaned) >= 3 or (cleaned and not cleaned.isascii()):
            keywords.append(cleaned)

    seen: set[str] = set()
    unique: list[str] = []
    for keyword in keywords:
        lowered = keyword.lower()
        if lowered and lowered not in seen:
            seen.add(lowered)
            unique.append(lowered)
    return unique


def _row_candidate(
    row: dict[str, Any], keywords: list[str]
) -> dict[str, Any] | None:
    """Normalize one Sina row via the shared candidate builder.

    Attribution requires a hit in the headline, not the body: a digest body
    routinely name-drops unrelated issuers, so a body hit proves nothing.
    """
    title, summary = _split_headline(row.get("内容"))
    if not title:
        return None
    lowered_title = title.lower()
    if not any(keyword in lowered_title for keyword in keywords):
        return None
    return _candidate(
        title=title,
        publisher=_PUBLISHER,
        published_at=_beijing_to_utc(row.get("时间")),
        # The feed exposes no per-item permalink.
        url="",
        summary=summary,
        source_provider=_SOURCE_PROVIDER,
    )


def _split_headline(value: Any) -> tuple[str, str]:
    """Split a ``【标题】正文`` payload into its headline and body."""
    text = str(value or "").strip()
    if not text:
        return "", ""
    match = _HEADLINE_PATTERN.match(text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return text, ""


def _beijing_to_utc(value: Any) -> pd.Timestamp | None:
    """Read a naive Sina timestamp as Beijing time and convert to UTC."""
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(timestamp):
        return None
    if timestamp.tzinfo is None:
        try:
            timestamp = timestamp.tz_localize(_BEIJING_TZ)
        except (TypeError, ValueError):  # Ambiguous or nonexistent local time.
            return None
    return timestamp.tz_convert("UTC")
