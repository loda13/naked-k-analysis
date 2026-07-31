"""Sina rolling-newswire collector for minute-level breaking coverage.

Wraps Sina's global live feed (``akshare.stock_info_global_sina``). Unlike the
per-symbol East Money feed in :mod:`naked_k_news_akshare`, this is a
market-wide digest: every item is scanned against the symbol's aliases, so the
caller must gate it on a title match (see ``_SOURCE_POLICIES``). AkShare is an
optional dependency: when absent, or on any provider failure, the collector
degrades to an empty list so the caller still renders a pure technical report.

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

_BEIJING_TZ = "Asia/Shanghai"
_SOURCE_PROVIDER = "sina"
_PUBLISHER = "新浪财经"

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
    fetch: FetchCallable | None = None,
    loader: LoaderCallable | None = None,
) -> list[dict[str, Any]]:
    """Return normalized, newest-first Sina newswire items mentioning the symbol.

    Sina publishes naive Beijing timestamps and ignores any date range, so
    timestamps are localized explicitly and the lookback window is applied
    client-side.
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

    try:
        if fetch is None:
            fetch = (loader or _load_stock_info_global_sina)()
        frame = fetch()
    except Exception:  # Providers must never abort the caller.
        return []

    if not isinstance(frame, pd.DataFrame):
        return []

    candidates: list[dict[str, Any]] = []
    try:
        for row in frame.to_dict("records"):
            candidate = _row_candidate(row, keywords)
            if candidate is None:
                continue
            if not cutoff <= candidate["published_at"] <= now_utc:
                continue
            candidates.append(candidate)
    except Exception:  # Malformed frames must not abort the caller.
        return []

    candidates.sort(key=lambda item: item["published_at"], reverse=True)
    return [
        {**candidate, "published_at": candidate["published_at"].isoformat()}
        for candidate in candidates[:max_items]
    ]


def _load_stock_info_global_sina() -> FetchCallable:
    """Resolve the AkShare entry point lazily so the dependency stays optional."""
    import akshare

    return akshare.stock_info_global_sina


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
