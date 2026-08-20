# Smart Money Dual-Evidence Phase 0–3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有未经校准的“主力概率”改造成免费、可回放、可审计的港股成交代理与裸 K 价格行为跨层印证功能，同时保证交易动作、价位、风险和组合敞口完全不受影响。

**Architecture:** `naked_k_planner.build_trade_plan()` 恢复为纯裸 K 技术计划；`naked_k_analysis.run_analysis()` 是唯一网络和快照编排边界，先采集或回放成交代理，再生成纯 price-action evidence、显式融合并只向报告附加 advisory 字段。所有 provider、evidence、fusion 都通过 versioned dataclass 和 content ID 串起 lineage；失败只降级相应层，不阻断基础报告。

**Tech Stack:** Python 3.14、pandas、requests、标准库 `dataclasses` / `enum.StrEnum` / `hashlib` / `gzip` / `json` / `pathlib` / `zoneinfo`、`unittest`、`unittest.mock`。

**Spec:** [`docs/superpowers/specs/2026-08-17-smart-money-dual-evidence-design.md`](../specs/2026-08-17-smart-money-dual-evidence-design.md)

## Global Constraints

- 保持裸 K 核心：不增加 MA、EMA、MACD、RSI、BOLL 或广义指标评分框架。
- trade print 只能称为逐笔成交；没有 bid/ask 时，tick rule 只能输出 uptick/downtick proxy，不能声称真实 aggressor side、订单身份或机构身份。
- 新 schema 不得输出 `probability`、`heuristic_score`、`strength_score` 或其他替代数字；只输出原始统计、触发规则、离散状态和 `validation_status=UNVALIDATED`。
- smart-money 始终为 `ADVISORY_ONLY`；注入前后 `action`、`signal_state`、价格字段、完整 `risk_plan`、仓位和组合 exposure 必须 deep-equal。
- 首期市场为港股，首期 live acceptance 固定 `0700.HK`、`1810.HK`、`9992.HK`；非港股不得调用港股 provider。
- 新增外部数据只用免费公开源：东方财富逐笔成交和 HKEX 当日卖空；接口失败必须结构化降级。
- `--smart-money-offline` 只禁止 Eastmoney/HKEX 新增分支联网；现有 OHLCV 仍由 `load_ohlcv()` 获取，不宣传为整个 CLI 完全离线。
- `smart_money.enabled=false` 时不得调用新增 provider，也不得写 `reports/market_data/**`。
- raw snapshot ID 对原始 bytes 求 SHA-256，不对 gzip bytes 求 hash；gzip 使用 `mtime=0`。normalized ID 对排除 retrieval envelope 与自引用 ID 的 canonical semantic payload 求 SHA-256；同内容多次抓取以独立 `retrieval_id` 记录。
- 单元测试必须注入 fake transport；`python -m unittest discover -v` 不得依赖 Eastmoney、HKEX 或行情站在线。
- 每个任务先写失败测试、确认 RED，再写最小实现、确认 GREEN，再单独提交；提交前运行 `git diff --cached --check`。
- 每次提交使用 OMC trailers：至少包含 `Constraint:`、`Confidence:` 和 `Scope-risk:`；已知未跑的 live 验收写入 `Not-tested:`。

## File Responsibility Map

| 文件 | 单一职责 |
|---|---|
| `naked_k_smart_money_contracts.py` | versioned dataclass、枚举、canonical serialization/content ID、provider/store/calendar Protocol |
| `naked_k_price_evidence.py` | 纯 OHLCV/zone/pool/structure 的 point-in-time price-action evidence |
| `naked_k_smart_money_fusion.py` | participation normalization、完整融合矩阵、时间对齐 |
| `naked_k_market_session.py` | 港股正常日/半日市/休市/未知和交易阶段边界 |
| `data/hkex_sessions_2026.json` | 2026 HKEX 官方休市日和半日市的版本化静态日历 |
| `naked_k_flow_eastmoney.py` | 东方财富请求参数、schema probe、parser/normalizer；不持久化 |
| `naked_k_flow_store.py` | raw/normalized snapshot、manifest/latest、回放与 tamper 检测 |
| `naked_k_smart_money_artifact_store.py` | immutable daily OHLCV input 与 evidence/fusion bundle，供同输入回放和 Phase 4 使用 |
| `naked_k_flow_evidence.py` | tick rule、nearest-rank、large/extra-large trade-tape LayerResult |
| `naked_k_short_selling_hkex.py` | HKEX 当日卖空 parser、reconciliation、neutral context |
| `naked_k_short_selling_store.py` | HKEX raw/normalized snapshot、manifest 和历史回放 |
| `naked_k_smart_money_acceptance.py` | 跨 Markdown/JSON/journal/audit 的 lineage 与执行不变量验收 |
| `naked_k_smart_money.py` | 兼容 facade，只转发到新 price/fusion API，不保留旧概率算法 |
| `naked_k_analysis.py` | 唯一编排边界、审计顺序、报告/journal/JSON 和执行不变量 |
| `naked_k_planner.py` | 纯裸 K 技术计划与 `InstrumentReport`，不导入任何 provider |
| `run_smart_money_live_smoke.py` | 三标的显式联网验收与同快照回放 |

---

### Task 0: Baseline, Approval Metadata, and Worktree Guard

**Files:**
- Read: `docs/superpowers/specs/2026-08-17-smart-money-dual-evidence-design.md`
- Read: all production and test files

**Interfaces:**
- Consumes: approved spec at commit `811d69f` plus the planning amendment that renames `--offline` to `--smart-money-offline`.
- Produces: a recorded clean baseline; no production output.

- [ ] **Step 1: Confirm the approved documents and clean worktree.**

Run:

```bash
git status --short
git log --oneline -3
rg -n "用户已批准|smart-money-offline" docs/superpowers/specs/2026-08-17-smart-money-dual-evidence-design.md
```

Expected: no unrelated dirty files; the spec says `用户已批准` and explicitly limits offline mode to the new provider branch.

- [ ] **Step 2: Run the exact baseline suite.**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -v
```

Expected: `Ran 447 tests` and `OK`. If the count has legitimately increased before execution, record the new count and require all tests to pass.

- [ ] **Step 3: Confirm no secret or generated market data is tracked.**

Run:

```bash
git ls-files .env reports/market_data
```

Expected: no output. This task creates no commit.

---

### Task 1: Versioned Contracts and Nested Configuration

**Files:**
- Create: `naked_k_smart_money_contracts.py`
- Create: `tests/test_naked_k_smart_money_contracts.py`
- Modify: `naked_k_config.py:36-102`
- Modify: `tests/test_naked_k_config.py`
- Modify: `config.example.json:22-28`

**Interfaces:**
- Consumes: standard-library types and existing `TradingConfig`.
- Produces: `TradePrint`, `TradeFlowSnapshot`, runtime-only `TradeFlowCollection`, `ShortSellingSnapshot`, runtime-only `ShortSellingCollection`, `OHLCVSnapshot`, `Evidence`, `LayerResult`, `FusionResult`, `SmartMoneyRuntime`, `canonical_payload()`, `content_id()`, and nested `SmartMoneyConfig` used by every later task.

The public contracts are fixed as:

```python
class ProviderStatus(StrEnum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    DEFINITION_MISMATCH = "DEFINITION_MISMATCH"
    INVALID = "INVALID"

class Direction(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"

class Lifecycle(StrEnum):
    OBSERVED = "observed"
    PENDING = "pending_confirmation"
    CONFIRMED = "confirmed"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
    NOT_COMPUTABLE = "not_computable"

class ParticipationState(StrEnum):
    INACTIVE = "INACTIVE"
    UNKNOWN = "UNKNOWN"
    PROVISIONAL = "PROVISIONAL"
    FORMAL_CONFLICT = "FORMAL_CONFLICT"
    FORMAL_BULLISH = "FORMAL_BULLISH"
    FORMAL_BEARISH = "FORMAL_BEARISH"
    FORMAL_NEUTRAL = "FORMAL_NEUTRAL"

def canonical_payload(value: Any) -> bytes: ...
def content_id(prefix: str, value: Any) -> str: ...
def normalized_snapshot_preimage(snapshot: TradeFlowSnapshot | ShortSellingSnapshot) -> Mapping[str, Any]: ...
def ohlcv_snapshot_preimage(snapshot: OHLCVSnapshot) -> Mapping[str, Any]: ...
def evidence_bundle_preimage(bundle: SmartMoneyEvidenceBundle) -> Mapping[str, Any]: ...
def retrieval_envelope_id(*, raw_snapshot_id: str, normalized_snapshot_id: str,
                          retrieved_at: pd.Timestamp) -> str: ...
```

`TradePrint`, `TradeFlowSnapshot`, `Evidence`, `LayerResult`, and `FusionResult` each expose `to_dict() -> dict[str, Any]`; datetimes serialize as timezone-aware ISO-8601 and enums serialize as strings. Unknown numerics are `None`, never zero.

Lock the cross-task carrier types in this task so later implementations do not invent incompatible shapes:

```python
@dataclass(frozen=True)
class TradeFlowCollection:
    raw_payload: bytes
    snapshot: TradeFlowSnapshot

@dataclass(frozen=True)
class ShortSellingCollection:
    raw_payload: bytes
    snapshot: ShortSellingSnapshot

@dataclass(frozen=True)
class LayerResult:
    schema_version: str
    layer_id: str
    availability: str
    direction: str
    lifecycle: str
    quality: str
    as_of: pd.Timestamp
    valid_from: pd.Timestamp
    expires_at: pd.Timestamp | None
    target_session: str
    evidence: tuple[Evidence, ...]
    evidence_ids: tuple[str, ...]
    lineage_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    validation_status: str = "UNVALIDATED"
    advisory_only: bool = True

@dataclass(frozen=True)
class FusionResult:
    schema_version: str
    fusion_id: str
    status: str
    direction: str
    as_of: pd.Timestamp
    trade_flow_layer_id: str
    price_action_layer_id: str
    source_evidence_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    limitations: tuple[str, ...]
    validation_status: str = "UNVALIDATED"
    advisory_only: bool = True
```

`TradePrint` is keyword-only and contains every field in spec §6.2, including derived `source_row_id` and `zero_tick`; `TradeFlowSnapshot` contains every field in §6.1 plus `prints: tuple[TradePrint, ...]`; `ShortSellingSnapshot` contains source/trading date, retrieved/available timestamps, shares/turnover, status, reconciliation and snapshot ID. `Evidence` contains every field in §6.3. Provider payload bytes live only in runtime collection objects and never serialize into report, journal or audit.

`OHLCVSnapshot` fixes `schema_version=ohlcv-input.v1`, ticker, interval, timezone, adjustment metadata, source, first-seen timestamp, ordered unrounded OHLCV rows and `ohlcv_snapshot_id`. `SmartMoneyEvidenceBundle` fixes `schema_version=smart-money-bundle.v1`, ticker/decision time, config fingerprint, trade/short/OHLCV snapshot IDs, both complete layers and fusion. `SmartMoneyBundleEnvelope` separately records `invocation_run_id`, `source_run_id`, `source_bundle_id` and acquisition/replay time; none of those provenance fields belongs to the bundle semantic payload.

Identity preimages are exact:

```text
raw_snapshot_id        = "sha256:" + SHA256(raw_payload)
normalized_snapshot_id = "sha256:" + SHA256(canonical_payload(
  normalized snapshot without retrieved_at, raw_snapshot_id,
  normalized_snapshot_id, retrieval_id, filesystem path and any
  acquisition-derived available_at
))
retrieval_id           = "sha256:" + SHA256(canonical_payload({
  raw_snapshot_id, normalized_snapshot_id, retrieved_at
}))
ohlcv_snapshot_id       = content ID of ordered unrounded rows + ticker/interval/
                          timezone/adjustment/source, excluding ID/first_seen/path
bundle_id               = content ID of ticker/decision/config/input IDs +
                          complete layers/fusion, excluding invocation_run_id,
                          source_run_id, source_bundle_id, retrieval envelope,
                          bundle_id and filesystem path
evidence_id            = content ID of rule version + semantic input IDs +
                         observed/available/expiry times + inputs/thresholds/status
fusion_id              = content ID of fusion rule version + two layer IDs +
                         decision_time/status/direction/reason codes
```

The first persisted retrieval owns the immutable snapshot's `retrieved_at`; later byte-identical retrievals append envelopes but do not rewrite it. For short-selling, the provider's acquisition-derived `available_at` is also excluded from the semantic preimage and rehydrated from the first-seen envelope before evidence construction. `available_at` and all evidence IDs therefore use the stable first-seen value on replay. Hash verification always reconstructs the documented preimage, so excluding envelope fields is explicit rather than accidental.

Define dependency inversion at the same boundary:

```python
class TradeFlowProvider(Protocol):
    def collect(self, ticker: str, session: MarketSession, *, retrieved_at: pd.Timestamp,
                config: TradeFlowConfig) -> TradeFlowCollection: ...

class ShortSellingProvider(Protocol):
    def collect(self, ticker: str, session: MarketSession, *, retrieved_at: pd.Timestamp,
                total_turnover: float | None,
                config: ShortSellingConfig) -> ShortSellingCollection: ...

class SnapshotStore(Protocol):
    def persist(self, collection: TradeFlowCollection) -> TradeFlowSnapshot: ...
    def load(self, snapshot_id: str) -> TradeFlowSnapshot: ...
    def history(self, ticker: str, *, before_session: str, limit: int) -> list[TradeFlowSnapshot]: ...

class ShortSellingStore(Protocol):
    def persist(self, collection: ShortSellingCollection) -> ShortSellingSnapshot: ...
    def load(self, snapshot_id: str) -> ShortSellingSnapshot: ...
    def history(self, ticker: str, *, before_session: str, limit: int) -> list[ShortSellingSnapshot]: ...

class SmartMoneyArtifactStore(Protocol):
    def persist_ohlcv(self, ticker: str, interval: str, frame: pd.DataFrame,
                      *, retrieved_at: pd.Timestamp) -> OHLCVSnapshot: ...
    def load_ohlcv(self, snapshot_id: str) -> OHLCVSnapshot: ...
    def persist_bundle(self, bundle: SmartMoneyEvidenceBundle, *,
                       envelope: SmartMoneyBundleEnvelope) -> str: ...
    def load_bundle(self, bundle_id: str) -> SmartMoneyEvidenceBundle: ...
    def bundle_envelopes(self, bundle_id: str) -> tuple[SmartMoneyBundleEnvelope, ...]: ...
    def latest_bundle(self, ticker: str) -> SmartMoneyEvidenceBundle | None: ...

@dataclass(frozen=True)
class SmartMoneyReplaySelection:
    trade_flow_snapshot_id: str | None = None
    short_selling_snapshot_id: str | None = None
    ohlcv_snapshot_id: str | None = None
    evidence_bundle_id: str | None = None

@dataclass(frozen=True)
class SmartMoneyRuntime:
    trade_flow_provider: TradeFlowProvider | None
    short_selling_provider: ShortSellingProvider | None
    snapshot_store: SnapshotStore
    short_selling_store: ShortSellingStore
    artifact_store: SmartMoneyArtifactStore
    calendar: TradingCalendar
    provider_offline: bool = False
    replay_by_ticker: Mapping[str, SmartMoneyReplaySelection] = field(default_factory=dict)
    now: pd.Timestamp | None = None
```

If `evidence_bundle_id` is present, orchestration resolves all three input IDs, config fingerprint and original decision time from that verified bundle; any simultaneously supplied component ID must match it. This is the canonical identical-ID replay path.
The replay invocation generates a fresh `invocation_run_id` for current report/journal/audit paths while preserving `source_run_id` and `source_bundle_id` only in a new provenance envelope. Audit records `replayed_from_bundle_id` and `source_run_id`; neither original nor fresh run IDs change bundle/evidence/fusion IDs.

- [ ] **Step 1: Write failing exact-schema and stable-ID tests.**

Add tests containing these assertions:

```python
def test_trade_print_duplicates_keep_distinct_row_ids(self):
    first = make_trade_print(source_ordinal=0, occurrence_index=0)
    second = make_trade_print(source_ordinal=1, occurrence_index=1)
    self.assertEqual(first.source_row_id, "0:0")
    self.assertEqual(second.source_row_id, "1:1")

def test_new_contracts_have_no_probability_or_numeric_score(self):
    encoded = json.dumps(self.layer.to_dict(), ensure_ascii=False)
    self.assertNotIn("probability", encoded)
    self.assertNotIn("strength_score", encoded)
    self.assertNotIn("heuristic_score", encoded)
    self.assertEqual(self.layer.validation_status, "UNVALIDATED")

def test_canonical_content_id_is_order_independent(self):
    self.assertEqual(content_id("evidence", {"b": 2, "a": 1}), content_id("evidence", {"a": 1, "b": 2}))
```

Also assert the exact `trade-flow.v1` required keys from spec §6.1 and that naive datetimes raise `ValueError`.
Round-trip every `ParticipationState`; assert the exact `LayerResult.to_dict()` key set includes `validation_status="UNVALIDATED"` and `advisory_only=true`, and reject unknown enum strings during deserialization.

- [ ] **Step 2: Run the focused tests to confirm RED.**

Run:

```bash
python -m unittest tests.test_naked_k_smart_money_contracts tests.test_naked_k_config -v
```

Expected: import failures for `naked_k_smart_money_contracts` and missing nested config fields.

- [ ] **Step 3: Implement canonical contracts and nested config.**

Add these configuration dataclasses:

```python
@dataclass(frozen=True)
class PriceActionEvidenceConfig:
    volume_anomaly_threshold: float = 1.5
    sweep_close_position_threshold: float = 0.65
    exhaustion_volume_ratio: float = 0.8

@dataclass(frozen=True)
class TradeFlowConfig:
    enabled: bool = True
    provider: str = "eastmoney_hk"
    timeout_seconds: float = 5.0
    max_retries: int = 1
    persist_raw: bool = True
    require_session_complete: bool = True

@dataclass(frozen=True)
class ShortSellingConfig:
    enabled: bool = True
    provider: str = "hkex"

@dataclass(frozen=True)
class SmartMoneyConfig:
    enabled: bool = True
    mode: str = "dual_evidence"
    price_action: PriceActionEvidenceConfig = field(default_factory=PriceActionEvidenceConfig)
    trade_flow: TradeFlowConfig = field(default_factory=TradeFlowConfig)
    short_selling: ShortSellingConfig = field(default_factory=ShortSellingConfig)
    deprecation_warnings: tuple[str, ...] = ()
```

Legacy `volume_anomaly_threshold`, `sweep_recovery_threshold`, and `exhaustion_volume_ratio` map once into `price_action`; `confluence_weight` is ignored. `build_trading_config()` stores deterministic warning codes in `deprecation_warnings` and also calls `warnings.warn(..., DeprecationWarning, stacklevel=2)`. Unknown mode/provider, nonpositive timeout and negative `max_retries` raise `ValueError` before runtime; `max_retries=0` means exactly one attempt.

- [ ] **Step 4: Run contracts/config tests to confirm GREEN.**

Run:

```bash
python -m unittest tests.test_naked_k_smart_money_contracts tests.test_naked_k_config -v
```

Expected: all tests pass; `config.example.json` contains the nested `dual_evidence` block and no `confluence_weight`.

- [ ] **Step 5: Commit the contracts task.**

Run:

```bash
git add naked_k_smart_money_contracts.py naked_k_config.py config.example.json tests/test_naked_k_smart_money_contracts.py tests/test_naked_k_config.py
git diff --cached --check
git commit -m "refactor: define dual-evidence contracts and config" -m "Constraint: No numeric smart-money score or paid data dependency
Confidence: high
Scope-risk: moderate"
```

---

### Task 2: Point-in-Time Price Evidence and Stable Zone IDs

**Files:**
- Create: `naked_k_price_evidence.py`
- Create: `tests/test_naked_k_price_evidence.py`
- Create: `tests/test_naked_k_price_evidence_lifecycle.py`
- Modify: `naked_k_zones.py:9-136`
- Modify: `tests/test_naked_k_zones.py`
- Replace tests: `tests/test_naked_k_smart_money.py`
- Modify: `naked_k_smart_money.py`

**Interfaces:**
- Consumes: `LayerResult`, `Evidence`, `PriceActionEvidenceConfig`, daily OHLCV, traceable zones/pools, market structure and existing pattern names.
- Produces: `build_price_action_layer(...) -> LayerResult`; `naked_k_smart_money.py` becomes a compatibility facade that exports this function only.

```python
def build_price_action_layer(
    daily: pd.DataFrame,
    *,
    zones: Sequence[Mapping[str, Any]],
    liquidity_pools: Sequence[Mapping[str, Any]],
    market_structure: Mapping[str, Any],
    patterns: Sequence[str],
    decision_time: pd.Timestamp,
    config: PriceActionEvidenceConfig,
) -> LayerResult: ...
```

- [ ] **Step 1: Write failing zone identity and bullish-boundary tests.**

Use a 20-bar baseline plus signal/confirmation bars and assert:

```python
def test_absorption_excludes_signal_volume_from_baseline(self):
    frame = price_frame_with_signal(relative_volume=1.50, close_position=0.65)
    layer = build_price_action_layer(frame, zones=[demand_zone("zone-1")], liquidity_pools=[],
        market_structure={"direction": "down"}, patterns=[], decision_time=self.decision, config=self.config)
    evidence = next(item for item in layer.evidence if item.kind == "bullish_absorption_like")
    self.assertEqual(evidence.inputs["relative_volume"], 1.5)
    self.assertEqual(layer.lifecycle, "pending_confirmation")

def test_missing_traceable_zone_or_pool_is_not_computable(self):
    zone_without_id = {"kind": "demand", "lower": 98.0, "upper": 99.0}
    layer = build_price_action_layer(self.frame, zones=[zone_without_id], liquidity_pools=[],
        market_structure={}, patterns=[], decision_time=self.decision, config=self.config)
    self.assertEqual(layer.lifecycle, "not_computable")
```

Update zone tests to require `zone_id`/`pool_id` based on canonical kind, source, member dates and unrounded prices; IDs must not depend only on rounded display prices.

- [ ] **Step 2: Write failing lifecycle and mirror tests.**

Add exact tests for `bullish_sweep_reclaim`, selling exhaustion’s two five-day decline formula, low-volume test parent linkage, five-day markup confirmation, invalidation-before-expiry, pending last bars, and a bearish golden mirror generated from the bullish frame by `O/H/L/C -> -O/-L/-H/-C` plus a positive offset.

```python
def test_future_bars_do_not_change_prior_evidence_id(self):
    pending = build_layer(self.frame.iloc[:-2], self.decision_minus_two)
    confirmed = build_layer(self.frame, self.decision)
    self.assertIn(pending.evidence[0].evidence_id, confirmed.evidence[0].lineage_ids)
    self.assertLess(pd.Timestamp(pending.evidence[0].observed_at), pd.Timestamp(confirmed.evidence[0].available_at))
```

- [ ] **Step 3: Run the focused tests to confirm RED.**

Run:

```bash
python -m unittest tests.test_naked_k_zones tests.test_naked_k_price_evidence tests.test_naked_k_price_evidence_lifecycle tests.test_naked_k_smart_money -v
```

Expected: missing module/interfaces and old probability-oriented assertions fail.

- [ ] **Step 4: Implement exact spec §8 rules without scores.**

Implement baselines from `t-20:t`, unrounded comparisons, traceable location rules, signal/available/expiry timestamps, and strict mirrored bearish rules. A price layer may cross-confirm tape only when at least one evidence has `dependency_group="price_response"`; pure volume observations stay in `trade_tape` dependency. When history or traceable location is insufficient return `direction="unknown"`, `lifecycle="not_computable"`, never “无明显信号”.

Delete the old manual confidence formulas from `naked_k_smart_money.py`; retain a small import-compatible facade:

```python
from naked_k_price_evidence import build_price_action_layer

__all__ = ["build_price_action_layer"]
```

- [ ] **Step 5: Run price evidence tests to confirm GREEN.**

Run:

```bash
python -m unittest tests.test_naked_k_zones tests.test_naked_k_price_evidence tests.test_naked_k_price_evidence_lifecycle tests.test_naked_k_smart_money -v
```

Expected: all pass; source search finds no live calculation of `confidence_score` or `probability` in `naked_k_smart_money.py`.

- [ ] **Step 6: Commit price evidence.**

Run:

```bash
git add naked_k_price_evidence.py naked_k_smart_money.py naked_k_zones.py tests/test_naked_k_price_evidence.py tests/test_naked_k_price_evidence_lifecycle.py tests/test_naked_k_smart_money.py tests/test_naked_k_zones.py
git diff --cached --check
git commit -m "feat: derive point-in-time price evidence" -m "Constraint: Indicator-free rules with no future confirmation leak
Rejected: Preserve legacy confidence percentages | not empirically calibrated
Confidence: high
Scope-risk: moderate"
```

---

### Task 3: Explicit Participation and Fusion State Machine

**Files:**
- Create: `naked_k_smart_money_fusion.py`
- Create: `tests/test_naked_k_smart_money_fusion.py`
- Create: `tests/fixtures/smart_money/fusion_matrix.v1.json`

**Interfaces:**
- Consumes: two `LayerResult` objects and a `TradingCalendar.session_distance()` implementation.
- Produces: `normalize_participation(layer) -> ParticipationState` and `fuse_dual_evidence(...) -> FusionResult`.

```python
def normalize_participation(layer: LayerResult) -> ParticipationState: ...

def fuse_dual_evidence(
    trade_flow: LayerResult,
    price_action: LayerResult,
    *,
    decision_time: pd.Timestamp,
    calendar: TradingCalendar,
) -> FusionResult: ...
```

- [ ] **Step 1: Write the failing normalization priority tests.**

Programmatically cover every combination of availability, quality, lifecycle and direction. Lock these edge cases:

```python
self.assertEqual(normalize_participation(layer(lifecycle="expired", direction="bullish")), "INACTIVE")
self.assertEqual(normalize_participation(layer(quality="PARTIAL", direction="conflict")), "PROVISIONAL")
self.assertEqual(normalize_participation(layer(lifecycle="not_computable", direction="unknown")), "UNKNOWN")
self.assertEqual(normalize_participation(layer(quality="VALID", lifecycle="confirmed", direction="bullish")), "FORMAL_BULLISH")
```

- [ ] **Step 2: Write the failing complete matrix and timing tests.**

The fixture contains the exact 4×4 formal matrix from spec §9. Tests iterate every cell, then assert formal conflict precedes provisional, provisional precedes single-layer, valid directional × not-computable remains single-layer, neutral × unknown is unavailable, same dependency group cannot align, and target sessions more than three sessions apart yield `provisional/time_misaligned`.

- [ ] **Step 3: Run the fusion tests to confirm RED.**

Run:

```bash
python -m unittest tests.test_naked_k_smart_money_fusion -v
```

Expected: missing module failure.

- [ ] **Step 4: Implement table-driven fusion.**

Use a constant mapping keyed by normalized participation states; do not add weights or numeric aggregation. `fusion_id` is `content_id("fusion", {trade_flow_id, price_action_id, decision_time, status, reason})`. A formal conflict remains conflict even if the other layer is provisional; a partial conflict is itself provisional.

- [ ] **Step 5: Run fusion tests and commit.**

Run:

```bash
python -m unittest tests.test_naked_k_smart_money_fusion -v
git add naked_k_smart_money_fusion.py tests/test_naked_k_smart_money_fusion.py tests/fixtures/smart_money/fusion_matrix.v1.json
git diff --cached --check
git commit -m "feat: fuse smart-money evidence with explicit states" -m "Constraint: Complete deterministic matrix without arithmetic scoring
Confidence: high
Scope-risk: narrow"
```

---

### Task 4: Advisory Core Integration and Semantic Surface Cleanup

**Files:**
- Modify: `naked_k_planner.py:1-280`
- Modify: `naked_k_analysis.py:18-283,750-818,1189-1377`
- Modify: `naked_k_interpreter.py:54-96,99-179`
- Modify: `naked_k_audit.py`
- Modify: `tests/test_naked_k_planner.py`
- Modify: `tests/test_naked_k_analysis.py`
- Modify: `tests/test_naked_k_interpreter.py`
- Create: `tests/test_naked_k_smart_money_surfaces.py`

**Interfaces:**
- Consumes: pure technical `InstrumentReport`, price-action `LayerResult`, an unavailable trade-flow `LayerResult`, and fusion function.
- Produces: advisory-only report fields and `capture_execution_projection(report) -> dict[str, Any]`.

`InstrumentReport` replaces `smart_money_signals` with:

```python
run_id: str = ""
trade_flow_evidence: dict[str, Any] = field(default_factory=dict)
price_action_evidence: dict[str, Any] = field(default_factory=dict)
smart_money_fusion: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 1: Write failing planner-separation and surface tests.**

Assert `inspect.getsource(naked_k_planner)` contains neither `naked_k_smart_money` nor provider names. Build a report and require the three new fields. Render report, brief, JSON, journal and audit, then recursively assert these forbidden keys are absent from new smart-money payloads:

```python
FORBIDDEN = {"probability", "confidence", "confidence_score", "heuristic_score", "strength_score"}

def assert_no_forbidden_keys(value):
    if isinstance(value, dict):
        self.assertTrue(FORBIDDEN.isdisjoint(value))
        for child in value.values():
            assert_no_forbidden_keys(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_forbidden_keys(child)
```

- [ ] **Step 2: Write failing execution-invariance tests.**

Define the exact projection:

```python
EXECUTION_FIELDS = (
    "action", "signal_state", "entry_trigger", "stop_loss", "target_price",
    "risk_per_share", "reward_to_risk", "position_size", "resistance", "support",
    "rationale", "risk_plan", "intraday_status",
)
```

`EXECUTION_FIELDS` must equal `naked_k_synthesis.TECHNICAL_SNAPSHOT_FIELDS`; the test fails if either tuple changes alone. `capture_execution_projection()` deep-copies nested data and separately records `risk_plan.suggested_gross_pct`, `effective_account_risk_pct` and `max_gross_pct`. Portfolio exposure is checked separately with the existing portfolio evaluator.

Capture a deep copy before advisory attachment and assert equality afterward for `price_action_only`, `provisional`, `conflict` and `unavailable`. Recompute `naked_k_portfolio.evaluate_portfolio_exposure()` before/after on a three-report basket and assert deep equality.

- [ ] **Step 3: Run focused integration tests to confirm RED.**

Run:

```bash
python -m unittest tests.test_naked_k_planner tests.test_naked_k_analysis tests.test_naked_k_interpreter tests.test_naked_k_smart_money_surfaces -v
```

Expected: old `smart_money_signals`/probability output causes failures.

- [ ] **Step 4: Remove smart-money computation from planner and attach advisory evidence in analysis.**

`build_trade_plan()` keeps its current signature and constructs only technical fields. `run_analysis()` builds price evidence from the completed report’s zones/structure/patterns, creates an unavailable flow layer, fuses, assigns only the three advisory fields, rebuilds trader brief/AI summary, and compares the exact execution projection. New audit payloads contain IDs and summary only; raw prints never enter audit.

Legacy journal rows remain readable through `load_journal()`; a legacy nested `probability` is not copied into the new fields or current report.

- [ ] **Step 5: Render the discrete user-facing copy.**

Add report section:

```text
主力动作代理判断
- 大额成交代理：不可用（首期数据层尚未接入）
- K线行为证据：<观察事实与 lifecycle>
- 跨层关系：<price_action_only/provisional/...>
- 确认条件：<confirmation>
- 失效条件：<invalidation>
- 数据限制：无法识别机构身份；ADVISORY_ONLY；UNVALIDATED
```

The trader brief uses the same fusion status and never appends `%` to smart-money text.

- [ ] **Step 6: Run focused tests and commit.**

Run:

```bash
python -m unittest tests.test_naked_k_planner tests.test_naked_k_analysis tests.test_naked_k_interpreter tests.test_naked_k_smart_money_surfaces -v
git add naked_k_planner.py naked_k_analysis.py naked_k_interpreter.py naked_k_audit.py tests/test_naked_k_planner.py tests/test_naked_k_analysis.py tests/test_naked_k_interpreter.py tests/test_naked_k_smart_money_surfaces.py
git diff --cached --check
git commit -m "fix: replace smart-money probability with advisory evidence" -m "Constraint: Technical execution must remain deep-equal
Rejected: Keep legacy score for compatibility | misleading and uncalibrated
Confidence: high
Scope-risk: broad"
```

---

### Task 5: HKEX Market Session Calendar and Phase Boundaries

**Files:**
- Create: `naked_k_market_session.py`
- Create: `data/hkex_sessions_2026.json`
- Create: `tests/test_naked_k_market_session.py`

**Interfaces:**
- Consumes: versioned official session data and timezone-aware timestamps.
- Produces: `HKTradingCalendar.resolve()`, `session_distance()`, `next_session_open()` and `classify_trade_phase()`.

The 2026 data file must contain this official schedule:

```json
{
  "schema_version": "hkex-sessions.v1",
  "year": 2026,
  "timezone": "Asia/Hong_Kong",
  "closed_dates": ["2026-01-01", "2026-02-17", "2026-02-18", "2026-02-19", "2026-04-03", "2026-04-06", "2026-04-07", "2026-05-01", "2026-05-25", "2026-06-19", "2026-07-01", "2026-10-01", "2026-10-19", "2026-12-25"],
  "half_days": ["2026-02-16", "2026-12-24", "2026-12-31"],
  "source_url": "https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/SEHK/2025/ce_SEHK_CT_075_2025.pdf",
  "source_ref": "CT/075/25"
}
```

- [ ] **Step 1: Write failing normal/half-day/unknown boundary tests.**

```python
self.assertFalse(calendar.resolve("hk", "2026-08-18", now=hkt("2026-08-18 16:09:59")).session_complete)
self.assertTrue(calendar.resolve("hk", "2026-08-18", now=hkt("2026-08-18 16:10:00")).session_complete)
self.assertFalse(calendar.resolve("hk", "2026-12-24", now=hkt("2026-12-24 12:09:59")).session_complete)
self.assertTrue(calendar.resolve("hk", "2026-12-24", now=hkt("2026-12-24 12:10:00")).session_complete)
self.assertEqual(calendar.resolve("hk", "2027-01-04", now=hkt("2027-01-04 17:00")).kind, "unknown")
```

Also test weekends/closed days, `pre_open|continuous|post_continuous_window`, Friday weekly boundary and next-session open.

- [ ] **Step 2: Run tests to confirm RED.**

Run:

```bash
python -m unittest tests.test_naked_k_market_session -v
```

- [ ] **Step 3: Implement conservative session resolution.**

Weekdays in a loaded year that are not closed/half are normal; dates outside loaded official year are unknown, never guessed. Full day is complete at 16:10 HKT; half day at 12:10 HKT. Unknown and closed sessions never claim complete. `tradable_at` for complete distribution is next official session 09:30 HKT.

- [ ] **Step 4: Run tests and commit.**

Run:

```bash
python -m unittest tests.test_naked_k_market_session -v
git add naked_k_market_session.py data/hkex_sessions_2026.json tests/test_naked_k_market_session.py
git diff --cached --check
git commit -m "feat: add explicit hong kong market sessions" -m "Constraint: Unknown future calendars must fail partial, not guess
Confidence: high
Scope-risk: narrow"
```

---

### Task 6: Eastmoney HK Trade-Print Provider

**Files:**
- Create: `naked_k_flow_eastmoney.py`
- Create: `tests/test_naked_k_flow_eastmoney.py`
- Create: `tests/fixtures/smart_money/eastmoney_hk/0700.raw.json.gz`
- Create: `tests/fixtures/smart_money/eastmoney_hk/1810.raw.json.gz`
- Create: `tests/fixtures/smart_money/eastmoney_hk/9992.raw.json.gz`
- Create: matching `*.meta.json` files

**Interfaces:**
- Consumes: ticker, `MarketSession`, injected `get`, retrieved time and `TradeFlowConfig`.
- Produces: `EastmoneyHKTradeFlowProvider.collect(...) -> TradeFlowCollection`; raw bytes and normalized snapshot remain inseparable until persistence.

```python
class EastmoneyHKTradeFlowProvider:
    provider_id = "eastmoney_hk"

    def __init__(self, get: Callable[..., Any] | None = None) -> None: ...

    def collect(self, ticker: str, session: MarketSession, *, retrieved_at: pd.Timestamp,
                config: TradeFlowConfig) -> TradeFlowCollection: ...
```

Use the exact request:

```python
URL = "https://push2.eastmoney.com/api/qt/stock/details/get"
PARAMS = {
    "fields1": "f1,f2,f3,f4,f5",
    "fields2": "f51,f52,f53,f54,f55",
    "pos": "-0",
    "iscca": "1",
    "invt": "2",
    "fltt": "2",
}
```

For HK details, parse `f51=time`, `f52=price`, `f53=shares`, retain `f54` as uninterpreted raw metadata and `f55` as `side_raw`; never map `f55` to active buy/sell. A captured row shape is `"09:00:09,447.293,13440,0,2"`.

- [ ] **Step 1: Write failing ticker/request/schema tests.**

Assert `0700.HK -> 116.00700`, `1810.HK -> 116.01810`, `9992.HK -> 116.09992`; malformed/non-HK inputs return unsupported without calling `get`. Assert exact params, five columns per detail row, `data.market==116`, matching five-digit `data.code`, and a stable redacted request fingerprint.

- [ ] **Step 2: Write failing duplicate/tick/status tests.**

Use fixture rows with identical time/price/volume and assert both ordinals survive. Test price up/down/same inheritance/first unknown. Empty data, `full!=1`, schema change, wrong session, out-of-order time and unknown unit yield the spec statuses rather than exceptions. A transport exception yields `UNAVAILABLE`.

- [ ] **Step 3: Run provider tests to confirm RED.**

Run:

```bash
python -m unittest tests.test_naked_k_flow_eastmoney -v
```

- [ ] **Step 4: Implement transport and pure normalization.**

Use `requests.get(..., params=params, timeout=config.timeout_seconds)` only inside `collect`; retry at most `max_retries`. Normalize all timestamps to `Asia/Hong_Kong`, preserve source ordinal and occurrence, compute `notional=price*shares`, classify phase through `MarketSession`, and record `coverage_start/end`, count, volume, notional and limitations. Do not silently sort an out-of-order response.

- [ ] **Step 5: Capture and document fixtures.**

Each `.meta.json` contains `source_url`, normalized params, `retrieved_at`, `session_date`, raw SHA-256, expected count/volume/notional and the statement `side_raw_not_interpreted=true`. Strip response headers/cookies and keep only response JSON.

- [ ] **Step 6: Run tests and commit.**

Run:

```bash
python -m unittest tests.test_naked_k_flow_eastmoney -v
git add naked_k_flow_eastmoney.py tests/test_naked_k_flow_eastmoney.py tests/fixtures/smart_money/eastmoney_hk
git diff --cached --check
git commit -m "feat: normalize eastmoney hk trade prints" -m "Constraint: Trade prints are not orders or verified aggressor flow
Confidence: medium
Scope-risk: moderate
Not-tested: Future undocumented Eastmoney schema stability"
```

---

### Task 7: Content-Addressed Snapshot Store and Replay

**Files:**
- Create: `naked_k_flow_store.py`
- Create: `tests/test_naked_k_flow_store.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: one `TradeFlowCollection` containing raw bytes and normalized `TradeFlowSnapshot`.
- Produces: `FileSnapshotStore.persist()`, `.load()`, `.history()` with append-only lineage.

```python
class FileSnapshotStore:
    def __init__(self, root: Path = Path("reports/market_data/trade_flow")) -> None: ...
    def persist(self, collection: TradeFlowCollection) -> TradeFlowSnapshot: ...
    def load(self, snapshot_id: str) -> TradeFlowSnapshot: ...
    def history(self, ticker: str, *, before_session: str, limit: int) -> list[TradeFlowSnapshot]: ...
```

- [ ] **Step 1: Write failing atomic-order and digest tests.**

In `TemporaryDirectory`, assert raw and normalized files exist before manifest/latest publication, path includes filesystem-safe UTC timestamp plus digest, gzip round-trip is deterministic with `mtime=0`, and both raw and normalized tampering return `INVALID` on load.

- [ ] **Step 2: Write failing manifest/rerun tests.**

Persist identical content twice at different retrieval times. Assert manifest has two distinct `retrieval_id` rows, both reference the same raw/normalized content IDs, the immutable normalized snapshot keeps the first-seen `retrieved_at`, `latest.json` points to the second retrieval envelope, and `history()` deduplicates by normalized snapshot ID before threshold calculation. Changing one semantic print changes normalized ID; changing only retrieval time does not. Inject an `os.replace` failure and assert no manifest/latest publication.

- [ ] **Step 3: Run store tests to confirm RED.**

Run:

```bash
python -m unittest tests.test_naked_k_flow_store -v
```

- [ ] **Step 4: Implement atomic content-addressed storage.**

Write same-directory temp files, verify SHA/schema, `os.replace()` raw then normalized, append one canonical manifest line, then atomically replace `latest.json`. On replay, verify raw ID, normalized ID and manifest linkage before returning. Add `reports/market_data/**` and `reports/market_data/**/*.tmp` to `.gitignore`; curated `tests/fixtures/**` remains tracked.

- [ ] **Step 5: Run tests, check ignore, and commit.**

Run:

```bash
python -m unittest tests.test_naked_k_flow_store -v
git check-ignore -v reports/market_data/example.raw.json.gz
git add naked_k_flow_store.py tests/test_naked_k_flow_store.py .gitignore
git diff --cached --check
git commit -m "feat: persist immutable trade-flow snapshots" -m "Constraint: Replay must reject digest or lineage tampering
Confidence: high
Scope-risk: moderate
Not-tested: Power-loss durability and concurrent writers"
```

---

### Task 8: Large and Extra-Large Trade-Tape Evidence

**Files:**
- Create: `naked_k_flow_evidence.py`
- Create: `tests/test_naked_k_flow_evidence.py`
- Create: `tests/smart_money_factories.py`

**Interfaces:**
- Consumes: current complete `TradeFlowSnapshot`, up to 20 deduplicated historical snapshots, decision time and optional neutral short evidence.
- Produces: one `trade_tape` `LayerResult`.

```python
def nearest_rank(values: Sequence[float], percentile: float) -> float: ...

def build_trade_flow_layer(
    current: TradeFlowSnapshot,
    history: Sequence[TradeFlowSnapshot],
    *,
    decision_time: pd.Timestamp,
    short_selling: Sequence[Evidence] = (),
) -> LayerResult: ...
```

- [ ] **Step 1: Write failing quantile/history/bootstrap tests.**

Create deterministic print factories for 999, 1000 and 1001 continuous prints. Assert nearest-rank q99/q99.9, 20 complete prior sessions excluding current, one incomparable day => not computable, bootstrap requires 1000 prints, and complete-distribution evidence is only tradable next session open.

- [ ] **Step 2: Write failing boundary/statistics tests.**

Lock `large_share==0.10`, imbalance `==±0.20`, extra-large count `==3`, imbalance `==±0.30`, coverage `==0.90`; exact boundaries trigger. Zero `T`, `LU+LD` or `EU+ED` returns `None/NOT_COMPUTABLE`, not zero. Post-continuous 15% is neutral. Simultaneous bullish/bearish evidence returns layer conflict.

- [ ] **Step 3: Run evidence tests to confirm RED.**

Run:

```bash
python -m unittest tests.test_naked_k_flow_evidence -v
```

- [ ] **Step 4: Implement spec §7 exactly.**

Only continuous prints contribute direction. `large`, `extra_large`, daily volume anomaly and tick imbalance collapse to one `dependency_group="trade_tape"`; they never count as multiple independent confirmations. Every evidence payload records observed/available/expires, thresholds, raw inputs and limitations.

- [ ] **Step 5: Run tests and commit.**

Run:

```bash
python -m unittest tests.test_naked_k_flow_evidence -v
git add naked_k_flow_evidence.py tests/test_naked_k_flow_evidence.py tests/smart_money_factories.py
git diff --cached --check
git commit -m "feat: derive deterministic trade-tape evidence" -m "Constraint: Relative per-ticker thresholds and no double counting
Confidence: high
Scope-risk: moderate"
```

---

### Task 9: HKEX Short-Selling Neutral Context

**Files:**
- Create: `naked_k_short_selling_hkex.py`
- Create: `naked_k_short_selling_store.py`
- Create: `tests/test_naked_k_short_selling_hkex.py`
- Create: `tests/test_naked_k_short_selling_store.py`
- Create: `tests/fixtures/smart_money/hkex_short_selling/main_board_day_close.txt`
- Create: `tests/fixtures/smart_money/hkex_short_selling/main_board_morning_close.txt`

**Interfaces:**
- Consumes: target ticker/session, total turnover from tape, optional comparable quote amount, history and injected `get`.
- Produces: `ShortSellingCollection`, content-addressed history, and neutral `Evidence`.

```python
class HKEXShortSellingProvider:
    def collect(self, ticker: str, session: MarketSession, *, retrieved_at: pd.Timestamp,
                total_turnover: float | None,
                config: ShortSellingConfig) -> ShortSellingCollection: ...

def build_short_selling_evidence(
    current: ShortSellingSnapshot,
    history: Sequence[ShortSellingSnapshot],
    *,
    comparable_quote_amount: float | None,
    decision_time: pd.Timestamp,
) -> Evidence: ...
```

Official endpoints:

```python
DAY_CLOSE_URL = "https://www.hkex.com.hk/eng/stat/smstat/ssturnover/ncms/ashtmain.htm"
MORNING_CLOSE_URL = "https://www.hkex.com.hk/eng/stat/smstat/ssturnover/ncms/mshtmain.htm"
```

Normal days use day-close; official half days use morning-close. Parse `TRADING DATE`, then lines matching code, stock name, short shares and short turnover. Never infer a missing row as zero.

- [ ] **Step 1: Write failing parser/status tests.**

Use a fixture line like `700  TENCENT  1,301,400  579,555,300`. Assert ticker match, integers, actual retrieval `available_at`, wrong trading date => `STALE`, missing ticker => `not_reported/NOT_COMPUTABLE`, and transport failure => `UNAVAILABLE`.

- [ ] **Step 2: Write failing reconciliation/history/store tests.**

Assert tape total versus comparable quote amount at exactly 2% passes; over 2% gives `DEFINITION_MISMATCH`; absent quote amount is `NOT_COMPUTABLE` reconciliation but does not invalidate tape total. HKD and RMB counters never combine. High short-pressure requires 20 prior complete days, inclusive prior-window q90, and still returns `direction="neutral"`. The store uses raw/normalized content IDs, publishes manifest/latest only after both files exist, deduplicates history by normalized ID and rejects tampering. Persist the same report at two retrieval times: normalized ID stays equal, retrieval IDs differ, and replayed `available_at` equals the first-seen envelope.

- [ ] **Step 3: Run tests to confirm RED.**

Run:

```bash
python -m unittest tests.test_naked_k_short_selling_hkex tests.test_naked_k_short_selling_store -v
```

- [ ] **Step 4: Implement the HKEX parser and neutral evidence.**

Use a strict line regex with code as the first numeric column and the final two comma-formatted columns as shares/turnover; names may contain spaces. Save source URL, trading date, retrieved/available times and raw/normalized snapshot IDs. Persist raw report and normalized snapshot atomically under `reports/market_data/short_selling` with the Task 1 semantic preimage/first-seen/retrieval-envelope rules; short context may add limitations/context to trade-flow output but may not set bullish/bearish direction or be arithmetically added to downtick notional.

- [ ] **Step 5: Run tests and commit.**

Run:

```bash
python -m unittest tests.test_naked_k_short_selling_hkex tests.test_naked_k_short_selling_store -v
git add naked_k_short_selling_hkex.py naked_k_short_selling_store.py tests/test_naked_k_short_selling_hkex.py tests/test_naked_k_short_selling_store.py tests/fixtures/smart_money/hkex_short_selling
git diff --cached --check
git commit -m "feat: add neutral hkex short-selling context" -m "Constraint: Missing rows are unknown and short data never proves institution identity
Confidence: medium
Scope-risk: narrow
Not-tested: Future HKEX page-format stability"
```

---

### Task 10: Full Orchestration, Smart-Money Replay, and Audit Invariants

**Files:**
- Create: `naked_k_smart_money_artifact_store.py`
- Modify: `naked_k_analysis.py:1189-1515`
- Modify: `naked_k_planner.py:25-62`
- Create: `tests/network_guard.py`
- Create: `tests/test_naked_k_smart_money_artifact_store.py`
- Create: `tests/test_naked_k_smart_money_zero_network.py`
- Create: `tests/test_naked_k_smart_money_integration.py`
- Create: `tests/test_naked_k_smart_money_invariance.py`
- Modify: `tests/test_naked_k_analysis.py`
- Modify: `tests/test_naked_k_planner.py`

**Interfaces:**
- Consumes: optional injected `SmartMoneyRuntime`, providers, stores, calendar and existing OHLCV.
- Produces: ordered audit events, immutable OHLCV/evidence artifacts, attached evidence/fusion, exact execution invariant and provider-only or full-input replay.

Final signature addition:

```python
def run_analysis(
    tickers: list[tuple[str, str]],
    journal_path: Path,
    config: naked_k_config.TradingConfig | None = None,
    audit_path: Path | None = None,
    llm_config: naked_k_llm.LLMConfig | None = None,
    llm_post: naked_k_llm.PostCallable | None = None,
    news_config: naked_k_news_llm.AnthropicNewsConfig | None = None,
    news_post: naked_k_news_llm.PostCallable | None = None,
    news_get: Callable[..., Any] | None = None,
    news_search_factory: naked_k_news.SearchFactory | None = None,
    news_lookback_days: int = 7,
    news_max_items: int = 12,
    news_bootstrap_error: dict[str, str] | None = None,
    smart_money_runtime: SmartMoneyRuntime | None = None,
) -> tuple[str, list[InstrumentReport]]: ...
```

`build_trade_plan()` remains unchanged.

`naked_k_smart_money_artifact_store.py` writes `OHLCVSnapshot` under `reports/market_data/research_ohlcv/` and `SmartMoneyEvidenceBundle` under `reports/market_data/evidence/`, using the same temp/write/verify/atomic-publish sequence as Task 7. `run_id`, bundle ID and all four input IDs propagate to report/journal/audit.

- [ ] **Step 1: Write failing zero-network and artifact-store tests.**

`tests/network_guard.py` patches both `requests.sessions.Session.request` and `socket.create_connection`. Explicitly import it in each `unittest` module; do not depend on `conftest.py`. Assert disabled mode, trade-flow disabled, non-HK and `--smart-money-offline` never call Eastmoney/HKEX. A missing flow or short replay snapshot degrades only that branch without remote fallback. Artifact tests lock OHLCV row order/unrounded values, adjustment/source metadata, content preimages, tamper rejection and atomic evidence-bundle publication. Persist the same semantic bundle with two invocation envelopes: bundle ID stays equal, envelopes/run IDs differ and both provenance rows verify.

- [ ] **Step 2: Write failing audit-order/degradation tests.**

Require per ticker:

```python
EXPECTED = [
    "data_loaded",
    "trade_flow_collection_started",
    "trade_flow_collected",  # or trade_flow_degraded
    "price_action_evidence_generated",
    "smart_money_fused",
    "plan_generated",
    "smart_money_execution_invariance_checked",
]
```

Every started event has exactly one collected/degraded terminal. Tampered replay degrades flow yet still produces base report. Requested non-HK tickers never call HK provider. News synthesis occurs only after the smart-money invariance comparison so a legitimate news action change is not blamed on smart-money.

- [ ] **Step 3: Write failing execution/portfolio invariance tests.**

For every fusion status, compare the exact execution projection before/after attachment. Build 0700/1810/9992 reports, compute portfolio exposure before and after advisory fields, and assert deep equality. If a test runtime intentionally mutates execution, orchestration restores the pre-attachment snapshot, emits failed invariance with before/after hashes and marks fusion invalid.

- [ ] **Step 4: Run orchestration tests to confirm RED.**

Run:

```bash
python -m unittest tests.test_naked_k_smart_money_artifact_store tests.test_naked_k_smart_money_zero_network tests.test_naked_k_smart_money_integration tests.test_naked_k_smart_money_invariance tests.test_naked_k_analysis tests.test_naked_k_planner -v
```

- [ ] **Step 5: Implement runtime wiring and CLI parsing.**

Add `--smart-money-offline` plus repeatable `--replay-bundle-id TICKER=sha256:...`; keep lower-level `--replay-trade-flow-id`, `--replay-short-selling-id` and `--replay-ohlcv-id` only for diagnostics. Parse them into one `SmartMoneyReplaySelection` per ticker and reject conflicting duplicate keys. Runtime defaults instantiate providers/stores/calendar only when enabled; tests inject fakes. Provider-only offline may still use fresh OHLCV and therefore guarantees only zero Eastmoney/HKEX network. Canonical identical-ID replay uses a verified bundle, which restores the same input IDs, config fingerprint and decision time.

Persist the actual daily frame used by price evidence before generating the bundle. On ordinary enabled runs also capture `^HSI` daily OHLCV into `reports/market_data/research_ohlcv/` on a best-effort, explicitly audited path; failure never affects the base report. Collect/replay flow and short context; build histories/layers; fuse; attach only advisory fields; compare execution; persist the evidence bundle; then continue existing news/LLM and journal flow.

Do not add smart-money fields to `naked_k_synthesis.TECHNICAL_SNAPSHOT_FIELDS`.

- [ ] **Step 6: Run orchestration tests to confirm GREEN.**

Run:

```bash
python -m unittest tests.test_naked_k_smart_money_artifact_store tests.test_naked_k_smart_money_zero_network tests.test_naked_k_smart_money_integration tests.test_naked_k_smart_money_invariance tests.test_naked_k_analysis tests.test_naked_k_planner -v
```

- [ ] **Step 7: Commit orchestration.**

Run:

```bash
git add naked_k_smart_money_artifact_store.py naked_k_analysis.py naked_k_planner.py tests/network_guard.py tests/test_naked_k_smart_money_artifact_store.py tests/test_naked_k_smart_money_zero_network.py tests/test_naked_k_smart_money_integration.py tests/test_naked_k_smart_money_invariance.py tests/test_naked_k_analysis.py tests/test_naked_k_planner.py
git diff --cached --check
git commit -m "feat: orchestrate advisory smart-money evidence" -m "Constraint: Provider failures and advisory data cannot mutate execution
Rejected: Put network calls in planner | breaks purity and replayability
Confidence: high
Scope-risk: broad"
```

---

### Task 11: Cross-Artifact Acceptance, Live Runner, and Documentation

**Files:**
- Create: `naked_k_smart_money_acceptance.py`
- Create: `run_smart_money_live_smoke.py`
- Create: `tests/test_naked_k_smart_money_acceptance.py`
- Modify: `naked_k_analysis.py:222-283,750-848`
- Modify: `README.md`
- Modify: CHANGELOG.md
- Modify: `docs/superpowers/smart-money-user-guide.md`
- Modify: `docs/superpowers/specs/2026-08-17-smart-money-dual-evidence-design.md`

**Interfaces:**
- Consumes: complete Phase 0–3 runtime.
- Produces: same lineage across Markdown/JSON/journal/audit, fixture acceptance, explicit live smoke and corrected user documentation.

```python
def capture_execution_projection(report: InstrumentReport) -> dict[str, Any]: ...

def validate_execution_invariance(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> tuple[bool, str, str]: ...

def validate_artifact_lineage(
    report_payload: Mapping[str, Any],
    journal_row: Mapping[str, Any],
    audit_events: Sequence[Mapping[str, Any]],
    *,
    trade_flow_store: SnapshotStore,
    short_selling_store: ShortSellingStore,
    artifact_store: SmartMoneyArtifactStore,
) -> list[str]: ...
```

The two hashes returned by `validate_execution_invariance()` are canonical SHA-256 digests. `validate_artifact_lineage()` returns deterministic error codes and an empty list on success; it must resolve and digest-check every referenced trade-flow, short-selling, OHLCV and evidence-bundle snapshot through the typed store.

- [ ] **Step 1: Write failing cross-artifact lineage tests.**

For a fixed invocation assert report, serialized JSON, journal and audit carry the same fresh `invocation_run_id`, trade-flow ID, short-selling ID when present, OHLCV ID, price evidence ID, fusion ID and bundle ID; direction/status/as-of are equal. Two independent invocations with identical semantic inputs produce the same bundle ID despite different run IDs. On bundle replay, the fresh invocation ID differs from the original, while the new envelope preserves `source_run_id`/`source_bundle_id`; evidence, fusion and bundle IDs remain equal and audit records the provenance edge. Audit must contain summaries but no `details` array or raw trade rows. Missing terminal event/provenance edge, unresolved typed snapshot/bundle or any digest mismatch fails the acceptance validator.

- [ ] **Step 2: Write failing three-fixture and live-runner contract tests.**

Assert all three captured fixtures validate count/volume/notional and metadata SHA/fingerprint. Patch the live runner runtime and require exactly `0700.HK,1810.HK,9992.HK`, news/LLM disabled, unique run directory, nonzero exit before session complete, nonzero exit when any trade provider is not `OK`, and identical evidence/fusion IDs only when replaying the verified bundle with provider network denied.

- [ ] **Step 3: Write failing documentation semantics test.**

Scan only current user-facing files, not archived delivery reports:

```python
CURRENT_DOCS = [
    "README.md", "CHANGELOG.md",
    "docs/superpowers/smart-money-user-guide.md",
]
FORBIDDEN_PHRASES = ["主力抄底概率", "主力派发概率", "识别机构/大资金", "主力长期布局"]
```

Require explicit explanations of tick-direction proxy, `UNVALIDATED`, `ADVISORY_ONLY`, provider-only offline scope and failure degradation.

- [ ] **Step 4: Run acceptance tests to confirm RED.**

Run:

```bash
python -m unittest tests.test_naked_k_smart_money_acceptance -v
```

- [ ] **Step 5: Implement acceptance validator, live runner and docs.**

The live runner accepts:

```text
--require-all-ok
--verify-artifacts
--verify-invariance
--smart-money-offline
--replay-latest
--deny-provider-network
--require-identical-ids
```

It never enables news/LLM, writes under a unique `reports/market_data/live-smoke/<run_id>/`, and prints one compact JSON result per ticker plus a final exit summary. `--replay-latest` resolves the latest verified evidence bundle per ticker and passes `--replay-bundle-id`, not an ambiguous untyped snapshot ID.

- [ ] **Step 6: Run acceptance and full regression suites.**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_naked_k_smart_money_acceptance -v
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -v
git diff --check
```

Expected: all tests pass; the suite count is greater than 447.

- [ ] **Step 7: Run the time-dependent live smoke after 16:10 HKT.**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python run_smart_money_live_smoke.py --require-all-ok --verify-artifacts --verify-invariance
PYTHONDONTWRITEBYTECODE=1 python run_smart_money_live_smoke.py --smart-money-offline --replay-latest --deny-provider-network --require-identical-ids
git check-ignore -v reports/market_data/
git status --short
```

Expected: three live trade providers are `OK`; replay IDs are identical; generated market data is ignored. HKEX short data may be unavailable without failing the trade-provider gate because it is auxiliary and neutral.

- [ ] **Step 8: Commit release surfaces.**

Run:

```bash
git add naked_k_smart_money_acceptance.py run_smart_money_live_smoke.py tests/test_naked_k_smart_money_acceptance.py naked_k_analysis.py README.md CHANGELOG.md docs/superpowers/smart-money-user-guide.md docs/superpowers/specs/2026-08-17-smart-money-dual-evidence-design.md
git diff --cached --check
git commit -m "docs: expose auditable smart-money proxy evidence" -m "Constraint: No identity claim, probability claim, or execution mutation
Confidence: high
Scope-risk: moderate
Not-tested: Long-horizon economic qualification in Phase 4"
```

## Final Verification Gate

Before declaring Phase 0–3 complete, run:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -v
rg -n "主力抄底概率|主力派发概率|probability" README.md CHANGELOG.md docs/superpowers/smart-money-user-guide.md naked_k_analysis.py naked_k_interpreter.py naked_k_smart_money.py
git diff --check
git status --short
```

Expected: full suite passes; `rg` finds no current user-facing or runtime smart-money probability claim; worktree is clean after commits. The only remaining blocker to calling the signal economically qualified is the separate Phase 4 plan.
