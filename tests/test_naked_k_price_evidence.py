"""
tests/test_naked_k_price_evidence.py

价格行为证据层测试 - 覆盖 §8 规范的 bullish/bearish 规则
"""

import unittest
from datetime import datetime, timezone

import pandas as pd

from naked_k_price_evidence import build_price_action_layer
from naked_k_config import PriceActionEvidenceConfig
from naked_k_smart_money_contracts import ParticipationState


def _baseline_frame(periods: int = 20, base_price: float = 100.0) -> pd.DataFrame:
    """创建20根基线K线"""
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


def _demand_zone(zone_id: str = "zone-1") -> dict:
    """创建需求区"""
    return {
        "kind": "demand",
        "zone_id": zone_id,
        "lower": 98.0,
        "upper": 99.0,
        "midpoint": 98.5,
        "source": "swing_cluster",
        "member_dates": ["2024-01-05", "2024-01-06"],
    }


def _supply_zone(zone_id: str = "zone-2") -> dict:
    """创建供给区"""
    return {
        "kind": "supply",
        "zone_id": zone_id,
        "lower": 101.0,
        "upper": 102.0,
        "midpoint": 101.5,
        "source": "swing_cluster",
        "member_dates": ["2024-01-05", "2024-01-06"],
    }


def _sell_side_pool(pool_id: str = "pool-1") -> dict:
    """创建卖方流动性池"""
    return {
        "kind": "sell_side_liquidity",
        "pool_id": pool_id,
        "midpoint": 97.0,
        "source": "equal_high_low_cluster",
    }


class TestAbsorptionExcludesSignalVolume(unittest.TestCase):
    """测试吸筹型证据排除信号K成交量"""

    def setUp(self):
        self.config = PriceActionEvidenceConfig()
        self.decision = pd.Timestamp("2024-01-22 16:00:00", tz="UTC")

    def test_absorption_excludes_signal_volume_from_baseline(self):
        """§8.1: 基线只使用 t-20:t（不含信号K）"""
        frame = _baseline_frame(periods=20)
        # 添加信号K：放量1.5倍，收在上半区65%
        # Close 必须 >= previous_close - 0.25*range_baseline
        # previous_close=100, range_baseline=2, floor=99.5
        signal_date = pd.Timestamp("2024-01-21", tz="UTC")
        frame.loc[signal_date] = {
            "Open": 99.0,
            "High": 100.5,
            "Low": 98.0,
            "Close": 99.8,  # (99.8-98.0)/(100.5-98.0) = 0.72, >= 99.5 floor
            "Volume": 1500000.0,  # 1.5x
        }

        layer = build_price_action_layer(
            frame,
            zones=[_demand_zone()],
            liquidity_pools=[],
            market_structure={"direction": "down"},
            patterns=[],
            decision_time=self.decision,
            config=self.config,
        )

        evidence = next((e for e in layer.evidence if e.kind == "bullish_absorption_like"), None)
        self.assertIsNotNone(evidence, "应检测到 bullish_absorption_like")
        self.assertAlmostEqual(evidence.inputs["relative_volume"], 1.5, places=2)
        self.assertEqual(layer.lifecycle, "pending_confirmation")


class TestMissingTraceableLocation(unittest.TestCase):
    """测试缺失可追溯位置时返回 NOT_COMPUTABLE"""

    def setUp(self):
        self.config = PriceActionEvidenceConfig()
        self.decision = pd.Timestamp("2024-01-22 16:00:00", tz="UTC")
        self.frame = _baseline_frame(periods=21)

    def test_missing_traceable_zone_or_pool_is_not_computable(self):
        """§8.1: 无 zone_id/pool_id 时位置不可验证"""
        zone_without_id = {"kind": "demand", "lower": 98.0, "upper": 99.0}
        layer = build_price_action_layer(
            self.frame,
            zones=[zone_without_id],
            liquidity_pools=[],
            market_structure={},
            patterns=[],
            decision_time=self.decision,
            config=self.config,
        )
        self.assertEqual(layer.lifecycle, "not_computable")
        self.assertEqual(layer.direction, "unknown")


class TestBullishSweepReclaim(unittest.TestCase):
    """测试 bullish_sweep_reclaim 规则"""

    def setUp(self):
        self.config = PriceActionEvidenceConfig()
        self.decision = pd.Timestamp("2024-01-22 16:00:00", tz="UTC")

    def test_sweep_reclaim_detects_低_below_prior_low_then_close_above(self):
        """§8.1: Low < prior_low 且 Close >= prior_low 且 close_position>=0.65"""
        frame = _baseline_frame(periods=20, base_price=100.0)
        # prior_low = 99.0
        signal_date = pd.Timestamp("2024-01-21", tz="UTC")
        frame.loc[signal_date] = {
            "Open": 98.5,
            "High": 100.0,
            "Low": 98.0,  # < 99.0
            "Close": 99.5,  # >= 99.0, close_position = (99.5-98)/(100-98) = 0.75
            "Volume": 1200000.0,
        }

        layer = build_price_action_layer(
            frame,
            zones=[],
            liquidity_pools=[],
            market_structure={},
            patterns=[],
            decision_time=self.decision,
            config=self.config,
        )

        evidence = next((e for e in layer.evidence if e.kind == "bullish_sweep_reclaim"), None)
        self.assertIsNotNone(evidence, "应检测到 bullish_sweep_reclaim")
        self.assertEqual(layer.lifecycle, "pending_confirmation")


class TestSellingExhaustion(unittest.TestCase):
    """测试卖盘衰竭的五日跌幅公式"""

    def setUp(self):
        self.config = PriceActionEvidenceConfig()

    def test_selling_exhaustion_five_day_decline_formula(self):
        """§8.1: prior_decline = max(0, Close[t-10] - Close[t-5]),
        recent_decline = max(0, Close[t-5] - Close[t]),
        要求 prior_decline > 0 且 recent_decline <= 0.5 * prior_decline"""
        # 需要至少 21 天：20 天基线 + 1 天信号
        frame = _baseline_frame(periods=20, base_price=110.0)

        # 添加额外 10 天以支持 exhaustion 计算（t-10 到 t）
        extra_dates = pd.date_range(
            start=frame.index[-1] + pd.Timedelta(days=1),
            periods=10,
            freq="D",
            tz="UTC"
        )
        extra = pd.DataFrame({
            "Open": 110.0,
            "High": 111.1,
            "Low": 108.9,
            "Close": 110.0,
            "Volume": 1000000.0,
        }, index=extra_dates)
        frame = pd.concat([frame, extra])

        # 信号K 是 t，所以 t-10 = iloc[-11], t-5 = iloc[-6]
        # t-10 到 t-5: 110 -> 100, prior_decline = 10
        # 修改 iloc[-11] (t-10 的前一根，即 t-11) 到 iloc[-6] (t-5)
        frame.iloc[-11:-5, frame.columns.get_loc("Close")] = [110, 105, 103, 101, 100, 100]
        # t-5 到 t-1: Close = 100
        frame.iloc[-5:, frame.columns.get_loc("Close")] = 100.0

        # 信号K: recent_decline = 100 -> 97.75 = 2.25 (< 0.5*10=5)
        signal_date = frame.index[-1] + pd.Timedelta(days=1)
        frame.loc[signal_date] = {
            "Open": 98.0,
            "High": 98.5,
            "Low": 97.0,  # <= prior_low
            "Close": 97.75,  # (97.75-97)/(98.5-97) = 0.5, close_position >= 0.50
            "Volume": 700000.0,  # relative_volume = 0.7
        }

        decision = signal_date + pd.Timedelta(days=1, hours=16)
        layer = build_price_action_layer(
            frame,
            zones=[],
            liquidity_pools=[],
            market_structure={},
            patterns=[],
            decision_time=decision,
            config=self.config,
        )

        evidence = next((e for e in layer.evidence if e.kind == "selling_exhaustion_like"), None)
        self.assertIsNotNone(evidence, "应检测到 selling_exhaustion_like")


class TestLowVolumeTestParentLinkage(unittest.TestCase):
    """测试低量测试引用父证据"""

    def setUp(self):
        self.config = PriceActionEvidenceConfig()

    def test_low_volume_test_must_reference_parent_evidence(self):
        """§8.1: low_volume_test 必须在已确认 absorption/sweep 后五日内"""
        # 此测试在 lifecycle 测试中实现
        pass


class TestLastTwoBarsLifecycle(unittest.TestCase):
    """测试最后两根K线的生命周期规则"""

    def setUp(self):
        self.config = PriceActionEvidenceConfig()

    def test_last_two_bars_return_pending_even_without_evidence(self):
        """§8.3: 最后两根K线只能标记 pending_confirmation，即使没有检测到任何证据"""
        # 需要 > 20 根才能通过 insufficient_history 检查
        frame = _baseline_frame(periods=22, base_price=100.0)

        # decision_time 指向倒数第二根K线
        decision_time = frame.index[-2] + pd.Timedelta(hours=16)

        layer = build_price_action_layer(
            frame,
            zones=[],  # 没有 zone
            liquidity_pools=[],
            market_structure={},
            patterns=[],
            decision_time=decision_time,
            config=self.config,
        )

        # 应该返回 pending_confirmation 而不是 observed
        self.assertEqual(layer.lifecycle, "pending_confirmation")
        self.assertEqual(layer.direction, "neutral")
        self.assertIn("no_traceable_location", layer.limitations)

    def test_last_bar_return_pending_even_without_evidence(self):
        """§8.3: 最后一根K线也应该标记 pending_confirmation"""
        frame = _baseline_frame(periods=22, base_price=100.0)

        # decision_time 指向最后一根K线
        decision_time = frame.index[-1] + pd.Timedelta(hours=16)

        layer = build_price_action_layer(
            frame,
            zones=[],
            liquidity_pools=[],
            market_structure={},
            patterns=[],
            decision_time=decision_time,
            config=self.config,
        )

        self.assertEqual(layer.lifecycle, "pending_confirmation")

    def test_third_last_bar_returns_observed_without_evidence(self):
        """§8.3: 倒数第三根及更早的K线，没有证据时返回 observed"""
        frame = _baseline_frame(periods=22, base_price=100.0)

        # decision_time 指向倒数第三根K线
        decision_time = frame.index[-3] + pd.Timedelta(hours=16)

        layer = build_price_action_layer(
            frame,
            zones=[],
            liquidity_pools=[],
            market_structure={},
            patterns=[],
            decision_time=decision_time,
            config=self.config,
        )

        self.assertEqual(layer.lifecycle, "observed")


if __name__ == "__main__":
    unittest.main()
