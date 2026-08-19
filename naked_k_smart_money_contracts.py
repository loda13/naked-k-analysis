"""
Versioned dataclasses, enums, and content ID for dual-evidence smart money.

All contracts are frozen, keyword-only, and use stable schema versions.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Protocol
import hashlib
import json
import pandas as pd


# ============================================================================
# Enums
# ============================================================================


class ProviderStatus(StrEnum):
    """Provider data availability status."""
    OK = "OK"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    DEFINITION_MISMATCH = "DEFINITION_MISMATCH"
    INVALID = "INVALID"


class Direction(StrEnum):
    """Directional bias."""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class Lifecycle(StrEnum):
    """Evidence lifecycle state."""
    OBSERVED = "observed"
    PENDING = "pending_confirmation"
    CONFIRMED = "confirmed"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
    NOT_COMPUTABLE = "not_computable"


class ParticipationState(StrEnum):
    """Smart money participation state."""
    INACTIVE = "INACTIVE"
    UNKNOWN = "UNKNOWN"
    PROVISIONAL = "PROVISIONAL"
    FORMAL_CONFLICT = "FORMAL_CONFLICT"
    FORMAL_BULLISH = "FORMAL_BULLISH"
    FORMAL_BEARISH = "FORMAL_BEARISH"
    FORMAL_NEUTRAL = "FORMAL_NEUTRAL"


# ============================================================================
# Content ID
# ============================================================================


def canonical_payload(value: Any) -> bytes:
    """
    Convert value to canonical JSON bytes for content addressing.

    Dicts are sorted by key, timestamps are ISO-8601, enums are strings.
    """
    def _serialize(obj: Any) -> Any:
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        elif isinstance(obj, StrEnum):
            return obj.value
        elif isinstance(obj, dict):
            return {k: _serialize(v) for k, v in sorted(obj.items())}
        elif isinstance(obj, (list, tuple)):
            return [_serialize(item) for item in obj]
        return obj

    serialized = _serialize(value)
    return json.dumps(serialized, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def content_id(prefix: str, value: Any) -> str:
    """
    Generate stable content ID from canonical payload.

    Returns: "sha256:<hex>"
    """
    payload = canonical_payload(value)
    digest = hashlib.sha256(payload).hexdigest()
    return f"sha256:{digest}"


def normalized_snapshot_preimage(snapshot: 'TradeFlowSnapshot | ShortSellingSnapshot') -> Mapping[str, Any]:
    """
    Extract semantic payload for normalized snapshot ID.

    Excludes: retrieved_at, raw_snapshot_id, normalized_snapshot_id, retrieval_id,
    filesystem path, acquisition-derived available_at.
    """
    d = snapshot.to_dict()
    exclude = {
        'retrieved_at', 'raw_snapshot_id', 'normalized_snapshot_id',
        'retrieval_id', 'path', 'available_at'
    }
    return {k: v for k, v in d.items() if k not in exclude}


def ohlcv_snapshot_preimage(snapshot: 'OHLCVSnapshot') -> Mapping[str, Any]:
    """
    Extract semantic payload for OHLCV snapshot ID.

    Excludes: ohlcv_snapshot_id, first_seen, path.
    """
    d = snapshot.to_dict()
    exclude = {'ohlcv_snapshot_id', 'first_seen', 'path'}
    return {k: v for k, v in d.items() if k not in exclude}


def evidence_bundle_preimage(bundle: 'SmartMoneyEvidenceBundle') -> Mapping[str, Any]:
    """
    Extract semantic payload for evidence bundle ID.

    Excludes: invocation_run_id, source_run_id, source_bundle_id,
    retrieval envelope, bundle_id, path.
    """
    d = bundle.to_dict()
    exclude = {
        'invocation_run_id', 'source_run_id', 'source_bundle_id',
        'bundle_id', 'path', 'retrieval_envelope'
    }
    return {k: v for k, v in d.items() if k not in exclude}


def retrieval_envelope_id(*, raw_snapshot_id: str, normalized_snapshot_id: str,
                          retrieved_at: pd.Timestamp) -> str:
    """
    Generate retrieval envelope ID from raw/normalized IDs and timestamp.
    """
    payload = {
        'raw_snapshot_id': raw_snapshot_id,
        'normalized_snapshot_id': normalized_snapshot_id,
        'retrieved_at': retrieved_at.isoformat(),
    }
    return content_id('retrieval', payload)


# ============================================================================
# Trade Flow
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class TradePrint:
    """Single trade print with tick direction."""
    source_ordinal: int
    occurrence_index: int
    timestamp: pd.Timestamp
    price: float
    volume: int
    tick_direction: str  # "uptick" | "downtick" | "zero_tick"
    zero_tick: bool

    def __post_init__(self):
        if self.timestamp.tz is None:
            raise ValueError("TradePrint timestamp must be timezone-aware")

    @property
    def source_row_id(self) -> str:
        """Stable row identifier: ordinal:index."""
        return f"{self.source_ordinal}:{self.occurrence_index}"

    def to_dict(self) -> dict[str, Any]:
        return {
            'source_ordinal': self.source_ordinal,
            'occurrence_index': self.occurrence_index,
            'source_row_id': self.source_row_id,
            'timestamp': self.timestamp.isoformat(),
            'price': self.price,
            'volume': self.volume,
            'tick_direction': self.tick_direction,
            'zero_tick': self.zero_tick,
        }


@dataclass(frozen=True, kw_only=True)
class TradeFlowSnapshot:
    """Immutable trade flow snapshot with schema version and content IDs."""
    schema_version: str  # "trade-flow.v1"
    ticker: str
    trading_date: str
    session_status: str
    retrieved_at: pd.Timestamp
    prints: tuple[TradePrint, ...]
    total_volume: int
    total_turnover: float
    raw_snapshot_id: str
    normalized_snapshot_id: str
    retrieval_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'schema_version': self.schema_version,
            'ticker': self.ticker,
            'trading_date': self.trading_date,
            'session_status': self.session_status,
            'retrieved_at': self.retrieved_at.isoformat(),
            'prints': [p.to_dict() for p in self.prints],
            'total_volume': self.total_volume,
            'total_turnover': self.total_turnover,
            'raw_snapshot_id': self.raw_snapshot_id,
            'normalized_snapshot_id': self.normalized_snapshot_id,
            'retrieval_id': self.retrieval_id,
        }


@dataclass(frozen=True)
class TradeFlowCollection:
    """Runtime carrier for raw payload and parsed snapshot."""
    raw_payload: bytes
    snapshot: TradeFlowSnapshot


# ============================================================================
# Short Selling
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class ShortSellingSnapshot:
    """Immutable short selling snapshot."""
    schema_version: str  # "short-selling.v1"
    ticker: str
    trading_date: str
    source_date: str
    retrieved_at: pd.Timestamp
    available_at: pd.Timestamp | None
    short_sell_shares: int | None
    short_sell_turnover: float | None
    status: str
    reconciliation_note: str | None
    raw_snapshot_id: str
    normalized_snapshot_id: str
    retrieval_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'schema_version': self.schema_version,
            'ticker': self.ticker,
            'trading_date': self.trading_date,
            'source_date': self.source_date,
            'retrieved_at': self.retrieved_at.isoformat(),
            'available_at': self.available_at.isoformat() if self.available_at else None,
            'short_sell_shares': self.short_sell_shares,
            'short_sell_turnover': self.short_sell_turnover,
            'status': self.status,
            'reconciliation_note': self.reconciliation_note,
            'raw_snapshot_id': self.raw_snapshot_id,
            'normalized_snapshot_id': self.normalized_snapshot_id,
            'retrieval_id': self.retrieval_id,
        }


@dataclass(frozen=True)
class ShortSellingCollection:
    """Runtime carrier for raw payload and parsed snapshot."""
    raw_payload: bytes
    snapshot: ShortSellingSnapshot


# ============================================================================
# OHLCV Snapshot
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class OHLCVSnapshot:
    """Immutable OHLCV input snapshot."""
    schema_version: str  # "ohlcv-input.v1"
    ticker: str
    interval: str
    timezone: str
    adjustment: str
    source: str
    first_seen: pd.Timestamp
    rows: tuple[dict[str, Any], ...]
    ohlcv_snapshot_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            'schema_version': self.schema_version,
            'ticker': self.ticker,
            'interval': self.interval,
            'timezone': self.timezone,
            'adjustment': self.adjustment,
            'source': self.source,
            'first_seen': self.first_seen.isoformat(),
            'rows': list(self.rows),
            'ohlcv_snapshot_id': self.ohlcv_snapshot_id,
        }


# ============================================================================
# Evidence
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class Evidence:
    """Single piece of evidence with lineage."""
    evidence_id: str
    rule_version: str
    observed_at: pd.Timestamp
    available_at: pd.Timestamp
    expires_at: pd.Timestamp | None
    input_snapshot_ids: tuple[str, ...]
    description: str
    direction: str
    lifecycle: str
    thresholds: dict[str, Any]
    raw_metrics: dict[str, Any]
    trigger_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            'evidence_id': self.evidence_id,
            'rule_version': self.rule_version,
            'observed_at': self.observed_at.isoformat(),
            'available_at': self.available_at.isoformat(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'input_snapshot_ids': list(self.input_snapshot_ids),
            'description': self.description,
            'direction': self.direction,
            'lifecycle': self.lifecycle,
            'thresholds': self.thresholds,
            'raw_metrics': self.raw_metrics,
            'trigger_status': self.trigger_status,
        }


@dataclass(frozen=True, kw_only=True)
class LayerResult:
    """Complete layer result with evidence and lineage."""
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

    def to_dict(self) -> dict[str, Any]:
        return {
            'schema_version': self.schema_version,
            'layer_id': self.layer_id,
            'availability': self.availability,
            'direction': self.direction,
            'lifecycle': self.lifecycle,
            'quality': self.quality,
            'as_of': self.as_of.isoformat(),
            'valid_from': self.valid_from.isoformat(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'target_session': self.target_session,
            'evidence': [e.to_dict() for e in self.evidence],
            'evidence_ids': list(self.evidence_ids),
            'lineage_ids': list(self.lineage_ids),
            'limitations': list(self.limitations),
            'validation_status': self.validation_status,
            'advisory_only': self.advisory_only,
        }


@dataclass(frozen=True, kw_only=True)
class FusionResult:
    """Fusion of trade flow and price action layers."""
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

    def to_dict(self) -> dict[str, Any]:
        return {
            'schema_version': self.schema_version,
            'fusion_id': self.fusion_id,
            'status': self.status,
            'direction': self.direction,
            'as_of': self.as_of.isoformat(),
            'trade_flow_layer_id': self.trade_flow_layer_id,
            'price_action_layer_id': self.price_action_layer_id,
            'source_evidence_ids': list(self.source_evidence_ids),
            'reason_codes': list(self.reason_codes),
            'limitations': list(self.limitations),
            'validation_status': self.validation_status,
            'advisory_only': self.advisory_only,
        }


# ============================================================================
# Evidence Bundle
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class SmartMoneyEvidenceBundle:
    """Immutable daily evidence bundle."""
    schema_version: str  # "smart-money-bundle.v1"
    ticker: str
    decision_time: pd.Timestamp
    config_fingerprint: str
    trade_flow_snapshot_id: str | None
    short_selling_snapshot_id: str | None
    ohlcv_snapshot_id: str
    price_action_layer: LayerResult
    trade_flow_layer: LayerResult | None
    fusion_result: FusionResult
    bundle_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            'schema_version': self.schema_version,
            'ticker': self.ticker,
            'decision_time': self.decision_time.isoformat(),
            'config_fingerprint': self.config_fingerprint,
            'trade_flow_snapshot_id': self.trade_flow_snapshot_id,
            'short_selling_snapshot_id': self.short_selling_snapshot_id,
            'ohlcv_snapshot_id': self.ohlcv_snapshot_id,
            'price_action_layer': self.price_action_layer.to_dict(),
            'trade_flow_layer': self.trade_flow_layer.to_dict() if self.trade_flow_layer else None,
            'fusion_result': self.fusion_result.to_dict(),
            'bundle_id': self.bundle_id,
        }


@dataclass(frozen=True, kw_only=True)
class SmartMoneyBundleEnvelope:
    """Provenance envelope for bundle replay."""
    invocation_run_id: str
    source_run_id: str
    source_bundle_id: str
    acquired_at: pd.Timestamp
    replayed_at: pd.Timestamp | None = None


# ============================================================================
# Replay Selection
# ============================================================================


@dataclass(frozen=True)
class SmartMoneyReplaySelection:
    """Replay mode snapshot selection."""
    trade_flow_snapshot_id: str | None = None
    short_selling_snapshot_id: str | None = None
    ohlcv_snapshot_id: str | None = None
    evidence_bundle_id: str | None = None


# ============================================================================
# Protocols
# ============================================================================


class MarketSession(Protocol):
    """Market session with trading boundaries."""
    pass


class TradeFlowProvider(Protocol):
    """Trade flow data provider."""
    def collect(self, ticker: str, session: MarketSession, *, retrieved_at: pd.Timestamp,
                config: Any) -> TradeFlowCollection: ...


class ShortSellingProvider(Protocol):
    """Short selling data provider."""
    def collect(self, ticker: str, session: MarketSession, *, retrieved_at: pd.Timestamp,
                total_turnover: float | None, config: Any) -> ShortSellingCollection: ...


class SnapshotStore(Protocol):
    """Trade flow snapshot persistence."""
    def persist(self, collection: TradeFlowCollection) -> TradeFlowSnapshot: ...
    def load(self, snapshot_id: str) -> TradeFlowSnapshot: ...
    def history(self, ticker: str, *, before_session: str, limit: int) -> list[TradeFlowSnapshot]: ...


class ShortSellingStore(Protocol):
    """Short selling snapshot persistence."""
    def persist(self, collection: ShortSellingCollection) -> ShortSellingSnapshot: ...
    def load(self, snapshot_id: str) -> ShortSellingSnapshot: ...
    def history(self, ticker: str, *, before_session: str, limit: int) -> list[ShortSellingSnapshot]: ...


class SmartMoneyArtifactStore(Protocol):
    """OHLCV and evidence bundle persistence."""
    def persist_ohlcv(self, ticker: str, interval: str, frame: pd.DataFrame,
                      *, retrieved_at: pd.Timestamp) -> OHLCVSnapshot: ...
    def load_ohlcv(self, snapshot_id: str) -> OHLCVSnapshot: ...
    def persist_bundle(self, bundle: SmartMoneyEvidenceBundle, *,
                       envelope: SmartMoneyBundleEnvelope) -> str: ...
    def load_bundle(self, bundle_id: str) -> SmartMoneyEvidenceBundle: ...
    def bundle_envelopes(self, bundle_id: str) -> tuple[SmartMoneyBundleEnvelope, ...]: ...
    def latest_bundle(self, ticker: str) -> SmartMoneyEvidenceBundle | None: ...


class TradingCalendar(Protocol):
    """Trading calendar for session classification."""
    pass


@dataclass(frozen=True)
class SmartMoneyRuntime:
    """Runtime wiring for smart money orchestration."""
    trade_flow_provider: TradeFlowProvider | None
    short_selling_provider: ShortSellingProvider | None
    snapshot_store: SnapshotStore
    short_selling_store: ShortSellingStore
    artifact_store: SmartMoneyArtifactStore
    calendar: TradingCalendar
    provider_offline: bool = False
    replay_by_ticker: Mapping[str, SmartMoneyReplaySelection] = field(default_factory=dict)
    now: pd.Timestamp | None = None
