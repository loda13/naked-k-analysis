"""
tests/test_naked_k_price_evidence_lifecycle.py

价格证据生命周期测试 - pending/confirmed/expired 状态转换
"""

import unittest
from datetime import timedelta

import pandas as pd

from naked_k_price_evidence import build_price_action_layer
from naked_k_config import PriceActionEvidenceConfig


def _baseline_frame(periods: int = 20, base_price: float = 100.0) -> pd.DataFrame:
    """创建基线K线"""
    dates = pd.date_range(start="2024-01-01", periods=periods, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "Open": base_price,
            "High": base_price * 1.01,
            "Low": base_price * 0.99,
            "Close": base_price,
            "Volume": 1000000.0,
        },
        index=dates,
    )


class TestEvidenceStability(unittest.TestCase):
    """测试证据ID稳定性"""

    def setUp(self):
        self.config = PriceActionEvidenceConfig()

    def test_future_bars_do_not_change_prior_evidence_id(self):
        """§8: 未来K线不改变已有证据的 evidence_id"""
        frame_base = _baseline_frame(periods=20)
        signal_date = pd.Timestamp("2024-01-21", tz="UTC")
        frame_base.loc[signal_date] = {
            "Open": 98.5,
            "High": 99.5,
            "Low": 98.0,
            "Close": 99.3,
            "Volume": 1600000.0,
        }

        decision_minus_two = pd.Timestamp("2024-01-22 16:00:00", tz="UTC")
        decision = pd.Timestamp("2024-01-24 16:00:00", tz="UTC")

        # 添加两根确认K
        confirm_date_1 = pd.Timestamp("2024-01-22", tz="UTC")
        confirm_date_2 = pd.Timestamp("2024-01-23", tz="UTC")
        frame_base.loc[confirm_date_1] = {"Open": 99.0, "High": 99.8, "Low": 98.8, "Close": 99.5, "Volume": 1100000.0}
        frame_base.loc[confirm_date_2] = {"Open": 99.5, "High": 100.2, "Low": 99.3, "Close": 100.0, "Volume": 1200000.0}

        frame_pending = frame_base.iloc[:-2]
        frame_confirmed = frame_base

        zone = {
            "kind": "demand",
            "zone_id": "zone-1",
            "lower": 98.0,
            "upper": 99.0,
            "midpoint": 98.5,
            "source": "swing_cluster",
            "member_dates": ["2024-01-05"],
        }

        pending = build_price_action_layer(
            frame_pending,
            zones=[zone],
            liquidity_pools=[],
            market_structure={"direction": "down"},
            patterns=[],
            decision_time=decision_minus_two,
            config=self.config,
        )
        confirmed = build_price_action_layer(
            frame_confirmed,
            zones=[zone],
            liquidity_pools=[],
            market_structure={"direction": "down"},
            patterns=[],
            decision_time=decision,
            config=self.config,
        )

        self.assertEqual(pending.lifecycle, "pending_confirmation")
        self.assertEqual(confirmed.lifecycle, "confirmed")

        # 确认后的证据应引用 pending 证据ID
        pending_id = pending.evidence[0].evidence_id
        confirmed_evidence = confirmed.evidence[0]
        self.assertIn(pending_id, confirmed_evidence.lineage_ids)

        # observed_at < available_at
        pending_observed = pd.Timestamp(pending.evidence[0].observed_at)
        confirmed_available = pd.Timestamp(confirmed_evidence.available_at)
        self.assertLess(pending_observed, confirmed_available)


class TestMarkupConfirmation(unittest.TestCase):
    """测试 markup confirmation 规则"""

    def setUp(self):
        self.config = PriceActionEvidenceConfig()

    def test_markup_confirmation_within_five_days(self):
        """§8.1: 五日内 Close > signal_high 确认"""
        frame = _baseline_frame(periods=20)
        signal_date = pd.Timestamp("2024-01-21", tz="UTC")
        frame.loc[signal_date] = {
            "Open": 98.5,
            "High": 99.5,  # signal_high
            "Low": 98.0,
            "Close": 99.3,
            "Volume": 1600000.0,
        }

        # 第三日突破
        confirm_date = pd.Timestamp("2024-01-24", tz="UTC")
        frame.loc[confirm_date] = {
            "Open": 99.5,
            "High": 100.5,
            "Low": 99.3,
            "Close": 100.2,  # > 99.5
            "Volume": 1300000.0,
        }

        decision = pd.Timestamp("2024-01-25 16:00:00", tz="UTC")
        zone = {
            "kind": "demand",
            "zone_id": "zone-1",
            "lower": 98.0,
            "upper": 99.0,
            "midpoint": 98.5,
            "source": "swing_cluster",
            "member_dates": ["2024-01-05"],
        }

        layer = build_price_action_layer(
            frame,
            zones=[zone],
            liquidity_pools=[],
            market_structure={"direction": "down"},
            patterns=[],
            decision_time=decision,
            config=self.config,
        )

        markup_evidence = next((e for e in layer.evidence if e.kind == "markup_confirmation"), None)
        self.assertIsNotNone(markup_evidence, "应检测到 markup_confirmation")
        self.assertEqual(layer.lifecycle, "confirmed")


class TestInvalidationBeforeExpiry(unittest.TestCase):
    """测试失效早于过期"""

    def setUp(self):
        self.config = PriceActionEvidenceConfig()

    def test_invalidation_before_expiry_changes_lifecycle_to_expired(self):
        """§8.1: 跌破 signal_low 立即失效"""
        frame = _baseline_frame(periods=20)
        signal_date = pd.Timestamp("2024-01-21", tz="UTC")
        frame.loc[signal_date] = {
            "Open": 98.5,
            "High": 99.5,
            "Low": 98.0,  # signal_low
            "Close": 99.3,
            "Volume": 1600000.0,
        }

        # 第二日跌破
        invalidate_date = pd.Timestamp("2024-01-23", tz="UTC")
        frame.loc[invalidate_date] = {
            "Open": 98.5,
            "High": 98.8,
            "Low": 97.5,
            "Close": 97.8,  # < 98.0
            "Volume": 1200000.0,
        }

        decision = pd.Timestamp("2024-01-24 16:00:00", tz="UTC")
        zone = {
            "kind": "demand",
            "zone_id": "zone-1",
            "lower": 98.0,
            "upper": 99.0,
            "midpoint": 98.5,
            "source": "swing_cluster",
            "member_dates": ["2024-01-05"],
        }

        layer = build_price_action_layer(
            frame,
            zones=[zone],
            liquidity_pools=[],
            market_structure={"direction": "down"},
            patterns=[],
            decision_time=decision,
            config=self.config,
        )

        self.assertEqual(layer.lifecycle, "expired")


class TestPendingLastBars(unittest.TestCase):
    """测试最后两根K线保持 pending"""

    def setUp(self):
        self.config = PriceActionEvidenceConfig()

    def test_last_two_bars_remain_pending_without_future_confirmation(self):
        """§8.3: 最后两根K线只能标记 pending_confirmation"""
        frame = _baseline_frame(periods=21)
        # 倒数第二根是信号K
        signal_date = frame.index[-2]
        frame.loc[signal_date, "Volume"] = 1600000.0
        frame.loc[signal_date, "Close"] = 99.3
        frame.loc[signal_date, "Low"] = 98.0
        frame.loc[signal_date, "High"] = 99.5

        decision = pd.Timestamp(frame.index[-1]) + timedelta(hours=16)
        zone = {
            "kind": "demand",
            "zone_id": "zone-1",
            "lower": 98.0,
            "upper": 99.0,
            "midpoint": 98.5,
            "source": "swing_cluster",
            "member_dates": [str(frame.index[5].date())],
        }

        layer = build_price_action_layer(
            frame,
            zones=[zone],
            liquidity_pools=[],
            market_structure={"direction": "down"},
            patterns=[],
            decision_time=decision,
            config=self.config,
        )

        self.assertEqual(layer.lifecycle, "pending_confirmation")


class TestBearishGoldenMirror(unittest.TestCase):
    """测试 bearish 规则是 bullish 的精确镜像"""

    def setUp(self):
        self.config = PriceActionEvidenceConfig()

    def test_bearish_absorption_mirrors_bullish_via_ohlc_negation(self):
        """§8.2: bearish = -O/-L/-H/-C + offset"""
        # Bullish frame
        bullish_frame = _baseline_frame(periods=20, base_price=100.0)
        signal_date = pd.Timestamp("2024-01-21", tz="UTC")
        bullish_frame.loc[signal_date] = {
            "Open": 98.5,
            "High": 99.5,
            "Low": 98.0,
            "Close": 99.15,
            "Volume": 1500000.0,
        }

        # Bearish frame: negate and offset
        offset = 200.0
        bearish_frame = bullish_frame.copy()
        for col in ["Open", "High", "Low", "Close"]:
            bearish_frame[col] = -bullish_frame[col] + offset
        # Swap High and Low after negation
        bearish_frame[["High", "Low"]] = bearish_frame[["Low", "High"]]

        decision = pd.Timestamp("2024-01-22 16:00:00", tz="UTC")
        demand_zone = {
            "kind": "demand",
            "zone_id": "zone-1",
            "lower": 98.0,
            "upper": 99.0,
            "midpoint": 98.5,
            "source": "swing_cluster",
            "member_dates": ["2024-01-05"],
        }
        supply_zone = {
            "kind": "supply",
            "zone_id": "zone-2",
            "lower": offset - 99.0,
            "upper": offset - 98.0,
            "midpoint": offset - 98.5,
            "source": "swing_cluster",
            "member_dates": ["2024-01-05"],
        }

        bullish_layer = build_price_action_layer(
            bullish_frame,
            zones=[demand_zone],
            liquidity_pools=[],
            market_structure={"direction": "down"},
            patterns=[],
            decision_time=decision,
            config=self.config,
        )
        bearish_layer = build_price_action_layer(
            bearish_frame,
            zones=[supply_zone],
            liquidity_pools=[],
            market_structure={"direction": "up"},
            patterns=[],
            decision_time=decision,
            config=self.config,
        )

        self.assertEqual(bullish_layer.direction, "bullish")
        self.assertEqual(bearish_layer.direction, "bearish")
        self.assertEqual(len(bullish_layer.evidence), len(bearish_layer.evidence))


if __name__ == "__main__":
    unittest.main()
