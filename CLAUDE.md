# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Scope Rule (read first)

This is a **naked candlestick analysis** tool. Production signal logic works only from OHLCV candles and price structure. Do **not** reintroduce the removed multi-indicator system: no MA/EMA/MACD/RSI/BOLL, no volume-profile advisor, no short/medium/long score engine, no `stock_advisor.py`, no `stock_analysis/` source package. `tests/test_westock_wrapper.py` actively asserts that `westock_wrapper.py` never imports `stock_analysis` — keep it that way.

## Commands

```bash
python -m pip install -r requirements.txt   # pandas, numpy, yfinance, requests

python naked_k_analysis.py                   # run report over default ticker pool
python naked_k_analysis.py --json            # also emit JSON payload
python naked_k_analysis.py --llm             # optional OpenAI-compatible commentary
python naked_k_analysis.py --news            # optional two-pass news deliberation

python -m unittest discover -v               # all tests
python -m unittest tests.test_naked_k_synthesis -v   # single test module
python -m unittest tests.test_naked_k_synthesis.ClassName.test_method -v   # single test
```

Every module `naked_k_X.py` has a matching `tests/test_naked_k_X.py`. There is no separate lint/build step — `unittest` is the gate. All tests inject fake sessions/data; none hit the live network.

## Architecture

`naked_k_analysis.py` is the CLI orchestrator (~1200 lines). It loads data, runs the deterministic engine per ticker, optionally layers LLM commentary and news deliberation, applies portfolio guardrails, and writes reports. It imports the specialized modules rather than owning their logic — read the module a symbol lives in, not this file, to change signal behavior.

The engine is organized as a **deterministic core** plus **optional LLM layers** that may reinterpret but never fabricate.

### Deterministic core (must stay indicator-free, price/structure only)
- `naked_k_patterns.py` — pure candlestick pattern detection (engulfing, Pin Bar, doji, hammer/shooting star, morning/evening star, inside bar). No indicators, ever.
- `naked_k_structure.py` — swing points, HH/HL/LH/LL, BOS/CHoCH, market regime classification.
- `naked_k_zones.py` — supply/demand zones, liquidity pools, POC/value area via swing clustering.
- `naked_k_setups.py` — classifies price behavior into replayable setups (BOS continuation, CHoCH reversal, fakeout, compression).
- `naked_k_timeframes.py` — monthly/weekly/daily/1H multi-timeframe context and conflict filtering.
- `naked_k_trade.py` — the largest core module: triggers, invalidation, ATR buffers, R/R metrics, position guidance, intraday status, candle classification, and most Markdown summary formatters.
- `naked_k_risk.py` — per-trade + account risk plan (1R/2R/3R, drawdown protection, consecutive-loss de-risking).
- `naked_k_portfolio.py` — aggregate exposure (direction/market/symbol/account) and guardrails when limits are exceeded.
- `naked_k_context.py` / `naked_k_interpreter.py` — contextualized candle-behavior objects and the trader-style brief (narrative, not "indicator crossed").
- `naked_k_config.py` — `RiskConfig`/`PortfolioConfig`/`TradingConfig` dataclasses loaded from optional JSON (`--config-path`).
- `naked_k_planner.py` — assembles the above into an `InstrumentReport` via `build_trade_plan`.
- `naked_k_backtest.py` — event backtester (bar-by-bar), Walk Forward, R-multiple metrics, market-cycle bucketing, Monte Carlo reshuffle.
- `naked_k_audit.py` — structured JSONL run-audit events (`AuditLogger`).

### Data layer
- `westock_wrapper.py` — yfinance-compatible `download()`. Fallback order: **westock-data CLI → Tencent K line → Yahoo chart JSON → yfinance**. Owns ticker normalization for HK / A-share / BJ / US / KR. This fallback chain is behavior-critical and covered by `tests/test_westock_wrapper.py` — change it test-first.

### Optional LLM layers (opt-in, failure must degrade to pure technical output)
- `naked_k_llm.py` — OpenAI-compatible `/chat/completions` commentary (`--llm`). Config via `LLM_BASE_URL`/`LLM_MODEL`/`LLM_API_KEY` (or `NAKED_K_LLM_*`). `safe_generate_llm_commentary` swallows failures.
- `naked_k_news.py` — collects normalized public news (yfinance search + Google News RSS), 7-day main window with 30-day `low_freshness` fallback, dedup, ≤12 items/symbol. No paid API key required.
- `naked_k_news_finnhub.py` — **[v3.2.0]** Finnhub professional financial news collector (SeekingAlpha, Benzinga). Free tier, optional, zero-config fallback.
- `naked_k_news_enhanced.py` — **[v3.2.0]** Multi-source intelligent merger with relevance scoring, quality weighting (Finnhub 3.0x, Google 1.0x, Yahoo 0.5x), word-boundary matching, and differentiated time windows. Improves relevant-news ratio from 0% → 71% (Xiaomi 1810.HK live test).
- `naked_k_news_llm.py` — Anthropic-compatible two-pass deliberation (`--news`). Config via `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL` (or `NAKED_K_NEWS_*`).
- `naked_k_synthesis.py` — merges the layers: snapshots the technical conclusion, applies the round-2 action, rebuilds price levels **deterministically** when direction changes, then re-runs risk/portfolio protection.
- `naked_k_ai.py` — deterministic AI-assistant payload: historical edge calibration and failure attribution over engine JSON.

### The two-pass news safety boundary (critical invariant)

Design doc: `docs/superpowers/specs/2026-07-20-news-two-pass-deliberation-design.md`. The rules that must hold:
- **Round 1** sees news only — never the technical action — and emits a structured news conclusion where every claim cites a collected evidence ID.
- **Round 2** sees the technical snapshot + raw news + round-1 output, and may upgrade or downgrade the action (e.g. 观望→买入 or 买入→回避). There is **no fixed weighting formula**.
- The model must **never invent** candles, prices, triggers, stops, targets, or news sources. When the action's direction flips, triggers/invalidation/risk are rebuilt by deterministic price helpers in `naked_k_synthesis.py`, not by the model.
- Model output never writes back into `naked_k_patterns.py` and never bypasses risk/portfolio guardrails.
- `naked_k_news_llm.py` quarantines instruction-like evidence and redacts config; **no real API key** may appear in code, reports, JSON, audit logs, test fixtures, or exception messages.

## Outputs (gitignored under `reports/`)
- `reports/naked_k_latest.md` — latest Markdown report (`--report-path`)
- `reports/naked_k_journal.jsonl` — review journal; each run replays the previous bar's trigger/invalidation (`--journal-path`)
- `reports/naked_k_audit.jsonl` — structured run audit (`--audit-path`)

Default ticker pool: `0700.HK`, `1810.HK`, `PDD`, `9992.HK`.

## Development Rules
- Add or update tests **before** changing signal behavior (TDD is the repo norm; every module is paired).
- Keep the deterministic core free of indicators and free of LLM writes-back.
- Any optional-layer failure (LLM or news) must fall back to a stable pure-technical report.
- Implementation plans and specs live in `docs/superpowers/`.

Note: `AGENTS.md` is a stale copy describing an older 3-module layout — prefer this file.
