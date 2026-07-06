# v2.0.0 - Naked K Focus

## Summary

This release converts the project from a mixed technical-indicator advisor into `naked-k-analysis`, a focused naked candlestick analysis CLI.

## Changed

- Renamed the product direction to Naked K Analysis / 裸 K 分析.
- Made `naked_k_analysis.py` the primary and only analysis entry point.
- Extracted candlestick pattern detection into `naked_k_patterns.py`.
- Kept market data fallback in `westock_wrapper.py`.
- Rewrote README and developer notes around naked K analysis only.

## Removed

- Removed the old multi-indicator advisor.
- Removed the old MA/EMA, MACD, RSI, BOLL, value-zone, and score-based analysis modules.
- Removed legacy CLI and tests tied to the indicator advisor.

## Current Coverage

- Naked K pattern detection.
- Price-action structure reading.
- Trigger, invalidation, target, R/R, and position sizing.
- 1H intraday confirmation.
- Journal review and same-bar deduplication.
- Market data fallback through westock-data, Tencent, Yahoo chart, and yfinance.
