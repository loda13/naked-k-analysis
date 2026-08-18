# Smart Money Phase 4 Economic Qualification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在积累足够 point-in-time 历史后，用冻结协议验证成交代理 A、价格响应 B 和 A∩B 是否具有可重复的样本外增量；未达到数据或统计门槛时只返回 `NOT_COMPUTABLE`/`UNVALIDATED`，不升级为概率或交易输入。

**Architecture:** Phase 4 是独立 research subsystem，只读取 Phase 0–3 的 immutable snapshots、evidence lineage 和当时可见 OHLCV prefix，不修改在线报告生成链路。流水线依次构造事件表、收益/风险标签、匹配基线、purged walk-forward 窗口和统计结果，最后由一个纯资格 gate 决定是否保持 `UNVALIDATED`。本计划只评估 Phase 0–3 预注册的唯一规则集，不做阈值搜索；研究产物 content-addressed 并保留协议版本与输入 ID。

**Tech Stack:** Python 3.14、pandas、numpy、标准库 `dataclasses` / `enum.StrEnum` / `hashlib` / `json` / `pathlib` / `statistics`、`unittest`。

**Spec:** [`docs/superpowers/specs/2026-08-17-smart-money-dual-evidence-design.md`](../specs/2026-08-17-smart-money-dual-evidence-design.md) §13 and §14 Phase 4.

## Global Constraints

- 此计划不能在 Phase 0–3 未完成、snapshot lineage 未验收前启动真实研究。
- 免费逐笔从上线日起积累；禁止用当前截面、日线成交量或随机生成数据补造历史逐笔事件。合成数据仅用于单元测试算法，不进入资格报告。
- 至少需要 3 年训练 + 6 个月验证 + 6 个月测试；不足时整个资格状态为 `NOT_COMPUTABLE/INSUFFICIENT_HISTORY`。
- 事件、结构、分位阈值、周/月线都只能使用各自 `available_at` 当时可见的数据。
- benchmark 固定 `^HSI`；缺失值保持 `NOT_COMPUTABLE`，不得填零或改用临时替代指数。
- 同日 `+1R/-1R` 都触及且没有 point-in-time 1H 数据时，precision 按失败；不能根据日线收盘猜先后。
- 全部 OOS 结果按 ticker 和时间排序；测试窗前后各 embargo 20 个交易日，跨边界最长 20 日标签必须 purge。
- 置信区间按 ticker-month block bootstrap 10,000 次；多 kind 同时检验使用 Benjamini-Hochberg FDR 5%。
- A=`trade_flow`，B=`price_response`；同源 OHLCV volume 不得被包装成第二层独立证据。
- Phase 0–3 阈值以唯一 `phase0-rules.v1` 预注册并在所有窗口冻结；若未来要增加候选阈值，必须另增 point-in-time `SessionFeature/CandidateEventSet` 规格，不能用已触发 evidence 反推。
- 达不到所有升级门槛时保留 `UNVALIDATED / ADVISORY_ONLY`；本计划不授权修改 action、position 或 exposure。
- 每个任务先 RED、再最小实现、再 GREEN、再独立提交；所有研究随机过程固定 seed 并写入产物。

## File Responsibility Map

| 文件 | 单一职责 |
|---|---|
| `naked_k_smart_money_research_contracts.py` | event/outcome/fold/result/qualification 的 versioned dataclass |
| `naked_k_smart_money_research_dataset.py` | point-in-time lineage 加载、事件去重、基础可用 session universe |
| `naked_k_smart_money_outcomes.py` | 5/10/20 日 excess return、MFE/MAE、1R precision labels |
| `naked_k_smart_money_matching.py` | 同 ticker/年/结构/振幅分位的一对一最近日期 matched baseline |
| `naked_k_smart_money_walk_forward.py` | 3y/6m/6m 滚动、purge/embargo、预注册规则绑定与 comparator 冻结 |
| `naked_k_smart_money_statistics.py` | ticker-month block bootstrap、BH-FDR、coverage/precision/lift |
| `naked_k_smart_money_qualification.py` | A、B、A∩B ablation 和固定升级 gate |
| `run_smart_money_event_study.py` | 离线研究 CLI、content-addressed artifacts、机器可读退出状态 |

---

### Task 0: Qualification Readiness Gate

**Files:**
- Create: `naked_k_smart_money_research_contracts.py`
- Create: `tests/test_naked_k_smart_money_research_contracts.py`
- Create: `tests/fixtures/smart_money/research/protocol.v1.json`

**Interfaces:**
- Consumes: protocol constants and a catalog of immutable snapshots/evidence.
- Produces: exact research contracts plus `assess_research_readiness()`.

```python
@dataclass(frozen=True)
class ResearchReadiness:
    status: str  # READY | NOT_COMPUTABLE
    reason_codes: tuple[str, ...]
    first_available_session: str | None
    last_available_session: str | None
    complete_years: float
    eligible_tickers: tuple[str, ...]

def assess_research_readiness(
    catalog: Sequence[Mapping[str, Any]],
    *,
    protocol: ResearchProtocol,
) -> ResearchReadiness: ...
```

- [ ] **Step 1: Write failing schema/readiness tests.**

Lock `research-protocol.v1`, `smart-money-event.v1`, `smart-money-outcome.v1`, `walk-forward-fold.v1`, `qualification-result.v1`. Test 3y+6m+6m exact boundary, one missing month, missing/tampered trade-flow, OHLCV, evidence-bundle or config ID, incomplete `^HSI` label coverage, synthetic-source marker and fewer than one eligible ticker.

- [ ] **Step 2: Run tests to confirm RED.**

```bash
python -m unittest tests.test_naked_k_smart_money_research_contracts -v
```

- [ ] **Step 3: Implement immutable contracts and fail-closed readiness.**

The protocol fixture fixes benchmark, horizons, R definition, matching keys, rolling windows, embargo, bootstrap repetitions/seed, FDR and qualification gates. `assess_research_readiness()` rejects any catalog row lacking verified trade-flow, point-in-time OHLCV, evidence-bundle and configuration IDs, any referenced digest that cannot be resolved, or any row marked synthetic. `^HSI` coverage must span every candidate label window; 1H may be absent because same-day double-touch then fails conservatively.

Freeze these choices in `ResearchProtocol` and its golden fixture rather than leaving them to implementers:

```text
cohort A       = formal directional trade-flow events on the eligible session universe
cohort B       = formal directional price-action events containing price_response dependency
cohort A_AND_B = same-direction, time-aligned A and B on the same decision session
```

The cohorts are non-exclusive; A_AND_B is a subset view, not an “independent source” claim. All three use the same base eligible ticker-session denominator and the same five-session direction dedup rule.

`ResearchProtocol.threshold_set_id` is fixed to the single pre-registered `phase0-rules.v1`; its exact rule versions and numeric boundaries are content-addressed in the fixture. Train, validation and test all bind that same ID. There is no candidate ranking, retuning, validation rejection or fallback in this plan; a code/config mismatch is `INVALID/PROTOCOL_MISMATCH`.

Validation also freezes the strongest single layer: rank A versus B by the same worst-direction precision-lift objective, then 10-day excess, then lexical cohort name. Test compares A_AND_B only with that preselected single layer.

For positive hypotheses use one-sided block-bootstrap p-values with plus-one correction: `(1 + count(draw_stat <= 0)) / (repetitions + 1)`; percentile 2.5/97.5 gives the reported two-sided 95% CI. Within each fold, one BH family `{protocol_id}:{fold_id}` contains (a) every evidence kind × cohort A/B/A_AND_B hypothesis for `precision_lift` and `excess_10d`, plus (b) every A_AND_B-versus-validation-frozen-single `dual_increment` contrast. Pooled OOS inference repeats the same family definition under `{protocol_id}:pooled-oos` after event-ID deduplication. MFE, MAE, coverage and 5/20-day returns are descriptive and excluded from FDR. Each event/control pair remains atomic inside its `(ticker, YYYY-MM)` resampled block.

“Three windows consistent” means A_AND_B has positive point estimates for both matched precision lift and 10-day directional excess in each of the latest three complete test folds. The pooled OOS dual increment gate compares A_AND_B with the validation-selected strongest single layer over the dual-observable session universe; its block-bootstrap precision-difference 95% lower bound must be greater than zero. This is in addition to the pooled matched precision lift ≥5pp with lower bound >0 and pooled 10-day excess lower bound >0.

- [ ] **Step 4: Run tests and commit.**

```bash
python -m unittest tests.test_naked_k_smart_money_research_contracts -v
git add naked_k_smart_money_research_contracts.py tests/test_naked_k_smart_money_research_contracts.py tests/fixtures/smart_money/research/protocol.v1.json
git diff --cached --check
git commit -m "feat: gate smart-money economic research readiness" -m "Constraint: No qualification without complete point-in-time history
Confidence: high
Scope-risk: narrow"
```

---

### Task 1: Point-in-Time Event Dataset

**Files:**
- Create: `naked_k_smart_money_research_dataset.py`
- Create: `tests/test_naked_k_smart_money_research_dataset.py`
- Create: `tests/fixtures/smart_money/research/point_in_time_events.v1.json`

**Interfaces:**
- Consumes: accepted Phase 0–3 snapshots, evidence/fusion artifacts, daily OHLCV and normalized market-structure state.
- Produces: `build_session_universe()` and `build_point_in_time_events()`.

```python
def build_session_universe(
    snapshots: Sequence[TradeFlowSnapshot],
    ohlcv_by_ticker: Mapping[str, pd.DataFrame],
    *,
    calendar: TradingCalendar,
) -> pd.DataFrame: ...

def build_point_in_time_events(
    artifacts: Sequence[Mapping[str, Any]],
    session_universe: pd.DataFrame,
    *,
    protocol: ResearchProtocol,
) -> tuple[SmartMoneyEvent, ...]: ...
```

- [ ] **Step 1: Write failing no-lookahead tests.**

Append future OHLCV and future evidence to the fixture and require all prior event IDs/fields unchanged. Assert `signal_at`, `available_at`, `tradable_at`, input IDs, dependency groups and pre-entry structure are retained; resampled weekly/monthly values use only daily prefixes visible at `available_at`.

- [ ] **Step 2: Write failing event-dedup and universe tests.**

Same ticker/direction within five trading sessions keeps earliest tradable event; reverse direction survives. Sessions with suspension, non-HKD counter, incomplete tape or missing base OHLCV are excluded from the coverage denominator with explicit reason codes.

- [ ] **Step 3: Run tests to confirm RED.**

```bash
python -m unittest tests.test_naked_k_smart_money_research_dataset -v
```

- [ ] **Step 4: Implement pure chronological dataset construction.**

Never re-run current detectors against a full historical frame. Read persisted point-in-time evidence and validate lineage first; use OHLCV prefixes only for fields explicitly required by the frozen protocol. Assign event groups `A`, `B`, `A_AND_B` without calling them statistically independent.

- [ ] **Step 5: Run tests and commit.**

```bash
python -m unittest tests.test_naked_k_smart_money_research_dataset -v
git add naked_k_smart_money_research_dataset.py tests/test_naked_k_smart_money_research_dataset.py tests/fixtures/smart_money/research/point_in_time_events.v1.json
git diff --cached --check
git commit -m "feat: build point-in-time smart-money events" -m "Constraint: Persisted availability and lineage define every event
Confidence: high
Scope-risk: moderate"
```

---

### Task 2: Outcomes, Risk Paths, and Coverage

**Files:**
- Create: `naked_k_smart_money_outcomes.py`
- Create: `tests/test_naked_k_smart_money_outcomes.py`

**Interfaces:**
- Consumes: deduplicated events, eligible session universe, ticker OHLCV, `^HSI` OHLCV and optional point-in-time 1H bars.
- Produces: `label_event_outcome()` and `compute_coverage()`.

```python
def label_event_outcome(
    event: SmartMoneyEvent,
    stock_daily: pd.DataFrame,
    benchmark_daily: pd.DataFrame,
    *,
    intraday: pd.DataFrame | None,
    calendar: TradingCalendar,
) -> EventOutcome: ...

def compute_coverage(events: Sequence[SmartMoneyEvent], eligible_sessions: pd.DataFrame) -> float | None: ...
```

- [ ] **Step 1: Write failing entry/return tests.**

Assert entry is the first normal-session open at or after `tradable_at`; missing open is `NOT_COMPUTABLE`. Lock directional 5/10/20 benchmark excess for bullish/bearish, with benchmark missing staying null.

- [ ] **Step 2: Write failing 1R/MFE/MAE tests.**

`1R=median(High-Low)` over the prior 20 complete sessions, excluding entry. Test +1R first, -1R first, both same daily bar with/without 1H ordering, fewer than 20 bars, p95 adverse input and no path beyond horizon 20.

- [ ] **Step 3: Run tests to confirm RED.**

```bash
python -m unittest tests.test_naked_k_smart_money_outcomes -v
```

- [ ] **Step 4: Implement exact outcome protocol.**

All return and excursion fields carry `computability` and reason codes. Precision denominator includes only directional, independently deduplicated, computable events. Coverage denominator is eligible ticker-session, not calendar days or triggered events.

- [ ] **Step 5: Run tests and commit.**

```bash
python -m unittest tests.test_naked_k_smart_money_outcomes -v
git add naked_k_smart_money_outcomes.py tests/test_naked_k_smart_money_outcomes.py
git diff --cached --check
git commit -m "feat: label smart-money event outcomes" -m "Constraint: Missing benchmark or path data is never imputed
Confidence: high
Scope-risk: moderate"
```

---

### Task 3: Matched Baseline Without Reuse

**Files:**
- Create: `naked_k_smart_money_matching.py`
- Create: `tests/test_naked_k_smart_money_matching.py`

**Interfaces:**
- Consumes: one already-built walk-forward fold/partition, its events, eligible session universe, all event exclusion windows and pre-entry features.
- Produces: deterministic one-to-one `MatchedPair` or `NOT_COMPUTABLE` scoped to that fold partition. Task 3 can be coded against the `WalkForwardFold` contract from Task 0, but runtime invocation happens only after Task 4 builds folds.

```python
def match_baselines(
    events: Sequence[SmartMoneyEvent],
    eligible_sessions: pd.DataFrame,
    *,
    fold: WalkForwardFold,
    partition: Literal["train", "validation", "test"],
    calendar: TradingCalendar,
) -> tuple[MatchedPair, ...]: ...
```

- [ ] **Step 1: Write failing eligibility and tie-break tests.**

Candidates must match ticker, natural year, normalized structure and prior-20-range quartile, and have no smart-money event within ±5 trading days. Candidate entry plus its 20-session outcome path must remain inside the same non-embargoed partition and must not cross a purged boundary. Choose minimum trading-session distance; ties choose earlier date then lexical session ID. A baseline cannot be reused within the same fold partition; `used_session_ids` resets only for a new fold/partition.

- [ ] **Step 2: Write failing direction/no-match tests.**

The candidate inherits the event direction for hypothetical outcome calculation; it never reads future returns to choose direction. No candidate yields `NOT_COMPUTABLE/NO_MATCH`, not zero lift.

- [ ] **Step 3: Run tests to confirm RED.**

```bash
python -m unittest tests.test_naked_k_smart_money_matching -v
```

- [ ] **Step 4: Implement deterministic greedy matching.**

Process events by `tradable_at,event_id`; track used candidate session IDs locally to `(fold_id, partition)`. Persist every candidate filter reason, fold/partition ID and selected distance for audit.

- [ ] **Step 5: Run tests and commit.**

```bash
python -m unittest tests.test_naked_k_smart_money_matching -v
git add naked_k_smart_money_matching.py tests/test_naked_k_smart_money_matching.py
git diff --cached --check
git commit -m "feat: match smart-money event baselines" -m "Constraint: Matching cannot inspect outcome prices
Confidence: high
Scope-risk: narrow"
```

---

### Task 4: Purged Walk-Forward Windows and Pre-Registered Protocol

**Files:**
- Create: `naked_k_smart_money_walk_forward.py`
- Create: `tests/test_naked_k_smart_money_walk_forward.py`

**Interfaces:**
- Consumes: chronological events/outcomes, validation metrics and protocol.
- Produces: `build_walk_forward_folds()`, fixed rule binding and a validation-frozen single-layer comparator.

```python
def build_walk_forward_folds(
    sessions: Sequence[str],
    *,
    protocol: ResearchProtocol,
    calendar: TradingCalendar,
) -> tuple[WalkForwardFold, ...]: ...

def bind_preregistered_rules(
    fold: WalkForwardFold,
    *,
    protocol: ResearchProtocol,
) -> FrozenRuleBinding: ...

def freeze_single_layer_comparator(
    fold: WalkForwardFold,
    validation_metrics: Sequence[MetricResult],
    *,
    protocol: ResearchProtocol,
) -> FrozenComparator: ...
```

- [ ] **Step 1: Write failing calendar-window tests.**

Lock first 3-year train, next 6-month validation, next 6-month test, then 6-month rolling. Assert exact month-end boundaries, incomplete terminal fold exclusion and per-ticker chronological ordering.

- [ ] **Step 2: Write failing purge/embargo/leak tests.**

Remove events whose 20-session label crosses a boundary and exclude 20 sessions on both sides of test. Every fold must bind the identical `phase0-rules.v1`; mutating train/validation/test outcomes cannot alter that threshold ID. Validation freezes the strongest single A or B by highest worst-direction matched precision lift, then median 10-day excess, then lexical cohort name; test mutations cannot alter the comparator ID.

- [ ] **Step 3: Run tests to confirm RED.**

```bash
python -m unittest tests.test_naked_k_smart_money_walk_forward -v
```

- [ ] **Step 4: Implement explicit fold membership.**

Every fold serializes train/validation/test date bounds, embargo ranges, included event IDs, purged IDs and the pre-registered threshold content ID. Build folds first, then call `match_baselines()` separately for each partition, bind the fixed rules, compute validation metrics and freeze the strongest single comparator. Test performs no selection.

- [ ] **Step 5: Run tests and commit.**

```bash
python -m unittest tests.test_naked_k_smart_money_walk_forward -v
git add naked_k_smart_money_walk_forward.py tests/test_naked_k_smart_money_walk_forward.py
git diff --cached --check
git commit -m "feat: add purged smart-money walk-forward folds" -m "Constraint: Test outcomes cannot influence frozen rules
Confidence: high
Scope-risk: moderate"
```

---

### Task 5: Block Bootstrap, FDR, and Metrics

**Files:**
- Create: `naked_k_smart_money_statistics.py`
- Create: `tests/test_naked_k_smart_money_statistics.py`

**Interfaces:**
- Consumes: OOS outcomes and matched pairs only.
- Produces: deterministic metrics/CI tables and BH decisions.

```python
def summarize_oos_metrics(
    outcomes: Sequence[EventOutcome],
    matched_pairs: Sequence[MatchedPair],
    *,
    fold: WalkForwardFold,
    cohort: Literal["A", "B", "A_AND_B"],
    evidence_kind: str,
    protocol: ResearchProtocol,
) -> tuple[MetricResult, ...]: ...

def benjamini_hochberg(
    p_values: Mapping[str, float],
    *,
    family_id: str,
    q: float = 0.05,
) -> FDRResult: ...

def summarize_pooled_oos_metrics(
    fold_outcomes: Mapping[str, Sequence[EventOutcome]],
    fold_matched_pairs: Mapping[str, Sequence[MatchedPair]],
    frozen_comparators: Mapping[str, FrozenComparator],
    *,
    protocol: ResearchProtocol,
) -> PooledResearchResult: ...
```

- [ ] **Step 1: Write failing metric denominator tests.**

Lock precision, false-positive rate, coverage, directional 5/10/20 excess, MFE, MAE, p95 adverse and matched lift. Null inputs remain excluded with reported numerator/denominator and reason.

- [ ] **Step 2: Write failing block-bootstrap tests.**

Resample complete `(ticker, YYYY-MM)` blocks with replacement, preserving rows and atomic event/control pairs inside blocks. Same seed yields byte-identical results; row bootstrap or separately sampled controls produce different known fixture results. Require exactly 10,000 draws in production mode. Lock percentile CI and the one-sided plus-one p-value against a hand-computed small fixture.

- [ ] **Step 3: Write failing BH-FDR tests.**

Test empty, one, ties, values at the rejection boundary and stable lexical tie order. Assert one family per `(protocol_id, fold_id)` and one `{protocol_id}:pooled-oos` family contain all kind × A/B/A_AND_B `precision_lift|excess_10d` hypotheses plus A_AND_B-versus-frozen-single `dual_increment` contrasts, including unfavorable results; descriptive metrics are excluded.

- [ ] **Step 4: Write failing pooled-OOS tests.**

Combine all test partitions, deduplicate by `event_id`, and if a rolling-window fixture repeats an event keep the earliest lexical `fold_id` plus its atomic matched control. Assert the pooled function resamples the deduplicated raw `(ticker, YYYY-MM)` blocks—not fold point estimates—and directly returns pooled matched precision lift, 10-day excess and A_AND_B-minus-frozen-single precision-difference estimates/CIs/p-values/counts. Changing one underlying event must change the pooled result even when fold summaries are held constant.

- [ ] **Step 5: Run tests to confirm RED.**

```bash
python -m unittest tests.test_naked_k_smart_money_statistics -v
```

- [ ] **Step 6: Implement transparent statistics.**

Persist point estimate, lower/upper 95% CI, sample/event/ticker/block counts, raw p-value, adjusted decision and seed. Fold and pooled results both retain their raw event/control IDs; pooled output is never reconstructed from fold CIs. Do not expose a calibrated event probability.

- [ ] **Step 7: Run tests and commit.**

```bash
python -m unittest tests.test_naked_k_smart_money_statistics -v
git add naked_k_smart_money_statistics.py tests/test_naked_k_smart_money_statistics.py
git diff --cached --check
git commit -m "feat: compute reproducible smart-money research metrics" -m "Constraint: Inference uses ticker-month blocks and declared FDR family
Confidence: high
Scope-risk: moderate"
```

---

### Task 6: Ablation and Qualification Gate

**Files:**
- Create: `naked_k_smart_money_qualification.py`
- Create: `tests/test_naked_k_smart_money_qualification.py`
- Create: `tests/fixtures/smart_money/research/qualification_matrix.v1.json`

**Interfaces:**
- Consumes: fold-level OOS metrics for three-window consistency plus one raw-block-derived `PooledResearchResult` for pooled gates.
- Produces: one deterministic `QualificationResult` that cannot modify live execution.

```python
def evaluate_qualification(
    fold_results: Sequence[FoldResearchResult],
    pooled_result: PooledResearchResult,
    *,
    protocol: ResearchProtocol,
) -> QualificationResult: ...
```

- [ ] **Step 1: Write failing every-gate matrix tests.**

Cover fewer than 200 independent OOS events, either direction below 30, fewer than three complete test windows, either matched precision lift or 10-day excess nonpositive in any of the latest three windows, absent/tampered `PooledResearchResult`, pooled matched precision lift below 5pp, its CI lower bound ≤0, pooled 10-day excess CI lower bound ≤0, pooled A_AND_B precision difference versus the validation-frozen strongest single layer with CI lower bound ≤0, any required BH decision failure, and missing matched baseline. Assert A/B/A_AND_B cohorts are non-exclusive and counts are never summed as independent samples.

- [ ] **Step 2: Write failing non-mutation tests.**

Run the evaluator beside real `InstrumentReport` fixtures and assert action, signal, risk, suggested gross and portfolio exposure remain byte-identical. Even a passing research fixture returns only `RESEARCH_QUALIFIED_FOR_SCHEMA_REVIEW`, never directly enables sizing.

- [ ] **Step 3: Run tests to confirm RED.**

```bash
python -m unittest tests.test_naked_k_smart_money_qualification -v
```

- [ ] **Step 4: Implement conjunctive fail-closed qualification.**

Every frozen protocol gate must pass conjunctively. Missing/not-computable values fail with reason codes. The 200/30 counts use deduplicated pooled OOS A_AND_B events only; three-window consistency uses the latest three complete test folds; incremental comparison uses the validation-selected single layer and the protocol's dual-observable universe. A pass requests a separate schema/calibration design review; it does not change `UNVALIDATED` fields in the current production schema.

- [ ] **Step 5: Run tests and commit.**

```bash
python -m unittest tests.test_naked_k_smart_money_qualification -v
git add naked_k_smart_money_qualification.py tests/test_naked_k_smart_money_qualification.py tests/fixtures/smart_money/research/qualification_matrix.v1.json
git diff --cached --check
git commit -m "feat: enforce smart-money qualification gates" -m "Constraint: Research pass requires a separate production schema review
Confidence: high
Scope-risk: narrow"
```

---

### Task 7: Offline Event-Study CLI and Research Artifacts

**Files:**
- Create: `run_smart_money_event_study.py`
- Create: `tests/test_run_smart_money_event_study.py`
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `docs/superpowers/smart-money-user-guide.md`

**Interfaces:**
- Consumes: immutable local Phase 0–3 trade-flow/short-selling stores, `SmartMoneyEvidenceBundle` artifacts and point-in-time ticker/`^HSI` `OHLCVSnapshot` artifacts only. Phase 0–3 `run_analysis()` is the producer; readiness rejects any missing/tampered interval rather than fetching it here.
- Produces: content-addressed dataset, fold, metric and qualification JSON plus Markdown summary.

CLI contract:

```text
python run_smart_money_event_study.py \
  --snapshot-root reports/market_data/trade_flow \
  --evidence-root reports/market_data/evidence \
  --ohlcv-root reports/market_data/research_ohlcv \
  --output-root reports/market_data/event-study \
  --protocol tests/fixtures/smart_money/research/protocol.v1.json \
  --deny-network
```

- [ ] **Step 1: Write failing zero-network/readiness/artifact tests.**

Patch socket and requests explicitly. Insufficient history exits with a documented nonzero code and writes only readiness JSON. Ready fixtures write dataset/fold/metrics/qualification artifacts, each carrying protocol ID, input content IDs, command parameters, code revision and seed.

- [ ] **Step 2: Write failing replay-determinism tests.**

Two runs over identical inputs in different output directories produce identical content IDs and payload bytes except a separate non-hashed invocation envelope. Tampered input aborts before any research result publication.

- [ ] **Step 3: Run tests to confirm RED.**

```bash
python -m unittest tests.test_run_smart_money_event_study -v
```

- [ ] **Step 4: Implement offline orchestration and atomic publication.**

Run readiness, dataset, outcomes, fold construction, per-fold/partition matching, fixed-rule binding, validation comparator freeze, test outcomes, fold statistics, pooled raw-block statistics, ablation and qualification in that order. Write same-directory temp files and atomically publish only after all input/output digests verify. Ignore `reports/market_data/event-study/**`; never track real market data.

- [ ] **Step 5: Document honest status.**

README/user guide must say Phase 4 remains unavailable until real point-in-time history satisfies readiness, explain all metrics/denominators, and distinguish “research-qualified for schema review” from a live trading signal.

- [ ] **Step 6: Run final Phase 4 regression and commit.**

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_naked_k_smart_money_research_contracts \
  tests.test_naked_k_smart_money_research_dataset \
  tests.test_naked_k_smart_money_outcomes \
  tests.test_naked_k_smart_money_matching \
  tests.test_naked_k_smart_money_walk_forward \
  tests.test_naked_k_smart_money_statistics \
  tests.test_naked_k_smart_money_qualification \
  tests.test_run_smart_money_event_study -v
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -v
git diff --check
git add run_smart_money_event_study.py tests/test_run_smart_money_event_study.py .gitignore README.md docs/superpowers/smart-money-user-guide.md
git diff --cached --check
git commit -m "feat: run offline smart-money event study" -m "Constraint: Real history only and no live execution mutation
Confidence: high
Scope-risk: broad
Not-tested: Qualification against a not-yet-accumulated three-year live dataset"
```

## Final Verification Gate

Before calling the Phase 4 machinery complete, run:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -v
python run_smart_money_event_study.py \
  --snapshot-root reports/market_data/trade_flow \
  --evidence-root reports/market_data/evidence \
  --ohlcv-root reports/market_data/research_ohlcv \
  --output-root reports/market_data/event-study \
  --protocol tests/fixtures/smart_money/research/protocol.v1.json \
  --deny-network
rg -n "probability|校准概率|已验证主力" README.md docs/superpowers/smart-money-user-guide.md reports/market_data/event-study 2>/dev/null
git diff --check
git status --short
```

Expected now: the code/test machinery may pass, but the real-data CLI will normally return `NOT_COMPUTABLE/INSUFFICIENT_HISTORY` until enough forward-collected data exists. That is a correct, complete Phase 4 implementation outcome; it is not permission to claim economic qualification.
