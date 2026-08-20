# Naked K Analysis Developer Notes

This repository is now focused only on naked candlestick analysis. Do not reintroduce the removed indicator advisor system.

## Main Entry

`naked_k_analysis.py`
- CLI entry point.
- Requires one or more positional ticker symbols; there is no default pool or allowlist.
- Loads daily, weekly, and optional 1H OHLCV data.
- Builds naked K trade plans with trigger, invalidation, target, R/R, position guidance, intraday status, and journal review.
- Writes Markdown reports and JSON payloads.

## Core Modules

`naked_k_patterns.py`
- Pure candlestick pattern detection.
- Owns engulfing, Pin Bar, doji, hammer, shooting star, morning/evening star, and inside bar logic.
- Must remain indicator-free.

`westock_wrapper.py`
- Market data adapter.
- Provides a yfinance-compatible `download()` function.
- Fallback order: westock-data CLI, Tencent K line, Yahoo chart JSON, yfinance.
- Owns ticker normalization for HK, A-share, BJ, and US tickers.

## Removed Scope

The old multi-indicator system has been removed:

- No MA/EMA advisor.
- No MACD/RSI/BOLL/volume-profile advisor.
- No short/medium/long score engine.
- No `stock_advisor.py`.
- No `stock_analysis/` package.

Future work should improve K-line reading, trigger discipline, journaling, and report quality.

## Commands

Run the naked K report:

```bash
python naked_k_analysis.py 0700.HK
python naked_k_analysis.py 0700.HK --json
```

Run all tests:

```bash
python -m unittest discover -v
```

Run focused tests:

```bash
python -m unittest tests.test_naked_k_analysis -v
python -m unittest tests.test_naked_k_patterns -v
python -m unittest tests.test_westock_wrapper -v
```

## Development Rules

- Keep production logic centered on OHLCV candles and price structure.
- Add tests before changing signal behavior.
- Keep data-fetch fallback behavior covered by `tests/test_westock_wrapper.py`.
- Do not add broad indicator frameworks back into the project.
- Keep generated reports under `reports/`.

## Important Outputs

- Latest report: `reports/naked_k_latest.md`
- Journal: `reports/naked_k_journal.jsonl`
- Implementation plans: `docs/superpowers/plans/`
