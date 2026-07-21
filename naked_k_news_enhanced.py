"""Enhanced news collection with multi-query strategy and company name mapping."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from naked_k_news import collect_news
from naked_k_news_finnhub import collect_finnhub_news


def load_company_names() -> dict[str, dict[str, list[str]]]:
    """Load company name mappings from JSON file."""
    config_path = Path(__file__).parent / "company_names.json"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def collect_news_enhanced(
    name: str,
    ticker: str,
    *,
    now=None,
    lookback_days: int = 7,
    fallback_days: int = 30,
    max_items: int = 12,
    search_factory=None,
    get=None,
    use_finnhub: bool = True,
) -> dict[str, Any]:
    """
    Enhanced news collection with multi-query strategy and Finnhub integration.

    Performs multiple searches using company name variations and merges results.
    Includes Finnhub professional financial news when API key is available.
    Prioritizes high-quality sources and filters by relevance.
    """
    company_names = load_company_names()
    queries = _generate_queries(name, ticker, company_names)

    all_candidates = []
    source_errors_all = []

    # Priority 1: Finnhub (professional financial news, longer lookback)
    if use_finnhub:
        finnhub_lookback = max(lookback_days, 30)  # Extend Finnhub to 30 days
        finnhub_candidates = collect_finnhub_news(
            ticker,
            lookback_days=finnhub_lookback,
            max_items=max_items * 2,
            get=get,
        )
        all_candidates.extend(finnhub_candidates)

    # Priority 2: Multi-query search (Yahoo + Google)
    for query_text in queries[:3]:  # Limit to top 3 queries to avoid rate limits
        result = collect_news(
            name="",  # Empty to use raw query
            ticker=query_text,
            now=now,
            lookback_days=lookback_days,
            fallback_days=fallback_days,
            max_items=max_items * 2,  # Collect more for merging
            search_factory=search_factory,
            get=get,
        )

        # Collect items
        for item in result.get("items", []):
            all_candidates.append({
                "title": item["title"],
                "publisher": item["publisher"],
                "published_at": item["published_at"],
                "url": item["url"],
                "summary": item["summary"],
                "source_provider": item["source_provider"],
            })

        # Collect errors
        if result.get("source_errors"):
            source_errors_all.extend(result["source_errors"])

    # Filter by relevance and apply quality scoring
    import pandas as pd

    # Build keywords for relevance filtering
    keywords = _build_relevance_keywords(name, ticker, company_names)

    # Score and filter candidates
    scored_candidates = []
    for c in all_candidates:
        relevance_score = _calculate_relevance_score(
            c["title"],
            c.get("summary", ""),
            keywords
        )

        # Apply source quality multiplier
        quality_weight = _get_source_quality_weight(c["source_provider"])

        # Calculate final score
        final_score = relevance_score * quality_weight

        # Only keep items with minimum relevance
        if relevance_score >= 1 or c["source_provider"] == "finnhub":
            scored_candidates.append({
                "title": c["title"],
                "publisher": c["publisher"],
                "published_at": pd.Timestamp(c["published_at"]),
                "url": c["url"],
                "summary": c["summary"],
                "source_provider": c["source_provider"],
                "relevance_score": relevance_score,
                "quality_weight": quality_weight,
                "final_score": final_score,
            })

    # Sort by final score (relevance * quality) and recency
    scored_candidates.sort(
        key=lambda x: (x["final_score"], x["published_at"]),
        reverse=True
    )

    # Deduplicate top candidates
    from naked_k_news import _deduplicate
    selected = _deduplicate(scored_candidates, max_items)

    # Build response
    items = [
        {
            "id": f"news-{index:02d}",
            "title": item["title"],
            "publisher": item["publisher"],
            "published_at": item["published_at"].isoformat(),
            "url": item["url"],
            "summary": item["summary"],
            "source_provider": item["source_provider"],
            "freshness": "fresh" if selected else "insufficient",
        }
        for index, item in enumerate(selected, start=1)
    ]

    status = "ok" if items else ("unavailable" if len(source_errors_all) >= 2 else "insufficient")

    return {
        "status": status,
        "name": name,
        "ticker": ticker,
        "as_of": pd.Timestamp.now(tz="UTC").isoformat(),
        "window_days": lookback_days,
        "freshness": "fresh" if items else "insufficient",
        "items": items,
        "source_errors": list(set(source_errors_all)),
        "queries_used": queries[:3],
    }


def _build_relevance_keywords(name: str, ticker: str, company_names: dict) -> list[str]:
    """Build list of keywords for relevance scoring."""
    keywords = []

    # Add ticker
    if ticker:
        keywords.append(ticker.lower())
        # Remove exchange suffix for matching (e.g., "1810" from "1810.HK")
        base_ticker = ticker.split('.')[0]
        if base_ticker != ticker:
            keywords.append(base_ticker)

    # Add company names from mapping
    mapping = company_names.get(ticker, {})

    if "en" in mapping:
        keywords.extend([n.lower() for n in mapping["en"]])

    if "zh" in mapping:
        keywords.extend([n.lower() for n in mapping["zh"]])

    if "keywords" in mapping:
        keywords.extend([k.lower() for k in mapping["keywords"]])

    # Add original name
    if name:
        keywords.append(name.lower())

    return list(set(keywords))  # Remove duplicates


def _calculate_relevance_score(title: str, summary: str, keywords: list[str]) -> float:
    """
    Calculate relevance score for a news item.

    Returns:
        Score >= 3: Highly relevant (keyword in title)
        Score >= 1: Relevant (keyword in summary or partial match)
        Score < 1: Low relevance
    """
    if not keywords:
        return 0.5  # Neutral score if no keywords

    import re

    title_lower = title.lower()
    summary_lower = summary.lower()

    score = 0.0

    for keyword in keywords:
        keyword_lower = keyword.lower()

        # Use word boundary matching for short keywords to avoid false positives
        # (e.g., "mi" matching "million")
        if len(keyword_lower) <= 3 and keyword_lower.isalpha():
            # Word boundary matching for short keywords
            pattern = r'\b' + re.escape(keyword_lower) + r'\b'

            if re.search(pattern, title_lower):
                score += 3.0
            elif re.search(pattern, summary_lower):
                score += 1.0
        else:
            # Substring matching for longer keywords and special characters
            if keyword_lower in title_lower:
                score += 3.0
            elif keyword_lower in summary_lower:
                score += 1.0

    return score


def _get_source_quality_weight(source_provider: str) -> float:
    """
    Get quality weight multiplier for different sources.

    Finnhub: 3.0 (professional financial news)
    Google News: 1.0 (standard)
    Yahoo Finance: 0.5 (high noise ratio)
    """
    weights = {
        "finnhub": 3.0,
        "google_news_rss": 1.0,
        "yahoo_finance": 0.5,
    }
    return weights.get(source_provider, 1.0)


def _generate_queries(name: str, ticker: str, company_names: dict) -> list[str]:
    """
    Generate multiple search queries for better coverage.

    Returns queries in priority order:
    1. English name + ticker
    2. Chinese name + ticker
    3. English name + keywords
    4. Original (fallback)
    """
    queries = []

    # Try to find mapping for this ticker
    mapping = company_names.get(ticker, {})

    # Priority 1: English names
    if "en" in mapping:
        for en_name in mapping["en"]:
            queries.append(f"{en_name} {ticker}")

    # Priority 2: Chinese names
    if "zh" in mapping:
        for zh_name in mapping["zh"]:
            queries.append(f"{zh_name} {ticker}")

    # Priority 3: Keywords
    if "keywords" in mapping and "en" in mapping:
        primary_en = mapping["en"][0]
        for keyword in mapping["keywords"][:2]:  # Top 2 keywords
            queries.append(f"{primary_en} {keyword}")

    # Priority 4: Original query as fallback
    if name and ticker:
        queries.append(f"{name} {ticker}")
    elif ticker:
        queries.append(ticker)

    return queries
