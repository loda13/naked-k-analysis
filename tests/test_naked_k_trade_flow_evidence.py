"""
tests/test_naked_k_trade_flow_evidence.py

逐笔成交证据生成器测试
"""

import unittest
from datetime import datetime, timezone

from naked_k_flow_eastmoney import TradeFlowSnapshot, TradePrint
from naked_k_trade_flow_evidence import (
    generate_trade_flow_evidence,
    _compute_bootstrap_thresholds,
    _compute_evidence_id,
)


def _make_snapshot(
    ticker: str,
    session_date: str,
    trades: list[TradePrint],
    session_complete: bool = True,
) -> TradeFlowSnapshot:
    """创建测试用快照"""
    total_volume = sum(t.volume for t in trades)
    total_notional = sum(t.notional for t in trades)

    return TradeFlowSnapshot(
        schema_version="trade-flow.v1",
        ticker=ticker,
        market="hk",
        session_date=session_date,
        timezone="Asia/Hong_Kong",
        provider="eastmoney",
        source_url="https://test",
        request_fingerprint="test",
        status="OK",
        retrieved_at=datetime.now(timezone.utc),
        coverage_start=trades[0].trade_time if trades else None,
        coverage_end=trades[-1].trade_time if trades else None,
        session_complete=session_complete,
        currency="HKD",
        price_unit="per_share",
        volume_unit="shares",
        trade_count=len(trades),
        total_volume=total_volume,
        total_notional=total_notional,
        classified_notional_coverage=1.0,
        raw_snapshot_id="sha256:test",
        normalized_snapshot_id="sha256:normalized-test",
        limitations=(),
        trades=tuple(trades),
    )


class TestEvidenceIdGeneration(unittest.TestCase):
    """测试证据ID生成"""

    def test_evidence_id_format(self):
        """证据ID格式正确"""
        evidence_id = _compute_evidence_id(
            "large_uptick_print_concentration",
            "2026-08-19",
            "0700.HK",
            datetime(2026, 8, 19, 16, 10, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(evidence_id.startswith("evidence-large_uptick_print_concentration-"))
        self.assertEqual(len(evidence_id.split("-")[-1]), 16)  # 16位哈希


class TestBootstrapThresholds(unittest.TestCase):
    """测试 bootstrap 阈值计算"""

    def test_insufficient_trades_returns_not_computable(self):
        """少于1000笔返回 NOT_COMPUTABLE"""
        trades = [
            TradePrint(
                source_ordinal=i,
                occurrence_index=0,
                trade_time=datetime(2026, 8, 19, 10, 0, 0, tzinfo=timezone.utc),
                price=100.0 + i * 0.1,
                volume=100,
                notional=(100.0 + i * 0.1) * 100,
                session_phase="continuous",
                side_raw="1",
                tick_direction="uptick",
                classification_method="tick_rule",
                source_row_id=f"{i}:0",
            )
            for i in range(500)
        ]
        snapshot = _make_snapshot("0700.HK", "2026-08-19", trades)

        thresholds = _compute_bootstrap_thresholds(snapshot)
        self.assertEqual(thresholds["method"], "NOT_COMPUTABLE")
        self.assertIsNone(thresholds["large_threshold"])

    def test_bootstrap_computes_percentiles(self):
        """足够多笔可以计算 bootstrap 阈值"""
        trades = [
            TradePrint(
                source_ordinal=i,
                occurrence_index=0,
                trade_time=datetime(2026, 8, 19, 10, 0, 0, tzinfo=timezone.utc),
                price=100.0,
                volume=100 + i,  # 递增的成交量
                notional=100.0 * (100 + i),
                session_phase="continuous",
                side_raw="1",
                tick_direction="uptick",
                classification_method="tick_rule",
                source_row_id=f"{i}:0",
            )
            for i in range(1500)
        ]
        snapshot = _make_snapshot("0700.HK", "2026-08-19", trades)

        thresholds = _compute_bootstrap_thresholds(snapshot)
        self.assertEqual(thresholds["method"], "BOOTSTRAP")
        self.assertIsNotNone(thresholds["large_threshold"])
        self.assertIsNotNone(thresholds["extra_large_threshold"])
        self.assertGreater(thresholds["extra_large_threshold"], thresholds["large_threshold"])


class TestEvidenceGeneration(unittest.TestCase):
    """测试证据生成"""

    def test_no_evidence_when_snapshot_unavailable(self):
        """数据不可用时不生成证据"""
        snapshot = TradeFlowSnapshot(
            schema_version="trade-flow.v1",
            ticker="0700.HK",
            market="hk",
            session_date="2026-08-19",
            timezone="Asia/Hong_Kong",
            provider="eastmoney",
            source_url="https://test",
            request_fingerprint="",
            status="UNAVAILABLE",
            retrieved_at=datetime.now(timezone.utc),
            coverage_start=None,
            coverage_end=None,
            session_complete=False,
            currency="HKD",
            price_unit="per_share",
            volume_unit="shares",
            trade_count=0,
            total_volume=None,
            total_notional=None,
            classified_notional_coverage=0.0,
            raw_snapshot_id="",
            normalized_snapshot_id="",
            limitations=("no_data",),
            trades=(),
        )

        evidences = generate_trade_flow_evidence(snapshot)
        self.assertEqual(len(evidences), 0)

    def test_large_uptick_concentration_evidence(self):
        """检测大额上涨tick集中证据"""
        # 创建1500笔成交，其中大额成交集中在上涨tick
        trades = []
        base_notional = 10000.0  # 普通成交
        large_notional = 1000000.0  # 大额成交（超过99%）

        # 1000笔普通成交
        for i in range(1000):
            trades.append(TradePrint(
                source_ordinal=i,
                occurrence_index=0,
                trade_time=datetime(2026, 8, 19, 10, 0, i % 60, tzinfo=timezone.utc),
                price=100.0,
                volume=100,
                notional=base_notional,
                session_phase="continuous",
                side_raw="1",
                tick_direction="uptick" if i % 2 == 0 else "downtick",
                classification_method="tick_rule",
                source_row_id=f"{i}:0",
            ))

        # 500笔大额成交，集中在上涨tick
        for i in range(1000, 1500):
            trades.append(TradePrint(
                source_ordinal=i,
                occurrence_index=0,
                trade_time=datetime(2026, 8, 19, 14, 0, (i - 1000) % 60, tzinfo=timezone.utc),
                price=100.0,
                volume=10000,
                notional=large_notional,
                session_phase="continuous",
                side_raw="1",
                tick_direction="uptick",  # 全部上涨
                classification_method="tick_rule",
                source_row_id=f"{i}:0",
            ))

        snapshot = _make_snapshot("0700.HK", "2026-08-19", trades)
        evidences = generate_trade_flow_evidence(snapshot)

        # 应检测到 large_uptick_print_concentration
        uptick_evidences = [e for e in evidences if e.kind == "large_uptick_print_concentration"]
        self.assertGreater(len(uptick_evidences), 0)

        evidence = uptick_evidences[0]
        self.assertEqual(evidence.direction, "bullish")
        self.assertEqual(evidence.family, "trade_tape")
        self.assertEqual(evidence.validation_status, "UNVALIDATED")
        self.assertIn("provisional", evidence.thresholds)
        self.assertTrue(evidence.thresholds["provisional"])

    def test_extra_large_downtick_cluster_evidence(self):
        """检测超大额下跌tick集聚证据"""
        trades = []
        base_notional = 10000.0
        extra_large_notional = 5000000.0  # 超大额（超过99.9%）

        # 1000笔普通成交
        for i in range(1000):
            trades.append(TradePrint(
                source_ordinal=i,
                occurrence_index=0,
                trade_time=datetime(2026, 8, 19, 10, 0, i % 60, tzinfo=timezone.utc),
                price=100.0,
                volume=100,
                notional=base_notional,
                session_phase="continuous",
                side_raw="1",
                tick_direction="uptick",
                classification_method="tick_rule",
                source_row_id=f"{i}:0",
            ))

        # 5笔超大额成交，全部下跌tick
        for i in range(1000, 1005):
            trades.append(TradePrint(
                source_ordinal=i,
                occurrence_index=0,
                trade_time=datetime(2026, 8, 19, 15, 0, i - 1000, tzinfo=timezone.utc),
                price=100.0,
                volume=50000,
                notional=extra_large_notional,
                session_phase="continuous",
                side_raw="2",
                tick_direction="downtick",
                classification_method="tick_rule",
                source_row_id=f"{i}:0",
            ))

        snapshot = _make_snapshot("0700.HK", "2026-08-19", trades)
        evidences = generate_trade_flow_evidence(snapshot)

        # 应检测到 extra_large_downtick_cluster
        downtick_evidences = [e for e in evidences if e.kind == "extra_large_downtick_cluster"]
        self.assertGreater(len(downtick_evidences), 0)

        evidence = downtick_evidences[0]
        self.assertEqual(evidence.direction, "bearish")
        self.assertGreaterEqual(evidence.inputs["extra_large_downtick_count"], 3)

    def test_lifecycle_pending_when_session_incomplete(self):
        """会话未完成时生命周期为 pending_confirmation"""
        trades = []
        large_notional = 1000000.0

        for i in range(1500):
            trades.append(TradePrint(
                source_ordinal=i,
                occurrence_index=0,
                trade_time=datetime(2026, 8, 19, 10, 0, i % 60, tzinfo=timezone.utc),
                price=100.0,
                volume=10000 if i >= 1000 else 100,
                notional=large_notional if i >= 1000 else 10000.0,
                session_phase="continuous",
                side_raw="1",
                tick_direction="uptick",
                classification_method="tick_rule",
                source_row_id=f"{i}:0",
            ))

        snapshot = _make_snapshot("0700.HK", "2026-08-19", trades, session_complete=False)
        evidences = generate_trade_flow_evidence(snapshot)

        if evidences:
            self.assertEqual(evidences[0].lifecycle, "pending_confirmation")
            self.assertIn("session_incomplete", evidences[0].limitations)


if __name__ == "__main__":
    unittest.main()
