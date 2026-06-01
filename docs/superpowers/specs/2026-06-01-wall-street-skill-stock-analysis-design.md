# Wall Street Skill Stock Analysis Design

## Goal

Build a stock analysis engine for this project that uses Wall Street Skill as the primary methodology layer, while keeping the existing moving-average and naked-K systems as local technical engines. The tool must analyze a ticker across short, medium, and long horizons and return a practical investment view: action, confidence, trigger conditions, invalidation line, key risks, and supporting evidence.

This is an analysis aid, not personalized financial advice. Reports must include a short risk disclaimer.

## Current Project Baseline

The repository currently has three executable analysis files:

- `ma_analysis.py`: a large all-in-one technical analyzer. It already computes MA20/60/120, EMA20/60/120, MACD, RSI, Bollinger Bands, Vegas tunnel, Ichimoku, OBV, VWAP, anchored VWAP, volume profile, Fibonacci zones, support/resistance, pullback, fake breakout, fake breakdown, and weekly/daily resonance.
- `naked_k_analysis.py`: a separate price-action analyzer. It detects candle patterns, swing highs/lows, HH/HL or LH/LL structure, support/resistance, key-level reactions, momentum, multi-candle structures, and JSON output.
- `westock_wrapper.py`: a yfinance-compatible wrapper around `westock-data`.

Important gaps:

- The current `4h` path in `ma_analysis.py` uses daily data as a stand-in, so it is not a true short-term 4-hour signal.
- `westock_wrapper.py` contains a hardcoded `/root/.openclaw/.../westock-data` path that is not portable in this workspace.
- Local dependencies are not installed in the default Python environment, so both current scripts fail with missing `pandas` or `yfinance`.
- Existing scoring is mainly indicator aggregation. It does not yet reflect the Wall Street Skill reading order: market stage first, trend context second, indicator state third, entry/exit execution last.
- Long-term analysis is not connected to Wall Street Skill research pages, sector scorecards, bubble-risk dashboard, earnings calendar, or IV event risk.

## Wall Street Skill Inputs

The site has four useful input categories.

### Technical Methodology Pages

Observed technical pages:

- `https://wall-street-skill.com/indicators/rsi`
- `https://wall-street-skill.com/indicators/macd`
- `https://wall-street-skill.com/indicators/bollinger`
- `https://wall-street-skill.com/indicators/vegas`
- `https://wall-street-skill.com/indicators/fibonacci`
- `https://wall-street-skill.com/indicators/ichimoku`
- `https://wall-street-skill.com/indicators/obv`
- `https://wall-street-skill.com/indicators/vwap`
- `https://wall-street-skill.com/indicators/volume-profile`

Methodology rules to encode locally:

- MACD: read zero-axis environment first, histogram expansion/contraction second, line cross last. Treat crosses as rhythm confirmation, not standalone buy/sell triggers.
- RSI: interpret 70/30 only after deciding whether the market is trending or ranging. In a strong trend, overbought/oversold can persist.
- Bollinger Bands: read middle-band direction first, bandwidth second, price position last. Do not mechanically fade upper/lower band touches.
- Vegas tunnel: use EMA144/169 as a long-term mean band and EMA12 as the rhythm filter. A trend candidate requires price and EMA12 to be on the same side of the tunnel.
- Fibonacci: use retracement and extension as reaction zones, not predictions. Add support for 0.886, 1.13, 1.272, and 1.618 in addition to the existing 0.236/0.382/0.5/0.618/0.786.
- Ichimoku: read price relative to cloud first, conversion/base line relationship second, lagging-span confirmation last.
- OBV: focus on direction, structure, and price/volume divergence. Do not use absolute OBV values.
- VWAP/Anchored VWAP: treat the line as market cost basis. Anchor selection must be explicit: major swing low, major swing high, gap, breakout, earnings, or year/month open.
- Fixed Range Volume Profile: use POC, VAH, VAL, and high-volume nodes to define support/resistance, invalidation lines, and profit-taking zones.

### AI Bubble Dashboard

Observed page: `https://wall-street-skill.com/ai%E6%B3%A1%E6%B2%AB%E5%91%A8%E6%8A%A5/`.

The page provides a market-risk layer. The engine should ingest or manually cache:

- Market state and AI bubble phase.
- QQQ upper line, QQQ defense line, SOX upper line, SOX defense line.
- VIX rupture line.
- HY OAS trigger line.
- Sector overheat notes such as AI servers, HBM, AI storage, neocloud, or SOX.
- Scenario rules: continue-up, top-range, early-breakdown.

These values are time-sensitive. The report must show the dashboard snapshot date when available and mark stale data if older than 7 calendar days.

### Deep Research Pages

Observed hub: `https://wall-street-skill.com/research/`.

Research pages provide long-term quality and sector-position inputs:

- Sector and industry map.
- Official ranked list when a ticker appears in a sector page.
- Business purity.
- Moat or indispensability score.
- Commercial validation.
- Financial quality.
- Industry position and long-term space.
- Valuation and odds.
- Risk deduction.
- Final score, rating, and evidence completeness.

The engine should not scrape credentials into the repo. Research data should be cached as JSON under a local cache path that can be refreshed manually or via authenticated browser/session logic. Account credentials must only be provided through environment variables or an interactive login path, never committed.

### Earnings And IV Page

Observed page: `https://wall-street-skill.com/earnings/`.

This page is useful for short-term risk:

- Earnings date.
- Before-open, after-close, or unknown timing.
- EPS estimate.
- Revenue estimate.
- Optional IV/implied move if the page exposes it for the chosen ticker.

The short-term report should downgrade fresh entries before high-uncertainty earnings unless there is a clear event strategy.

## Selected Architecture

Use a modular CLI/report engine, not a web UI in the first version.

The selected design keeps current scripts working while adding a new structured pipeline. This avoids a risky full rewrite of `ma_analysis.py` and allows current CLI users to keep using it.

Version 1 is intentionally smaller than the full architecture:

- Milestone 1: local advisor CLI using fixture/cache files, existing technical functions, naked-K helper output, deterministic methodology rules, and static Wall Street Skill cache lookup.
- Milestone 2: authenticated cache refresh for research, market-risk, and earnings pages.
- Milestone 3: richer provider support, true 4h provider coverage, and broader market/sector automation.

The first implementation must complete Milestone 1 only. It may expose `--refresh-wss-cache`, but the command should fail with a clear `refresh_not_implemented` message until Milestone 2 exists.

Planned module boundaries:

- `stock_analysis/data.py`: ticker normalization, OHLCV fetch, interval selection, provider fallback, and consistent DataFrame schema.
- `stock_analysis/technical.py`: reusable wrappers around the existing MA indicator logic. It should return structured `TechnicalSnapshot` objects rather than print-only output.
- `stock_analysis/naked_k.py`: reusable wrappers around the existing naked-K logic. It should return structured `NakedKSnapshot` objects.
- `stock_analysis/wss_methodology.py`: local Wall Street Skill rule interpretation for MACD, RSI, Bollinger, Vegas, Fibonacci, Ichimoku, OBV, VWAP, and volume profile.
- `stock_analysis/wss_research.py`: cached research lookup by ticker and sector. It should expose `ResearchSnapshot` with score, rank, rating, business purity, moat, catalysts, risks, and cache freshness.
- `stock_analysis/wss_market.py`: cached AI bubble dashboard and broad market risk lookup. It should expose `MarketRiskSnapshot`.
- `stock_analysis/earnings.py`: earnings/IV snapshot lookup.
- `stock_analysis/advisor.py`: combines all snapshots into horizon-specific recommendations.
- `stock_analysis/report.py`: human-readable Chinese report and JSON output.
- `stock_advisor.py`: new CLI entrypoint.

## Data Flow

1. User runs `python stock_advisor.py NVDA --horizons short,medium,long --json`.
2. `data.py` fetches OHLCV for each required timeframe.
3. `technical.py` computes existing technical indicators for 4h/daily/weekly/monthly where data exists.
4. `naked_k.py` computes price action, swing lines, support/resistance, and key-level reactions.
5. `wss_methodology.py` converts raw indicators into Wall Street Skill-style interpretation, using reading-order rules instead of mechanical single-indicator triggers.
6. `wss_research.py` loads cached deep-research metadata for the ticker and sector.
7. `wss_market.py` loads the latest bubble-dashboard risk state.
8. `earnings.py` checks event risk.
9. `advisor.py` produces:
   - Short-term recommendation.
   - Medium-term recommendation.
   - Long-term recommendation.
   - Overall action.
   - Confidence.
   - Trigger conditions.
   - Invalidation line.
   - Position/risk guidance.
10. `report.py` prints a compact Chinese report and optionally JSON.

## Horizon Definitions

Short-term:

- Timeframe: true 4h if available, otherwise daily with explicit fallback warning.
- Decision focus: entry timing, earnings/IV event risk, immediate support/resistance, naked-K reaction, MACD rhythm, Bollinger bandwidth, VWAP/AVWAP cost.
- Typical actions: `短线买入`, `等回踩`, `突破确认后买`, `短线减仓`, `观望`.
- Invalidation line: nearest structural low, AVWAP, POC/VAL, or fake-breakout level.

Medium-term:

- Timeframe: daily plus weekly.
- Decision focus: weekly direction, daily buy/sell point, MA convergence, Vegas tunnel, Ichimoku cloud, Fibonacci reaction zones, volume-profile levels, OBV confirmation.
- Typical actions: `波段买入`, `持有`, `减仓`, `等待日线买点`, `趋势破坏`.
- Invalidation line: weekly key low, cloud break, tunnel break, or volume-profile value-area failure.

Long-term:

- Timeframe: weekly/monthly plus Wall Street Skill research metadata.
- Decision focus: industry position, ranking score, business purity, moat, commercial validation, financial quality, valuation odds, risk deductions, sector/bubble phase.
- Typical actions: `长期核心持有`, `长期观察`, `估值过热等待`, `回避`.
- Invalidation line: research thesis failure, sector bubble risk trigger, fundamentals deterioration, or long-term technical trend break.

## Recommendation Model

The advisor should use a layered scoring model:

1. Market risk gate:
   - If VIX, HY OAS, QQQ/SOX defense lines, or bubble dashboard state indicate rupture, cap long-only recommendations and favor defense.
   - If market is strong but locally overheated, allow holds but penalize chase entries.

2. Long-term quality gate:
   - Strong sector ranking and high evidence completeness support long-term hold/buy.
   - Low business purity, weak evidence, or high risk deduction caps long-term rating.

3. Trend context:
   - Weekly direction defines the medium-term bias.
   - Daily/4h define execution timing.

4. Indicator interpretation:
   - MACD, RSI, Bollinger, Vegas, Ichimoku, OBV, VWAP, volume profile, and Fibonacci are interpreted in Wall Street Skill reading order.
   - Single indicators cannot directly override market-risk or trend-context gates.

5. Naked-K confirmation:
   - Naked-K lines are auxiliary confirmation for entry, invalidation, and profit-taking.
   - Price action can upgrade confidence when it confirms the same direction as the technical context.
   - Price action can block a trade when it shows failed breakout, bearish engulfing near resistance, or breakdown of key structure.

Version 1 deterministic thresholds:

- Market risk:
  - `rupture` if any cached market rule has `status: rupture`, or if the ticker belongs to an overheated sector and the cached market state is `触发防守`.
  - `overheated` if market state is `警戒观察` or sector note contains the ticker's mapped sector.
  - `supportive` if market state is `趋势仍强` and no sector-specific overheat note applies.
- Research quality:
  - `strong` if score is at least 80 and evidence completeness is `A` or `A-`.
  - `acceptable` if score is at least 68 and evidence completeness is `B+` or better.
  - `weak` if score is below 68, evidence is below `B+`, or the ticker is in an avoid list.
  - `missing` if no cached research entry exists.
- Technical direction:
  - `bullish` if weekly direction is bullish and daily score is positive.
  - `bearish` if weekly direction is bearish or daily score is below -1.
  - `neutral` otherwise.
- Final action:
  - `买入`: market is supportive or overheated, research is strong or acceptable, technical direction is bullish, and no earnings warning blocks fresh entries.
  - `小仓试错`: research is strong or acceptable, technical direction is neutral-to-bullish, and naked-K shows a nearby invalidation line.
  - `持有`: research is strong or acceptable, but entry timing is not favorable.
  - `减仓`: market is rupture-like or technical direction is bearish while long-term research is still acceptable.
  - `卖出`: market is rupture-like and technical direction is bearish.
  - `观望`: research is missing or stale, or signals conflict.
  - `回避`: research is weak or ticker appears in an avoid list.

Recommended output fields:

- `overall_action`: one of `买入`, `小仓试错`, `持有`, `减仓`, `卖出`, `观望`, `回避`.
- `short_term_action`
- `medium_term_action`
- `long_term_action`
- `confidence`: `低`, `中`, `高`.
- `position_guidance`: `空仓等待`, `轻仓`, `标准仓`, `只持有不加仓`, `降低高 beta`.
- `entry_triggers`: concrete price/indicator conditions.
- `invalidation`: concrete condition that proves the trade wrong.
- `upside_zones`: next resistance or target zones.
- `downside_zones`: key support/risk zones.
- `evidence`: concise reasons grouped by market, research, technical, naked-K, earnings.
- `warnings`: stale data, provider fallback, missing research, missing true 4h data, earnings uncertainty.

## CLI Shape

Initial CLI:

```bash
python stock_advisor.py NVDA
python stock_advisor.py NVDA --horizons short,medium,long
python stock_advisor.py NVDA --json
python stock_advisor.py NVDA --refresh-wss-cache
python stock_advisor.py 0700.HK --market hk --horizons medium,long
```

Default behavior:

- Runs all three horizons.
- Prints a compact Chinese report.
- Includes data freshness and external research freshness.
- Does not require site login unless `--refresh-wss-cache` is requested.

## Caching And Credentials

No Wall Street Skill email, password, cookies, or tokens may be committed.

Cache files are runtime artifacts and must not be committed. The repository should ignore:

- `data/cache/`
- `.wss-session/`
- any browser cookie export or login artifact

Tests may use sanitized fixtures under `tests/fixtures/wss/`. Fixtures must contain only hand-written or reduced public/derived values, never raw member-only page dumps, cookies, passwords, or session tokens.

Cache layout:

- `data/cache/wss/research.json`: ticker and sector research snapshots.
- `data/cache/wss/market_risk.json`: AI bubble dashboard snapshot.
- `data/cache/wss/earnings.json`: earnings calendar snapshot.

Credential handling:

- Interactive browser login is acceptable for manual refresh.
- Environment variables are acceptable for automated refresh:
  - `WSS_EMAIL`
  - `WSS_PASSWORD`
- The implementation must not print these values.
- Cache files should contain derived research facts and timestamps, not raw credentials or cookies.

Milestone 1 refresh behavior:

- `--refresh-wss-cache` should exit non-zero and print a short Chinese message saying authenticated refresh is not implemented yet.
- Normal advisor runs should read existing cache files if present.
- If cache files are missing, the advisor should continue with technical-only analysis and cap confidence at `中`.

## Error Handling

The report should continue with partial data when possible:

- If true 4h data is unavailable, fall back to daily and add a warning.
- If research cache is missing, still provide technical and naked-K analysis, but mark long-term recommendation as lower confidence.
- If market-risk cache is stale, do not block analysis, but cap confidence at medium.
- If earnings data is missing, add a warning only for short-term analysis.
- If all price providers fail, return a clear `no_data` error.

## Testing Strategy

Focused tests should cover:

- Ticker normalization for US, HK, A-share, and already-normalized provider codes.
- Indicator interpretation rules for MACD zero-axis, histogram expansion, and crosses.
- RSI interpretation in trend and range contexts.
- Bollinger interpretation for trend-walk versus range fade.
- Advisor behavior when market risk is strong, overheated, and rupture-like.
- Advisor behavior when research score is high, missing, stale, or weak.
- Naked-K support/resistance integration into invalidation and target zones.
- JSON report schema stability.
- Cache safety: runtime cache paths are ignored by git, and fixture paths remain allowed.
- Existing CLI compatibility smoke tests for `ma_analysis.py --json` and `naked_k_analysis.py --json`, using monkeypatched or fixture data rather than live network calls.
- `--refresh-wss-cache` Milestone 1 behavior: clear unsupported message and non-zero exit.

Use small fixture DataFrames for deterministic unit tests. Do not rely on live network data in default tests.

## Implementation Boundaries

First implementation should deliver a working CLI and JSON output. It should not build a web UI, portfolio tracker, alert system, live broker integration, or automated trading.

Existing scripts should keep running. New modules can import existing functions where practical, but the new advisor path should prefer structured return values over parsing printed output.

## Open Decisions

The selected defaults are:

- Start with a CLI/report engine.
- Use Wall Street Skill methodology as the main decision framework.
- Keep moving averages and naked K as local execution/confirmation engines.
- Treat Wall Street Skill research and market-risk pages as cached external context.
- Avoid storing credentials in the repository.

These are sufficient to start implementation planning.
