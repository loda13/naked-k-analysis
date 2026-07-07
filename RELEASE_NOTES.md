# v2.1.0 - Naked K Context Enhancements

## Summary

This release deepens the naked K reading layer without bringing indicators back. The report now explains trend structure, pullback depth, volatility state, and volume-price confirmation inside the existing price-action context.

## Added

- Added short-window trend structure classification for upward, downward, and sideways price action.
- Added pullback context based on the latest close against the prior swing high/low range.
- Added volatility state classification for breakout expansion, breakdown expansion, wide-range chop, normal range, and compression.
- Added volume-pressure labels for volume-confirmed breakouts, breakdowns, failed breakouts, downside reclaim, and low-volume breakout warnings.
- Expanded report summaries so trend, pullback, volatility, and volume-pressure details appear in the naked K interpretation.

## Changed

- Updated the trade-plan improvement note to describe enhanced naked K context instead of only shadow, close-position, and prior high/low reading.
- Extended unit coverage for trend confirmation, bullish pullback depth, and volume-pressure reporting.

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
