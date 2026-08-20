# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Scope Rule (read first)

This is a **naked candlestick analysis** tool. Production signal logic works only from OHLCV candles and price structure. Do **not** reintroduce the removed multi-indicator system: no MA/EMA/MACD/RSI/BOLL, no volume-profile advisor, no short/medium/long score engine, no `stock_advisor.py`, no `stock_analysis/` source package. `tests/test_westock_wrapper.py` actively asserts that `westock_wrapper.py` never imports `stock_analysis` — keep it that way.

## Commands

```bash
python -m pip install -r requirements.txt   # pandas, numpy, yfinance, requests

python naked_k_analysis.py 0700.HK          # explicit ticker; multiple tickers are accepted
python naked_k_analysis.py 0700.HK --json   # also emit JSON payload
python naked_k_analysis.py 0700.HK --llm    # optional OpenAI-compatible commentary
python naked_k_analysis.py 0700.HK --news   # optional two-pass news deliberation

python -m unittest discover -v               # all tests
python -m unittest tests.test_naked_k_synthesis -v   # single test module
python -m unittest tests.test_naked_k_synthesis.ClassName.test_method -v   # single test
```

Every module `naked_k_X.py` has a matching `tests/test_naked_k_X.py`. There is no separate lint/build step — `unittest` is the gate. All tests inject fake sessions/data; none hit the live network.

## Architecture

`naked_k_analysis.py` is the CLI orchestrator. It loads data, runs the deterministic engine per ticker, optionally layers LLM commentary and news deliberation, applies portfolio guardrails, and writes reports. It imports the specialized modules rather than owning their logic — read the module a symbol lives in, not this file, to change signal behavior.

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
- `naked_k_config.py` — `RiskConfig`/`PortfolioConfig`/`SmartMoneyConfig`/`TradingConfig` dataclasses loaded from optional JSON (`--config-path`).
- `naked_k_planner.py` — assembles the above into an `InstrumentReport` via `build_trade_plan`.
- `naked_k_smart_money.py` — deterministic OHLCV volume/price proxy rules for accumulation-like behavior and buying/selling exhaustion. Outputs are uncalibrated advisory evidence, not institutional identity or probability.
- `naked_k_backtest.py` — event backtester (bar-by-bar), Walk Forward, R-multiple metrics, market-cycle bucketing, Monte Carlo reshuffle.
- `naked_k_audit.py` — structured JSONL run-audit events (`AuditLogger`).

### Data layer
- `westock_wrapper.py` — yfinance-compatible `download()`. Fallback order: **westock-data CLI → Tencent K line → Yahoo chart JSON → yfinance**. Owns ticker normalization for HK / A-share / BJ / US / KR (rule-based; there is deliberately no hand-maintained ticker table). This fallback chain is behavior-critical and covered by `tests/test_westock_wrapper.py` — change it test-first.
- **Every fetcher must tag `df.attrs['adjustment']`.** Each timeframe calls `load_ohlcv` separately, so all four walk the fallback chain independently and can land on different sources — and therefore different corporate-action bases — within one run. Verified live: Tencent serves A-shares 前复权 under `qfq<period>`, but serves HK under plain `<period>` and ignores the requested mode entirely (`''`/`qfq`/`hfq` return byte-identical rows); that HK series tracks Yahoo's un-adjusted close to a 0.0027% mean across 489 bars spanning two 0700.HK dividends, so it is `split_only`, not `qfq`. Yahoo is `split_only` in both fetchers; the westock CLI exposes no mode and stays `unknown`. `unknown` never counts as a match, including against itself.
- `detect_adjustment_conflict` warns when those bases diverge, because mixing them preserves candle shape while shifting every trigger and stop — a qfq-vs-`split_only` daily comparison reached 8.9% on 600519 and 12.6% on 601398 over 2y. It checks **daily/weekly/monthly only**, because the intraday basis is *unobservable* rather than merely different: the 1h window is ~5 days and the minute endpoint caps at 120 bars (~30 sessions), so no intraday source can reach back past an ex-date, and over that window qfq and un-adjusted closes measured identical to 0.0000%. The minute fetcher therefore reports `unknown`, which never compares equal — including intraday would warn on every A-share every run.
- **Intraday uses a different Tencent endpoint.** `fqkline/get` has no minute data at all (live: `hk00700` m60/m30/m15 return exactly 1 row; `sh688256` returns `code=1`), so requesting `m60` there yielded a stub. Minute bars come from `ifzq.gtimg.cn/appstock/app/kline/mkline` via `fetch_tencent_minute_kline`, which serves **A-shares only** — HK answers `code=-1`, so HK intraday must come from Yahoo. Rows are `[time, open, close, high, low, volume]` (**close before high**) and timestamps are **naive Beijing time**, while Yahoo's intraday index is **naive UTC** (0700.HK's 16:00 close reads 06:07), so the minute fetcher converts to naive UTC — the same 8h skew trap documented for AkShare and Sina.
- **The intraday row gate scales with the requested window (`min_intraday_rows`).** The old flat `MIN_INTRADAY_ROWS = 120` was arithmetically unsatisfiable for production's `period="5d"`: A-shares trade 4h/day and HK ~5.5h, so 5 days hold at most 20 and ~30 hourly bars. It also applied only to westock/Tencent, so a 1-row Yahoo stub was accepted while a 119-row Tencent frame was rejected. The gate now applies to **every** source, and is capped below `TENCENT_MINUTE_MAX_ROWS` — the scaled value for `60d` landed on exactly 120, equal to mkline's hard cap, so one holiday would have re-broken it.
- **Intraday frames are UTC internally, converted to the market's clock only for display.** UTC is what lets Tencent's minute bars (naive Beijing at source) and Yahoo's (naive UTC) share one axis, but it made the report label a 15:00 Beijing close as `07:00` — measured 8h off for CN/HK and 4h for US, a pre-existing defect that predates the minute endpoint. `naked_k_trade._format_ts` takes the zone and `build_intraday_status(market=...)` supplies it; omitting `market` keeps the raw stamp so old callers do not shift. Crypto has no single session and stays UTC.
- `naked_k_trade.classify_market` delegates to `naked_k_portfolio.classify_market`, which is the more complete rule — it maps `.BJ` to `cn` and recognises crypto, whereas `naked_k_analysis.classify_market` returns `us` for `.BJ`. `naked_k_portfolio` imports only `naked_k_config`, so this adds no cycle. Do not add a third copy of this rule.
- **Row counts sent to Tencent are interval-aware and clamped to `TENCENT_MAX_ROWS` (2000).** The cap is a live boundary: `limit<=2000` returns rows, `limit>=2001` returns an empty payload. Counting weekly/monthly bars in trading days made `1mo`/`10y` request 2500, which tripped the cap and silently dropped that one timeframe to Yahoo — the original source of the mixed-basis bug above.

### Optional LLM layers (opt-in, failure must degrade to pure technical output)
- `naked_k_llm.py` — OpenAI-compatible `/chat/completions` commentary (`--llm`). Config via `LLM_BASE_URL`/`LLM_MODEL`/`LLM_API_KEY` (or `NAKED_K_LLM_*`). `safe_generate_llm_commentary` swallows failures.
- `naked_k_news.py` — collects normalized public news (yfinance search + Google News RSS), 7-day main window with 30-day `low_freshness` fallback, dedup, ≤12 items/symbol. No paid API key required.
- `naked_k_news_finnhub.py` — **[v3.2.0]** Finnhub professional financial news collector (SeekingAlpha, Benzinga). Free tier, optional API-key integration with a no-key fallback.
- `naked_k_news_akshare.py` — **[v3.3.0]** AkShare Chinese-language financial news via East Money (`stock_news_em`). No API key. **akshare is an optional dependency and deliberately absent from `requirements.txt`** (it pulls ~14 transitive deps); it is imported lazily and a missing import degrades to `[]`. Three behavior-critical details, all test-covered: HK tickers must be zero-padded to 5 digits (`1810` matches "利润暴增1810%" noise, `01810` does not); publish times are **naive Beijing time** and must be localized before UTC conversion (`naked_k_news._to_utc` would skew them 8h); the endpoint ignores date-range args, so the lookback window is filtered client-side.
- `naked_k_news_sina.py` — Sina 7x24 rolling newswire, the only minute-level source. It is a market-wide digest paged directly (`_PAGE_SIZE=100`, `_MAX_PAGES=20`), so attribution is **headline-only** (`_row_candidate` requires a title hit; a body hit does not qualify) and timestamps are **naive Beijing time**. Its nominal `lookback_days` is not what it delivers: walking all 20 pages spans roughly **one day** (measured 23.7h), so a symbol absent from that window yields zero legitimately — deep history is AkShare's job, not a Sina bug. Judge coverage by `source_provider`, never by the `publisher` label, which is Sina's own `新浪财经` string.
- `naked_k_news_sec.py` — SEC EDGAR material-event filings. Collects **both 8-K and 6-K** (`_MATERIAL_EVENT_FORMS`): domestic issuers file 8-K, foreign private issuers file 6-K and never file 8-K, so 8-K-only returned empty forever for every China ADR (live: PDD 67 6-K / 0 8-K, BABA 339/0, JD 188/0, NIO 268/0). Document URLs use the CIK **unpadded** — `data.sec.gov/submissions` requires the zero-padded 10-digit CIK (unpadded 404s) while `www.sec.gov/Archives` requires it unpadded (padded 301s), so the two must not share one format. Resolving a ticker costs a ~2MB `company_tickers.json` index download, so any ticker containing a **dot** returns empty before any network call (`_is_outside_edgar`). The dot is the general rule, not a denylist of known suffixes: verified against the live index, 0 of 10432 entries contain a dot while 544 contain a hyphen, because SEC spells share classes `BRK-B` and never `BRK.B`. So `.L`/`.T`/`.TO` are covered without enumeration, and hyphenated US classes stay reachable. OTC ADRs (TCEHY, XIACF) have no CIK and are not covered.
- `naked_k_news_enhanced.py` — **[v3.2.0]** Multi-source intelligent merger with relevance scoring, quality weighting (Finnhub 3.0x, AkShare 2.0x, Google 1.0x, Yahoo 0.5x), word-boundary matching, and differentiated time windows. Improves relevant-news ratio from 0% → 71% (Xiaomi 1810.HK live test). Per-provider behavior lives in one table, `_SOURCE_POLICIES` (`_SourcePolicy`: quality weight + `requires_title_match` + `bypasses_gate`), so adding a source is a single entry rather than parallel edits to a weight dict and a gate branch. Finnhub sets `bypasses_gate` (already symbol-scoped); **AkShare sets `requires_title_match`** because East Money mixes in market-wide capital-flow tables whose bodies list every ticker code *and* issuer name, so any body-derived score leaks them. `_relevance_scores` returns title and body scores separately in one pass for this reason — the gate needs the title half alone, and `_TITLE_MATCH_SCORE` / `_BODY_MATCH_SCORE` keep the threshold tied to the weights instead of a bare `>= 3`. Word-boundary matching is ASCII-only — `\b` can never match a 2–3 char CJK name, so 小米/腾讯 would otherwise score 0.
- `naked_k_news_llm.py` — Anthropic-compatible two-pass deliberation (`--news`). Config via `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL` (or `NAKED_K_NEWS_*`).
- `naked_k_synthesis.py` — merges the layers: snapshots the technical conclusion, applies the round-2 action, rebuilds price levels **deterministically** when direction changes, then re-runs risk/portfolio protection.
- `naked_k_ai.py` — deterministic AI-assistant payload: historical edge calibration and failure attribution over engine JSON.

### The two-pass news safety boundary (critical invariant)

The rules that must hold:
- **Round 1** sees news only — never the technical action — and emits a structured news conclusion where every claim cites a collected evidence ID.
- **Round 2** sees the technical snapshot + raw news + round-1 output, and may upgrade or downgrade the action (e.g. 观望→买入 or 买入→回避). There is **no fixed weighting formula**.
- The model must **never invent** candles, prices, triggers, stops, targets, or news sources. When the action's direction flips, triggers/invalidation/risk are rebuilt by deterministic price helpers in `naked_k_synthesis.py`, not by the model.
- Model output never writes back into `naked_k_patterns.py` and never bypasses risk/portfolio guardrails.
- `naked_k_news_llm.py` quarantines instruction-like evidence and redacts config; **no real API key** may appear in code, reports, JSON, audit logs, test fixtures, or exception messages.

## Outputs (gitignored under `reports/`)
- `reports/naked_k_latest.md` — latest Markdown report (`--report-path`)
- `reports/naked_k_journal.jsonl` — review journal; each run replays the previous bar's trigger/invalidation (`--journal-path`)
- `reports/naked_k_audit.jsonl` — structured run audit (`--audit-path`)

The CLI has no ticker allowlist or default pool; every run supplies its symbols explicitly.

## Development Rules
- Add or update tests **before** changing signal behavior (TDD is the repo norm; every module is paired).
- Keep the deterministic core free of indicators and free of LLM writes-back.
- Any optional-layer failure (LLM or news) must fall back to a stable pure-technical report.
- Implementation plans and specs live in `docs/superpowers/`.
- **No test may touch the live network.** `collect_news_enhanced` enables every provider by default, so a new source silently leaks out of every test that forgets to stub it. Stub it in the `only_*` helpers in `tests/test_naked_k_news_enhanced.py`; `NoNetworkMixin` there is the backstop and raises `LiveNetworkAttempt`, which derives from `BaseException` precisely because each collector's `except Exception` fallback would swallow an `AssertionError`.
