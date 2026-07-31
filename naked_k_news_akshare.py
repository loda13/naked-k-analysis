"""AkShare news collector for Chinese-language financial coverage.

Wraps East Money's per-symbol news feed (``akshare.stock_news_em``). AkShare is
an optional dependency: when it is absent, or any provider call fails, the
collector degrades to an empty list so the caller still renders a pure
technical report.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import pandas as pd

from naked_k_news import _as_timestamp, _canonical_url, _clip


FetchCallable = Callable[..., Any]
LoaderCallable = Callable[[], FetchCallable]

_BEIJING_TZ = "Asia/Shanghai"
_TITLE_LIMIT = 300
_SUMMARY_LIMIT = 500
_URL_LIMIT = 500


def collect_akshare_news(
    ticker: str,
    *,
    now: datetime | pd.Timestamp | None = None,
    lookback_days: int = 30,
    max_items: int = 20,
    fetch: FetchCallable | None = None,
    loader: LoaderCallable | None = None,
) -> list[dict[str, Any]]:
    """Return normalized, newest-first Chinese news items for ``ticker``.

    East Money publishes naive Beijing timestamps and ignores any date range,
    so timestamps are localized explicitly and the lookback window is applied
    client-side.
    """
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    if max_items <= 0:
        raise ValueError("max_items must be positive")

    now_utc = _as_timestamp(now)
    cutoff = now_utc - pd.Timedelta(days=lookback_days)

    try:
        if fetch is None:
            fetch = (loader or _load_stock_news_em)()
        frame = fetch(symbol=_akshare_symbol(ticker))
    except Exception:  # Providers must never abort the caller.
        return []

    if not isinstance(frame, pd.DataFrame):
        return []

    candidates: list[dict[str, Any]] = []
    try:
        for row in frame.to_dict("records"):
            candidate = _candidate(row)
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


def _load_stock_news_em() -> FetchCallable:
    """Resolve the AkShare entry point lazily so the dependency stays optional."""
    import akshare

    return akshare.stock_news_em


def _akshare_symbol(ticker: str) -> str:
    """Map a Yahoo-style ticker to the bare code East Money expects.

    Hong Kong codes must be zero-padded to five digits: a bare ``1810`` matches
    unrelated headlines such as "利润暴增1810%", while ``01810`` does not.
    """
    symbol = ticker.strip().upper()
    if symbol.endswith(".HK"):
        return symbol[:-3].zfill(5)
    if symbol.endswith((".SS", ".SZ", ".BJ")):
        return symbol[:-3]
    return symbol


def _candidate(row: dict[str, Any]) -> dict[str, Any] | None:
    title = _clip(str(row.get("新闻标题") or "").strip(), _TITLE_LIMIT)
    published_at = _beijing_to_utc(row.get("发布时间"))
    if not title or published_at is None:
        return None
    return {
        "title": title,
        "publisher": _clip(str(row.get("文章来源") or "").strip(), _TITLE_LIMIT),
        "published_at": published_at,
        "url": _clip(_canonical_url(str(row.get("新闻链接") or "")), _URL_LIMIT),
        "summary": _clip(str(row.get("新闻内容") or "").strip(), _SUMMARY_LIMIT),
        "source_provider": "akshare_em",
    }


def _beijing_to_utc(value: Any) -> pd.Timestamp | None:
    """Read a naive East Money timestamp as Beijing time and convert to UTC."""
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
