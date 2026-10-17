# Dual Moving Average Analysis Developer Notes

The user approved a transition from naked-candlestick-only analysis to daily swing trend assessment on 2026-09-06. The investment horizon is several weeks to several months. Keep the `naked_k_analysis.py` CLI name for continuity.

On 2026-09-29 the user requested broad technical-indicator and price-pattern coverage in a text-only report for their own judgment. No charts. This observation layer remains advisory and separately versioned; it never changes trade actions or risk budgets.

On 2026-10-17 the user requested the YouTube 以太坊教授幣哥 dual-MA system as the sole trade-decision path and confirmed stock daily bars. Current rule version is `bige-dual-ma-v1`; source mapping, engineering assumptions and migration are in `docs/dual-ma-system.md`. The previous v2 signal rules are retired.

## Scope

- `naked_k_trend.py`: shared MA/EMA20/60/120 compression, breakout, first-pullback, target and stop rules; legacy indicator calculations remain advisory only.
- `naked_k_observations.py`: broad indicators, causal text-only pattern observations and bullish/bearish/conflicting evidence. Definitions and thresholds: `docs/technical-observations.md`.
- `naked_k_zones.py`: confirmed structural support/resistance and explicit-anchor HLC3-volume VWAP approximation.
- `naked_k_verification.py`: read-only multi-timeframe MA comparison, candidate rising-leg retracement and data/anchor checks. Report it after the main plan; it never changes actions, stops, targets or budgets.
- `naked_k_planner.py`: conditional plans, existing-position handling and proposed portfolio budgets.
- `naked_k_risk.py`, `naked_k_portfolio.py`, `naked_k_config.py`: validated risk and optional read-only account state.
- `naked_k_analysis.py`: CLI, market data checks, factual news appendix, Markdown/JSON/journal/audit.
- `naked_k_backtest.py`: offline long/cash replay using the exact same trend and entry functions, explicit costs, daily marked equity and comparisons.
- `westock_wrapper.py`: westock CLI -> Tencent -> Yahoo chart -> yfinance; preserve ticker normalization, adjustment metadata, UTC-internal minute data and provider limits.

## Rules

- Automatically use ponytail full for coding tasks. Prefer existing pandas/numpy and stdlib; no broad indicator frameworks or duplicated scoring engines.
- Add failing tests before changing signal or risk behavior. Tests never use the live network.
- Preserve data quality, closed-bar checks, cross-timeframe adjustment warnings and UTC timestamp regressions.
- Use only data available at the signal timestamp. Channels exclude the signal bar; structural pivots are available only after confirmation.
- Rule version `bige-dual-ma-v1`: require 120 closed bars for all six averages; no short-history substitute. Only compression breakout confirmation or the first qualifying MA20-band pullback can create candidates. Do not restore EMA50/200, ADX, volume or Donchian entry filters. Keep source concepts separate from engineering thresholds in `naked_k_config.py`.
- Backtest production warmup is at least 120 bars. Keep targets fixed after entry; retain the entry-specific stop family and use conservative stop-first ordering on ambiguous intraday bars. Mark EMA50/200 comparisons unavailable if EMA200 is missing at the initial signal; never report a cash-only curve as a valid unavailable benchmark. Report mode changes using only each signal's available prefix.
- Trend strength is not direction, a risk multiple is not a target prediction, and a rule threshold is not a calibrated probability.
- Observation indicators must not vote on or mutate trade actions or risk budgets. Pattern confirmation means the documented geometry/price rule was met, not that a trade will profit. Oversold is not an automatic buy; volume proxies cannot identify institutions. Keep missing/insufficient values explicit.
- Retracement, starting lows and 1h/4h/weekly context cross-check the dual-MA judgment; they are not a replacement report or a second strategy. Show supporting evidence, conflicts and unavailable data. Automatic weekly extremes are candidate anchors, not an assertion of the author's chosen wave. Never mix price drawdown with retracement of a rise, incompatible adjustments or incomplete hourly sessions.
- News contains source/date/title metadata only and must never alter technical actions; failure must preserve the technical report. Do not restore LLM direction synthesis or institutional-flow inference.
- Unknown account holdings or drawdown are not zero. Proposed budgets are not actual exposure; defensive actions never open shorts.
- Backtest uses next-open execution, adverse slippage, costs and multi-day positions. No fills at stale trigger prices, fake final liquidation or trade-count-scaled Sharpe.
- Do not claim investment effectiveness from passing unit tests or synthetic market fixtures. Real economic validation requires disclosed samples, costs and out-of-sample comparisons.
- Keep new research artifacts in `reports/`; append journal records without deleting historical schemas or reports.

## Commands

```bash
python naked_k_analysis.py 0700.HK
python naked_k_analysis.py 0700.HK TSLA --news --json
python naked_k_analysis.py 0700.HK --account-path account.json
python -m unittest discover -v
```

Current design and source rules: `docs/dual-ma-system.md`.

Historical design: `docs/superpowers/specs/2026-09-06-technical-trend-streamline-design.md`.
Short-history extension: `docs/superpowers/specs/2026-09-06-short-history-trend-design.md`.
Implementation ledger: `docs/superpowers/plans/2026-09-06-technical-trend-streamline.md`.
Earlier v1/v2 specs describe retired signal systems and are retained as history, not current product requirements.
