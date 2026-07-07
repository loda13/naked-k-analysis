# v3.0.0 - Professional Naked K + AI Trading Assistant

## Summary

This release upgrades the project from a rule-based naked K CLI into a professional trading-assistance system centered on price action, market structure, multi-timeframe context, risk planning, backtesting, and AI-assisted review. The deterministic engine remains the source of truth; AI can explain and challenge the plan, but it cannot change trading signals.

## Added

- Added a market structure engine for swing high/low detection, HH/HL and LH/LL sequences, BOS, CHoCH, and market regime classification.
- Added a multi-timeframe framework: monthly direction, weekly structure, daily opportunity, and 1H trigger/invalidations.
- Added context-aware candle behavior objects for Pin Bar, inside bar, engulfing, liquidity sweep, failed breakout, long-wick rejection, and compression behavior.
- Added professional price zones: supply/demand zones, liquidity pools, volume profile POC/value area, high-volume nodes, and anchored VWAP.
- Added trade setup playbooks for BOS continuation, CHoCH reversal, failed breakout reversal, and compression expansion watch states.
- Added structured risk planning with account risk, position caps, 1R/2R/3R targets, maximum drawdown protection, consecutive-loss protection, and portfolio exposure guardrails.
- Added an event-driven backtest base with next-bar execution, walk-forward windows, R-multiple metrics, Monte Carlo reshuffling, and market-cycle validation.
- Added an AI trading assistant payload with strict signal boundaries, historical edge calibration, failure attribution, and trader-style journal notes.
- Added an OpenAI-compatible LLM adapter for optional `/chat/completions` review output, including local `.env` loading, Markdown fenced JSON parsing, and nonfatal error handling.
- Added structured JSONL audit events for data loading, plan generation, LLM commentary, portfolio exposure, and run completion.

## Changed

- Refactored the previous monolithic analysis flow into focused modules for planning, structure, zones, context, risk, portfolio, backtesting, auditing, LLM integration, and reporting.
- Updated the report language from simple pattern labels to market-behavior explanations, including buyer/seller pressure, failed breakout context, liquidity behavior, and multi-path trade planning.
- Expanded README documentation to cover the new architecture, CLI options, report fields, risk model, backtesting model, AI assistant, and LLM configuration.
- Expanded unit coverage from the original naked K tests to the full V1/V2 workflow, including structure, multi-timeframe analysis, zones, risk, portfolio, backtest, AI, LLM, and audit behavior.

## Security

- API keys are read only from ignored local `.env` files or environment variables; no CLI flag accepts a key.
- `.env` remains ignored by Git and is not part of the release.
- LLM config redaction and error sanitization prevent API keys from appearing in JSON output, audit logs, or failure messages.

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
