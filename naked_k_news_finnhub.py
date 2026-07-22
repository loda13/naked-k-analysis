"""Finnhub news collector for professional financial news."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from naked_k_news import _as_timestamp, _to_utc


def _load_finnhub_ticker_mapping() -> dict[str, str | None]:
    """Load Finnhub ticker mapping from company_names.json."""
    config_path = Path(__file__).parent / "company_names.json"
    if not config_path.exists():
        return {}

    try:
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)

        # Extract finnhub_ticker mapping
        mapping = {}
        for ticker, info in data.items():
            if "finnhub_ticker" in info:
                mapping[ticker] = info["finnhub_ticker"]

        return mapping
    except Exception:
        return {}


def collect_finnhub_news(
    ticker: str,
    *,
    now=None,
    lookback_days: int = 7,
    max_items: int = 20,
    get: Any = None,
) -> list[dict[str, Any]]:
    """
    Collect company news from Finnhub API.

    Args:
        ticker: Stock ticker symbol (e.g., "1810.HK", "PDD")
        lookback_days: Number of days to look back
        max_items: Maximum number of news items to return
        get: Optional HTTP GET function (for testing)

    Returns:
        List of news items in internal format
    """
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    if max_items <= 0:
        raise ValueError("max_items must be positive")

    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        # No API key, return empty list silently
        return []

    if get is None:
        try:
            import requests
            get = requests.get
        except ImportError:
            return []

    # Map HK tickers to US OTC tickers for Finnhub
    # (Finnhub free tier doesn't support HK exchange)
    ticker_mapping = _load_finnhub_ticker_mapping()
    finnhub_ticker = ticker_mapping.get(ticker, ticker)

    if finnhub_ticker is None:
        # Explicitly marked as unavailable
        return []

    # Calculate date range
    to_date = _to_utc(_as_timestamp(now))
    from_date = to_date - timedelta(days=lookback_days)

    url = "https://finnhub.io/api/v1/company-news"
    params = {
        "symbol": finnhub_ticker,  # Use mapped ticker
        "from": from_date.strftime("%Y-%m-%d"),
        "to": to_date.strftime("%Y-%m-%d"),
        "token": api_key,
    }

    try:
        response = get(url, params=params, timeout=15)
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()

        data = response.json() if hasattr(response, "json") else response

        # Finnhub returns array of news items
        if not isinstance(data, list):
            return []

        candidates = []
        for item in data[:max_items]:
            if not isinstance(item, dict):
                continue

            # Convert Unix timestamp to datetime
            timestamp = item.get("datetime")
            if timestamp:
                try:
                    published_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                except (ValueError, OSError):
                    continue
            else:
                continue

            headline = item.get("headline", "").strip()
            if not headline:
                continue

            candidates.append({
                "title": headline[:300],
                "publisher": item.get("source", "")[:300],
                "published_at": published_at.isoformat(),  # Convert to ISO string
                "url": item.get("url", "")[:500],
                "summary": item.get("summary", "")[:500],
                "source_provider": "finnhub",
            })

        return candidates

    except Exception:
        # Finnhub errors should not abort the caller
        return []


def test_finnhub_connection() -> dict[str, Any]:
    """
    Test Finnhub API connection and return status.

    Returns:
        Dictionary with connection status and details
    """
    api_key = os.getenv("FINNHUB_API_KEY")

    if not api_key:
        return {
            "status": "no_api_key",
            "message": "FINNHUB_API_KEY not found in environment",
            "suggestion": "Register at https://finnhub.io/register and add key to .env",
        }

    try:
        import requests
    except ImportError:
        return {
            "status": "no_requests",
            "message": "requests library not installed",
            "suggestion": "pip install requests",
        }

    # Test with a known ticker
    test_ticker = "AAPL"
    url = "https://finnhub.io/api/v1/company-news"
    params = {
        "symbol": test_ticker,
        "from": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
        "to": datetime.now().strftime("%Y-%m-%d"),
        "token": api_key,
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict) and "error" in data:
            return {
                "status": "api_error",
                "message": data.get("error"),
                "suggestion": "Check API key validity",
            }

        if isinstance(data, list):
            return {
                "status": "ok",
                "message": f"Connection successful, retrieved {len(data)} test items",
                "api_key_prefix": api_key[:8] + "...",
            }

        return {
            "status": "unexpected_response",
            "message": f"Unexpected response type: {type(data)}",
        }

    except requests.exceptions.RequestException as exc:
        return {
            "status": "connection_error",
            "message": str(exc),
            "suggestion": "Check network connection",
        }
    except Exception as exc:
        return {
            "status": "unknown_error",
            "message": str(exc),
        }
