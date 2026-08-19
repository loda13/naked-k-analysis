"""
Tests for naked_k_smart_money_contracts — versioned dataclasses, enums, and content ID.
"""

import unittest
import json
import pandas as pd
from datetime import datetime, timezone

from naked_k_smart_money_contracts import (
    ProviderStatus,
    Direction,
    Lifecycle,
    ParticipationState,
    TradePrint,
    TradeFlowSnapshot,
    ShortSellingSnapshot,
    LayerResult,
    FusionResult,
    Evidence,
    canonical_payload,
    content_id,
)


class TestEnums(unittest.TestCase):
    """Test enum stability and serialization."""

    def test_provider_status_values(self):
        self.assertEqual(ProviderStatus.OK, "OK")
        self.assertEqual(ProviderStatus.PARTIAL, "PARTIAL")
        self.assertEqual(ProviderStatus.STALE, "STALE")
        self.assertEqual(ProviderStatus.UNAVAILABLE, "UNAVAILABLE")
        self.assertEqual(ProviderStatus.DEFINITION_MISMATCH, "DEFINITION_MISMATCH")
        self.assertEqual(ProviderStatus.INVALID, "INVALID")

    def test_direction_values(self):
        self.assertEqual(Direction.BULLISH, "bullish")
        self.assertEqual(Direction.BEARISH, "bearish")
        self.assertEqual(Direction.NEUTRAL, "neutral")
        self.assertEqual(Direction.CONFLICT, "conflict")
        self.assertEqual(Direction.UNKNOWN, "unknown")

    def test_lifecycle_values(self):
        self.assertEqual(Lifecycle.OBSERVED, "observed")
        self.assertEqual(Lifecycle.PENDING, "pending_confirmation")
        self.assertEqual(Lifecycle.CONFIRMED, "confirmed")
        self.assertEqual(Lifecycle.INVALIDATED, "invalidated")
        self.assertEqual(Lifecycle.EXPIRED, "expired")
        self.assertEqual(Lifecycle.NOT_COMPUTABLE, "not_computable")

    def test_participation_state_roundtrip(self):
        for state in ParticipationState:
            self.assertEqual(ParticipationState(state.value), state)


class TestTradePrint(unittest.TestCase):
    """Test TradePrint schema and row ID stability."""

    def test_trade_print_duplicates_keep_distinct_row_ids(self):
        first = TradePrint(
            source_ordinal=0,
            occurrence_index=0,
            timestamp=pd.Timestamp("2026-08-19 10:00:00", tz="UTC"),
            price=100.0,
            volume=1000,
            tick_direction="uptick",
            zero_tick=False,
        )
        second = TradePrint(
            source_ordinal=1,
            occurrence_index=1,
            timestamp=pd.Timestamp("2026-08-19 10:00:01", tz="UTC"),
            price=100.0,
            volume=1000,
            tick_direction="uptick",
            zero_tick=False,
        )
        self.assertEqual(first.source_row_id, "0:0")
        self.assertEqual(second.source_row_id, "1:1")

    def test_naive_timestamp_raises(self):
        with self.assertRaises(ValueError):
            TradePrint(
                source_ordinal=0,
                occurrence_index=0,
                timestamp=pd.Timestamp("2026-08-19 10:00:00"),  # naive
                price=100.0,
                volume=1000,
                tick_direction="uptick",
                zero_tick=False,
            )


class TestTradeFlowSnapshot(unittest.TestCase):
    """Test TradeFlowSnapshot exact schema."""

    def test_exact_schema_version(self):
        snapshot = TradeFlowSnapshot(
            schema_version="trade-flow.v1",
            ticker="0700.HK",
            trading_date="2026-08-19",
            session_status="complete",
            retrieved_at=pd.Timestamp("2026-08-19 16:10:00", tz="UTC"),
            prints=(),
            total_volume=0,
            total_turnover=0.0,
            raw_snapshot_id="sha256:abc",
            normalized_snapshot_id="sha256:def",
        )
        self.assertEqual(snapshot.schema_version, "trade-flow.v1")

    def test_required_keys_in_dict(self):
        snapshot = TradeFlowSnapshot(
            schema_version="trade-flow.v1",
            ticker="0700.HK",
            trading_date="2026-08-19",
            session_status="complete",
            retrieved_at=pd.Timestamp("2026-08-19 16:10:00", tz="UTC"),
            prints=(),
            total_volume=0,
            total_turnover=0.0,
            raw_snapshot_id="sha256:abc",
            normalized_snapshot_id="sha256:def",
        )
        d = snapshot.to_dict()
        required_keys = {
            "schema_version", "ticker", "trading_date", "session_status",
            "retrieved_at", "prints", "total_volume", "total_turnover",
            "raw_snapshot_id", "normalized_snapshot_id",
        }
        self.assertTrue(required_keys.issubset(d.keys()))


class TestLayerResult(unittest.TestCase):
    """Test LayerResult has no probability/score and UNVALIDATED by default."""

    def test_new_contracts_have_no_probability_or_numeric_score(self):
        layer = LayerResult(
            schema_version="layer.v1",
            layer_id="test-layer",
            availability="available",
            direction="bullish",
            lifecycle="observed",
            quality="high",
            as_of=pd.Timestamp("2026-08-19 16:00:00", tz="UTC"),
            valid_from=pd.Timestamp("2026-08-19 16:00:00", tz="UTC"),
            expires_at=None,
            target_session="2026-08-20",
            evidence=(),
            evidence_ids=(),
            lineage_ids=(),
            limitations=(),
        )
        encoded = json.dumps(layer.to_dict(), ensure_ascii=False)
        self.assertNotIn("probability", encoded)
        self.assertNotIn("strength_score", encoded)
        self.assertNotIn("heuristic_score", encoded)
        self.assertEqual(layer.validation_status, "UNVALIDATED")

    def test_layer_result_dict_has_advisory_only_true(self):
        layer = LayerResult(
            schema_version="layer.v1",
            layer_id="test-layer",
            availability="available",
            direction="bullish",
            lifecycle="observed",
            quality="high",
            as_of=pd.Timestamp("2026-08-19 16:00:00", tz="UTC"),
            valid_from=pd.Timestamp("2026-08-19 16:00:00", tz="UTC"),
            expires_at=None,
            target_session="2026-08-20",
            evidence=(),
            evidence_ids=(),
            lineage_ids=(),
            limitations=(),
        )
        d = layer.to_dict()
        self.assertEqual(d["validation_status"], "UNVALIDATED")
        self.assertEqual(d["advisory_only"], True)


class TestContentID(unittest.TestCase):
    """Test canonical payload and content ID stability."""

    def test_canonical_content_id_is_order_independent(self):
        id1 = content_id("evidence", {"b": 2, "a": 1})
        id2 = content_id("evidence", {"a": 1, "b": 2})
        self.assertEqual(id1, id2)

    def test_content_id_prefix_included(self):
        cid = content_id("test-prefix", {"key": "value"})
        self.assertTrue(cid.startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
