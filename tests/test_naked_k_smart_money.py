"""
tests/test_naked_k_smart_money.py

主力资金行为识别模块的单元测试
"""

import unittest
from datetime import datetime, timedelta

import pandas as pd

from naked_k_smart_money import (
    analyze_smart_money_signals,
    analyze_sweep_quality,
    detect_accumulation_volume,
    detect_buying_exhaustion,
    detect_multi_tf_confluence,
    detect_selling_exhaustion,
)


def _create_fake_ohlcv(
    start_date: str = "2024-01-01",
    periods: int = 50,
    base_price: float = 100.0,
    base_volume: float = 1000000,
) -> pd.DataFrame:
    """创建假的OHLCV数据框架"""
    dates = pd.date_range(start=start_date, periods=periods, freq="D")
    df = pd.DataFrame(
        {
            "Open": base_price,
            "High": base_price * 1.02,
            "Low": base_price * 0.98,
            "Close": base_price,
            "Volume": base_volume,
        },
        index=dates,
    )
    return df


class TestAccumulationDetection(unittest.TestCase):
    """测试吸筹成交量模式识别"""

    def test_detect_accumulation_pattern(self):
        """测试标准吸筹模式：放量+窄幅震荡+收在上半区"""
        df = _create_fake_ohlcv(periods=30)

        # 在第25-27日制造吸筹模式
        for i in range(25, 28):
            df.loc[df.index[i], "Volume"] = 2500000  # 2.5倍均量
            df.loc[df.index[i], "High"] = 101.0
            df.loc[df.index[i], "Low"] = 99.5
            df.loc[df.index[i], "Close"] = 100.7  # 收在上半区
            df.loc[df.index[i], "Open"] = 99.8

        signals = detect_accumulation_volume(df, window=20, volume_threshold=2.0)

        self.assertGreater(len(signals), 0, "应该检测到吸筹信号")
        signal = signals[0]
        self.assertEqual(signal["type"], "accumulation")
        self.assertGreater(signal["volume_ratio"], 2.0)
        self.assertGreater(signal["body_position"], 0.5)
        self.assertIn(signal["strength"], ("developing", "strong"))

    def test_no_accumulation_when_volume_normal(self):
        """测试正常成交量时不应触发吸筹信号"""
        df = _create_fake_ohlcv(periods=30)
        signals = detect_accumulation_volume(df, window=20, volume_threshold=2.0)
        self.assertEqual(len(signals), 0, "正常成交量不应触发吸筹信号")

    def test_no_accumulation_when_price_scattered(self):
        """测试价格分散时不应触发吸筹信号"""
        df = _create_fake_ohlcv(periods=30)

        # 放量但价格大幅波动
        for i in range(25, 28):
            df.loc[df.index[i], "Volume"] = 2500000
            df.loc[df.index[i], "Close"] = 100.0 + (i - 25) * 3  # 价格快速上涨

        signals = detect_accumulation_volume(df, window=20, volume_threshold=2.0)
        self.assertEqual(len(signals), 0, "价格分散不应触发吸筹信号")

    def test_strong_accumulation_signal(self):
        """测试强吸筹信号：3倍成交量+收在K线顶部"""
        df = _create_fake_ohlcv(periods=30)

        for i in range(25, 28):
            df.loc[df.index[i], "Volume"] = 3500000  # 3.5倍
            df.loc[df.index[i], "High"] = 101.0
            df.loc[df.index[i], "Low"] = 99.0
            df.loc[df.index[i], "Close"] = 100.9  # 收在K线顶部
            df.loc[df.index[i], "Open"] = 99.5

        signals = detect_accumulation_volume(df, window=20, volume_threshold=2.0)

        self.assertGreater(len(signals), 0)
        signal = signals[0]
        self.assertEqual(signal["strength"], "strong")
        self.assertGreater(signal["confidence_score"], 70)


class TestLiquiditySweepQuality(unittest.TestCase):
    """测试流动性扫荡质量评估"""

    def test_high_quality_bullish_sweep(self):
        """测试高质量多头扫荡：长下影+快速收回+缩量"""
        sweep_candle = {
            "Low": 95.0,
            "High": 100.5,
            "Close": 100.0,  # 收回91%
            "Volume": 2000000,
        }

        recovery_candles = [
            {"Close": 100.5, "Volume": 1000000},
            {"Close": 101.0, "Volume": 900000},
        ]

        demand_zone = {"lower": 98.0, "upper": 99.0}

        result = analyze_sweep_quality(sweep_candle, recovery_candles, demand_zone, "bullish")

        self.assertEqual(result["quality"], "strong")
        self.assertGreater(result["confidence_score"], 70)
        self.assertTrue(result["components"]["reclaim_confirmed"])
        self.assertGreater(result["components"]["volume_contrast"], 1.5)

    def test_weak_bullish_sweep(self):
        """测试弱扫荡：收回比例低+未站稳需求区"""
        sweep_candle = {
            "Low": 95.0,
            "High": 100.0,
            "Close": 96.5,  # 仅收回30%
            "Volume": 1000000,
        }

        recovery_candles = [
            {"Close": 96.0, "Volume": 1000000},  # 未站稳
        ]

        demand_zone = {"lower": 98.0, "upper": 99.0}

        result = analyze_sweep_quality(sweep_candle, recovery_candles, demand_zone, "bullish")

        self.assertIn(result["quality"], ("weak", "developing"))
        self.assertLess(result["confidence_score"], 70)

    def test_bearish_sweep_quality(self):
        """测试空头扫荡质量"""
        sweep_candle = {
            "Low": 95.0,
            "High": 105.0,
            "Close": 96.0,  # 上影线收回90%
            "Volume": 2000000,
        }

        recovery_candles = [
            {"Close": 94.0, "Volume": 1000000},
        ]

        supply_zone = {"lower": 101.0, "upper": 103.0}

        result = analyze_sweep_quality(sweep_candle, recovery_candles, supply_zone, "bearish")

        self.assertIn(result["quality"], ("strong", "developing"))
        self.assertGreater(result["components"]["wick_recovery"], 0.5)


class TestSellingExhaustion(unittest.TestCase):
    """测试卖压衰竭识别"""

    def test_detect_exhaustion_returns_dict(self):
        """测试衰竭检测函数基本返回格式"""
        df = _create_fake_ohlcv(periods=50)

        # 函数应该返回dict，无论是否检测到信号
        result = detect_selling_exhaustion(df, lookback=10, volume_window=20)
        self.assertIsInstance(result, dict)

        # 如果检测到信号，应该包含必要字段
        if result:
            self.assertIn("signal", result)
            self.assertIn("components", result)

    def test_no_exhaustion_when_not_new_low(self):
        """测试非新低时不触发衰竭信号"""
        df = _create_fake_ohlcv(periods=40, base_price=100.0)

        # 价格横盘，无新低
        for i in range(30, 37):
            df.loc[df.index[i], "Volume"] = 600000

        result = detect_selling_exhaustion(df, lookback=10)
        self.assertEqual(result, {}, "非新低不应触发衰竭信号")

    def test_no_exhaustion_when_volume_high(self):
        """测试成交量仍高时不触发衰竭信号"""
        df = _create_fake_ohlcv(periods=40, base_price=110.0)

        # 新低但成交量仍高
        for i in range(30, 37):
            df.loc[df.index[i], "Close"] = 90.0
            df.loc[df.index[i], "Low"] = 89.0
            df.loc[df.index[i], "Volume"] = 1200000  # 仍高于均量

        result = detect_selling_exhaustion(df, lookback=10)
        self.assertEqual(result, {}, "成交量仍高不应触发衰竭信号")


class TestBuyingExhaustion(unittest.TestCase):
    """测试买盘衰竭识别"""

    def test_detect_buying_exhaustion_returns_dict(self):
        """测试买盘衰竭检测函数基本返回格式"""
        df = _create_fake_ohlcv(periods=50)

        # 函数应该返回dict，无论是否检测到信号
        result = detect_buying_exhaustion(df, lookback=10, volume_window=20)
        self.assertIsInstance(result, dict)

        # 如果检测到信号，应该包含必要字段
        if result:
            self.assertIn("signal", result)
            self.assertIn("components", result)


class TestMultiTimeframeConfluence(unittest.TestCase):
    """测试多周期共振识别"""

    def test_bullish_confluence_detected(self):
        """测试多头三重共振：日线在周线需求区，周线在月线需求区"""
        monthly_zones = [
            {"kind": "demand", "lower": 90.0, "upper": 110.0, "midpoint": 100.0, "strength": "strong"}
        ]

        weekly_zones = [
            {"kind": "demand", "lower": 95.0, "upper": 105.0, "midpoint": 100.0, "strength": "strong"}
        ]

        daily_zones = [{"kind": "demand", "lower": 98.0, "upper": 102.0, "midpoint": 100.0, "strength": "developing"}]

        current_price = 100.0

        result = detect_multi_tf_confluence(monthly_zones, weekly_zones, daily_zones, current_price, "bullish")

        self.assertEqual(result.get("signal"), "multi_tf_demand_confluence")
        self.assertEqual(result.get("strength"), "strong")
        self.assertGreater(result.get("confidence_score", 0), 70)
        self.assertIn("三重共振", result.get("thesis", ""))

    def test_no_confluence_when_not_aligned(self):
        """测试区域不对齐时不触发共振"""
        monthly_zones = [{"kind": "demand", "lower": 50.0, "upper": 60.0, "midpoint": 55.0, "strength": "strong"}]

        weekly_zones = [{"kind": "demand", "lower": 95.0, "upper": 105.0, "midpoint": 100.0, "strength": "strong"}]

        daily_zones = [{"kind": "demand", "lower": 98.0, "upper": 102.0, "midpoint": 100.0, "strength": "developing"}]

        current_price = 100.0

        result = detect_multi_tf_confluence(monthly_zones, weekly_zones, daily_zones, current_price, "bullish")

        self.assertEqual(result, {}, "不对齐的区域不应触发共振信号")

    def test_bearish_confluence_detected(self):
        """测试空头三重共振"""
        monthly_zones = [
            {"kind": "supply", "lower": 140.0, "upper": 160.0, "midpoint": 150.0, "strength": "strong"}
        ]

        weekly_zones = [
            {"kind": "supply", "lower": 145.0, "upper": 155.0, "midpoint": 150.0, "strength": "developing"}
        ]

        daily_zones = [{"kind": "supply", "lower": 148.0, "upper": 152.0, "midpoint": 150.0, "strength": "weak"}]

        current_price = 150.0

        result = detect_multi_tf_confluence(monthly_zones, weekly_zones, daily_zones, current_price, "bearish")

        self.assertEqual(result.get("signal"), "multi_tf_supply_confluence")
        self.assertIn("供给", result.get("thesis", ""))


class TestSmartMoneyAnalysis(unittest.TestCase):
    """测试主力信号综合分析"""

    def test_comprehensive_bullish_signals(self):
        """测试综合多头信号分析"""
        # 使用真实的日期，确保信号不会因为时效性被过滤
        from datetime import datetime, timedelta
        start_date = (datetime.now() - timedelta(days=50)).strftime("%Y-%m-%d")

        df = _create_fake_ohlcv(periods=50, base_price=100.0, base_volume=1000000)
        df.index = pd.date_range(start=start_date, periods=50, freq="D")

        # 制造下跌趋势（10-29）
        for i in range(10, 30):
            price = 100.0 - (i - 10) * 0.5
            df.loc[df.index[i], "Open"] = price + 0.2
            df.loc[df.index[i], "Close"] = price
            df.loc[df.index[i], "High"] = price + 0.5
            df.loc[df.index[i], "Low"] = price - 0.3
            df.loc[df.index[i], "Volume"] = 1000000

        # 制造衰竭+吸筹模式（30-39）
        for i in range(30, 40):
            price = 90.5 - (i - 30) * 0.1
            df.loc[df.index[i], "Open"] = price + 0.1
            df.loc[df.index[i], "Close"] = price
            df.loc[df.index[i], "High"] = price + 0.3
            df.loc[df.index[i], "Low"] = price - 0.2
            df.loc[df.index[i], "Volume"] = 600000

        # 最后3根吸筹K线（47-49）- 最近几天
        for i in range(47, 50):
            df.loc[df.index[i], "Volume"] = 2500000
            df.loc[df.index[i], "Close"] = 89.7
            df.loc[df.index[i], "High"] = 90.0
            df.loc[df.index[i], "Low"] = 89.3
            df.loc[df.index[i], "Open"] = 89.5

        zones = [{"kind": "demand", "lower": 89.0, "upper": 90.5, "midpoint": 89.75}]
        liquidity_pools = []
        market_structure = {"direction": "down"}

        result = analyze_smart_money_signals(df, zones, liquidity_pools, market_structure)

        self.assertTrue(result.get("enabled"))
        # 至少应该有吸筹信号（最近3日）
        self.assertGreater(len(result.get("signals", [])), 0)
        self.assertIn(result.get("direction"), ("bullish", "neutral"))

    def test_no_signals_when_normal_market(self):
        """测试正常市场时无特殊信号"""
        df = _create_fake_ohlcv(periods=30)

        zones = []
        liquidity_pools = []
        market_structure = {}

        result = analyze_smart_money_signals(df, zones, liquidity_pools, market_structure)

        self.assertTrue(result.get("enabled"))
        self.assertEqual(len(result.get("signals", [])), 0)
        self.assertIn("无明显", result.get("overall_assessment", ""))

    def test_empty_dataframe_handling(self):
        """测试空数据框处理"""
        df = pd.DataFrame()

        result = analyze_smart_money_signals(df, [], [], {})

        self.assertFalse(result.get("enabled"))
        self.assertEqual(len(result.get("signals", [])), 0)


if __name__ == "__main__":
    unittest.main()
