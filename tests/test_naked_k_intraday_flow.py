"""
tests/test_naked_k_intraday_flow.py

分钟线聚合资金流的单元测试。所有测试用构造的 DataFrame，不触网。
"""

import unittest
from datetime import datetime, timezone

import pandas as pd

from naked_k_intraday_flow import (
    IntradayFlowSnapshot,
    build_intraday_flow,
    MIN_BARS_FOR_VALID,
    SCHEMA_VERSION,
)


def make_bars(
    n: int = 120,
    start: str = "2026-08-19 09:30",
    tz: str = "Asia/Hong_Kong",
    volume: int = 1000,
    close_above_open: bool = True,
) -> pd.DataFrame:
    """构造 n 根 1 分钟 bar。默认全部收阳。"""
    idx = pd.date_range(start=start, periods=n, freq="1min", tz=tz)
    opens = [100.0] * n
    closes = [100.5 if close_above_open else 99.5] * n
    return pd.DataFrame(
        {
            "Open": opens,
            "High": [max(o, c) + 0.2 for o, c in zip(opens, closes)],
            "Low": [min(o, c) - 0.2 for o, c in zip(opens, closes)],
            "Close": closes,
            "Volume": [volume] * n,
        },
        index=idx,
    )


class BuildIntradayFlowUnavailableTests(unittest.TestCase):
    """取不到数或数据不合格时必须返回 UNAVAILABLE，而不是抛异常。"""

    def test_none_frame_returns_unavailable(self):
        snap = build_intraday_flow("0700.HK", "2026-08-19", None)
        self.assertEqual(snap.status, "UNAVAILABLE")
        self.assertEqual(snap.quality, "UNAVAILABLE")
        self.assertEqual(snap.bar_count, 0)
        self.assertIn("no_intraday_data", snap.limitations)

    def test_empty_frame_returns_unavailable(self):
        snap = build_intraday_flow("0700.HK", "2026-08-19", pd.DataFrame())
        self.assertEqual(snap.status, "UNAVAILABLE")
        self.assertIn("no_intraday_data", snap.limitations)

    def test_missing_columns_returns_unavailable(self):
        df = pd.DataFrame({"Close": [1.0, 2.0]})
        snap = build_intraday_flow("0700.HK", "2026-08-19", df)
        self.assertEqual(snap.status, "UNAVAILABLE")
        self.assertIn("missing_ohlcv_columns", snap.limitations)

    def test_all_zero_volume_returns_unavailable(self):
        df = make_bars(n=100, volume=0)
        snap = build_intraday_flow("0700.HK", "2026-08-19", df)
        self.assertEqual(snap.status, "UNAVAILABLE")
        self.assertIn("no_positive_volume_bars", snap.limitations)

    def test_unavailable_snapshot_is_serializable(self):
        snap = build_intraday_flow("0700.HK", "2026-08-19", None)
        d = snap.to_dict()
        self.assertEqual(d["status"], "UNAVAILABLE")
        self.assertIsInstance(d["retrieved_at"], str)
        self.assertIsInstance(d["limitations"], list)


class BuildIntradayFlowQualityTests(unittest.TestCase):
    """bar 数决定 status/quality，且质量绝不能标成 VALID。"""

    def test_sufficient_bars_marked_proxy(self):
        snap = build_intraday_flow("0700.HK", "2026-08-19", make_bars(n=MIN_BARS_FOR_VALID + 10))
        self.assertEqual(snap.status, "OK")
        self.assertEqual(snap.quality, "PROXY")
        self.assertNotIn("insufficient_bars", " ".join(snap.limitations))

    def test_insufficient_bars_marked_partial(self):
        n = MIN_BARS_FOR_VALID - 10
        snap = build_intraday_flow("0700.HK", "2026-08-19", make_bars(n=n))
        self.assertEqual(snap.status, "PARTIAL")
        self.assertEqual(snap.quality, "PARTIAL")
        self.assertIn(f"insufficient_bars:{n}", snap.limitations)

    def test_quality_never_claims_valid(self):
        """与真实 tape 证据不同级：PROXY/PARTIAL/UNAVAILABLE 三种，绝无 VALID。"""
        for n in (5, MIN_BARS_FOR_VALID - 1, MIN_BARS_FOR_VALID, 331):
            snap = build_intraday_flow("0700.HK", "2026-08-19", make_bars(n=n))
            self.assertNotEqual(snap.quality, "VALID", f"n={n} 不应标 VALID")

    def test_proxy_limitations_always_present(self):
        """代理口径和同源依赖必须始终写进 limitations。"""
        snap = build_intraday_flow("0700.HK", "2026-08-19", make_bars(n=200))
        self.assertIn("proxy_not_real_tape", snap.limitations)
        self.assertIn("same_dependency_group_as_daily_volume", snap.limitations)

    def test_schema_version_stamped(self):
        snap = build_intraday_flow("0700.HK", "2026-08-19", make_bars(n=200))
        self.assertEqual(snap.schema_version, SCHEMA_VERSION)


class VwapAndUptickTests(unittest.TestCase):
    """VWAP 与收阳占比的数值正确性。"""

    def test_vwap_is_volume_weighted_not_simple_mean(self):
        idx = pd.date_range("2026-08-19 09:30", periods=2, freq="1min", tz="Asia/Hong_Kong")
        df = pd.DataFrame(
            {
                "Open": [100.0, 100.0],
                "High": [101.0, 201.0],
                "Low": [99.0, 199.0],
                "Close": [100.0, 200.0],
                "Volume": [9000, 1000],
            },
            index=idx,
        )
        snap = build_intraday_flow("T", "2026-08-19", df)
        # 成交加权 = (100*9000 + 200*1000) / 10000 = 110；简单均值会是 150
        self.assertAlmostEqual(snap.vwap, 110.0, places=6)
        self.assertNotAlmostEqual(snap.vwap, 150.0, places=3)

    def test_close_vs_vwap_sign(self):
        idx = pd.date_range("2026-08-19 09:30", periods=2, freq="1min", tz="Asia/Hong_Kong")
        df = pd.DataFrame(
            {
                "Open": [100.0, 100.0],
                "High": [101.0, 121.0],
                "Low": [99.0, 119.0],
                "Close": [100.0, 120.0],
                "Volume": [1000, 1000],
            },
            index=idx,
        )
        snap = build_intraday_flow("T", "2026-08-19", df)
        self.assertEqual(snap.last_close, 120.0)
        self.assertGreater(snap.close_vs_vwap, 0.0)

    def test_all_up_bars_gives_full_uptick_ratio(self):
        snap = build_intraday_flow("T", "2026-08-19", make_bars(n=100, close_above_open=True))
        self.assertAlmostEqual(snap.uptick_volume_ratio, 1.0, places=6)

    def test_all_down_bars_gives_zero_uptick_ratio(self):
        snap = build_intraday_flow("T", "2026-08-19", make_bars(n=100, close_above_open=False))
        self.assertAlmostEqual(snap.uptick_volume_ratio, 0.0, places=6)

    def test_mixed_bars_uptick_ratio_is_volume_weighted(self):
        """收阳占比按成交量加权，不是按 bar 计数。"""
        idx = pd.date_range("2026-08-19 09:30", periods=4, freq="1min", tz="Asia/Hong_Kong")
        df = pd.DataFrame(
            {
                "Open": [100.0, 100.0, 100.0, 100.0],
                "High": [101.0, 101.0, 101.0, 101.0],
                "Low": [99.0, 99.0, 99.0, 99.0],
                # 一根收阳但量大，三根收阴但量小
                "Close": [100.5, 99.5, 99.5, 99.5],
                "Volume": [7000, 1000, 1000, 1000],
            },
            index=idx,
        )
        snap = build_intraday_flow("T", "2026-08-19", df)
        self.assertAlmostEqual(snap.uptick_volume_ratio, 0.7, places=6)

    def test_doji_bars_not_counted_as_uptick(self):
        """收=开的平盘 bar 不算收阳。"""
        idx = pd.date_range("2026-08-19 09:30", periods=2, freq="1min", tz="Asia/Hong_Kong")
        df = pd.DataFrame(
            {
                "Open": [100.0, 100.0],
                "High": [100.0, 100.0],
                "Low": [100.0, 100.0],
                "Close": [100.0, 100.0],
                "Volume": [1000, 1000],
            },
            index=idx,
        )
        snap = build_intraday_flow("T", "2026-08-19", df)
        self.assertAlmostEqual(snap.uptick_volume_ratio, 0.0, places=6)


class VolumeQuantileTests(unittest.TestCase):
    """成交量分位数与大量 bar 统计。"""

    def test_quartiles_are_monotonic(self):
        """volume_q3 存在且合理（删除 q1/q2/max 后只验证 q3）。"""
        idx = pd.date_range("2026-08-19 09:30", periods=100, freq="1min", tz="Asia/Hong_Kong")
        df = pd.DataFrame(
            {
                "Open": [100.0] * 100,
                "High": [101.0] * 100,
                "Low": [99.0] * 100,
                "Close": [100.5] * 100,
                "Volume": list(range(1, 101)),
            },
            index=idx,
        )
        snap = build_intraday_flow("T", "2026-08-19", df)
        # Q3 对应 75% 分位，volume 1-100 中 Q3≈75
        self.assertGreater(snap.volume_q3, 0.0)
        self.assertLess(snap.volume_q3, 100.0)

    def test_uniform_volume_gives_no_large_bars(self):
        """全部等量时没有 bar 严格大于 Q3。"""
        snap = build_intraday_flow("T", "2026-08-19", make_bars(n=100, volume=1000))
        self.assertAlmostEqual(snap.large_bar_volume_ratio, 0.0, places=6)
        self.assertAlmostEqual(snap.large_bar_uptick_ratio, 0.0, places=6)

    def test_large_bar_uptick_ratio_scoped_to_large_bars(self):
        """large_bar_uptick_ratio 的分母是大量 bar 的成交，不是全日成交。"""
        idx = pd.date_range("2026-08-19 09:30", periods=8, freq="1min", tz="Asia/Hong_Kong")
        # 6 根小量收阴，2 根大量（一阳一阴）
        df = pd.DataFrame(
            {
                "Open": [100.0] * 8,
                "High": [101.0] * 8,
                "Low": [99.0] * 8,
                "Close": [99.5] * 6 + [100.5, 99.5],
                "Volume": [100] * 6 + [5000, 5000],
            },
            index=idx,
        )
        snap = build_intraday_flow("T", "2026-08-19", df)
        # 两根大量 bar 各 5000，其中收阳的一根占一半
        self.assertAlmostEqual(snap.large_bar_uptick_ratio, 0.5, places=6)

    def test_total_volume_sums_all_bars(self):
        snap = build_intraday_flow("T", "2026-08-19", make_bars(n=50, volume=200))
        self.assertAlmostEqual(snap.total_volume, 50 * 200)


class SessionWindowTests(unittest.TestCase):
    """港股早盘/午盘时段划分。"""

    def test_morning_only_bars(self):
        df = make_bars(n=60, start="2026-08-19 10:00")
        snap = build_intraday_flow("T", "2026-08-19", df)
        self.assertAlmostEqual(snap.morning_volume_ratio, 1.0, places=6)
        self.assertAlmostEqual(snap.afternoon_volume_ratio, 0.0, places=6)

    def test_afternoon_only_bars(self):
        df = make_bars(n=60, start="2026-08-19 14:00")
        snap = build_intraday_flow("T", "2026-08-19", df)
        self.assertAlmostEqual(snap.afternoon_volume_ratio, 1.0, places=6)
        self.assertAlmostEqual(snap.morning_volume_ratio, 0.0, places=6)

    def test_ratios_sum_to_one_across_both_sessions(self):
        morning = make_bars(n=60, start="2026-08-19 10:00")
        afternoon = make_bars(n=60, start="2026-08-19 14:00")
        df = pd.concat([morning, afternoon])
        snap = build_intraday_flow("T", "2026-08-19", df)
        self.assertAlmostEqual(
            snap.morning_volume_ratio + snap.afternoon_volume_ratio, 1.0, places=6
        )
        self.assertAlmostEqual(snap.morning_volume_ratio, 0.5, places=6)

    def test_lunch_break_bars_excluded_from_both(self):
        """12:00-13:00 午休不属于任何时段，占比之和应小于 1。"""
        lunch = make_bars(n=30, start="2026-08-19 12:10")
        snap = build_intraday_flow("T", "2026-08-19", lunch)
        self.assertAlmostEqual(snap.morning_volume_ratio, 0.0, places=6)
        self.assertAlmostEqual(snap.afternoon_volume_ratio, 0.0, places=6)
        self.assertIn("session_window_unmatched", snap.limitations)

    def test_non_datetime_index_flags_limitation(self):
        df = make_bars(n=80).reset_index(drop=True)
        snap = build_intraday_flow("T", "2026-08-19", df)
        self.assertIn("index_not_datetime", snap.limitations)
        self.assertAlmostEqual(snap.morning_volume_ratio, 0.0, places=6)


class SnapshotContractTests(unittest.TestCase):
    """快照本身的契约：不可变、可序列化、字段齐全。"""

    def test_snapshot_is_frozen(self):
        snap = build_intraday_flow("T", "2026-08-19", make_bars(n=100))
        with self.assertRaises(Exception):
            snap.ticker = "OTHER"  # type: ignore[misc]

    def test_to_dict_is_json_serializable(self):
        import json

        snap = build_intraday_flow("0700.HK", "2026-08-19", make_bars(n=200))
        payload = json.dumps(snap.to_dict(), ensure_ascii=False)
        self.assertIn("0700.HK", payload)
        self.assertIn("proxy_not_real_tape", payload)

    def test_report_formatting_keys_present(self):
        """naked_k_analysis 报告段直接按这些 key 取值，缺一个就会 KeyError。"""
        snap = build_intraday_flow("0700.HK", "2026-08-19", make_bars(n=200))
        d = snap.to_dict()
        for key in (
            "status",
            "quality",
            "bar_count",
            "vwap",
            "last_close",
            "close_vs_vwap",
            "uptick_volume_ratio",
            "large_bar_volume_ratio",
            "large_bar_uptick_ratio",
            "morning_volume_ratio",
            "afternoon_volume_ratio",
            "limitations",
        ):
            self.assertIn(key, d, f"报告格式化需要的 key 缺失: {key}")

    def test_session_date_preserved(self):
        snap = build_intraday_flow("0700.HK", "2026-08-19", make_bars(n=100))
        self.assertEqual(snap.session_date, "2026-08-19")
        self.assertEqual(snap.ticker, "0700.HK")

    def test_retrieved_at_is_timezone_aware(self):
        snap = build_intraday_flow("T", "2026-08-19", make_bars(n=100))
        self.assertIsNotNone(snap.retrieved_at.tzinfo)


class NoNetworkTests(unittest.TestCase):
    """build_intraday_flow 必须是纯计算，不做任何网络 I/O。"""

    def test_build_does_not_touch_network(self):
        import naked_k_intraday_flow as mod

        called = {"n": 0}

        def boom(*args, **kwargs):
            called["n"] += 1
            raise AssertionError("build_intraday_flow 不应发起网络请求")

        original = getattr(mod, "fetch_intraday_bars")
        setattr(mod, "fetch_intraday_bars", boom)
        try:
            snap = mod.build_intraday_flow("T", "2026-08-19", make_bars(n=100))
            self.assertEqual(snap.status, "OK")
            self.assertEqual(called["n"], 0)
        finally:
            setattr(mod, "fetch_intraday_bars", original)


class PublicEntryPointTests(unittest.TestCase):
    """fetch_intraday_bars 和 collect_intraday_flow 的集成测试。"""

    def test_fetch_intraday_bars_returns_none_on_network_failure(self):
        """网络失败时 fetch 必须返回 None 不抛异常。"""
        import naked_k_intraday_flow as mod
        
        def mock_fail(*args, **kwargs):
            raise ConnectionError("simulated network failure")
        
        import yfinance
        original = yfinance.Ticker
        try:
            yfinance.Ticker = mock_fail
            result = mod.fetch_intraday_bars("0700.HK")
            self.assertIsNone(result)
        finally:
            yfinance.Ticker = original

    def test_collect_intraday_flow_returns_unavailable_on_fetch_failure(self):
        """取数失败时 collect 返回 UNAVAILABLE 快照，不抛异常。"""
        import naked_k_intraday_flow as mod
        
        original = mod.fetch_intraday_bars
        try:
            mod.fetch_intraday_bars = lambda ticker: None
            snap = mod.collect_intraday_flow("0700.HK")
            self.assertEqual(snap.status, "UNAVAILABLE")
            self.assertIn("intraday_fetch_failed", snap.limitations)
        finally:
            mod.fetch_intraday_bars = original

    def test_collect_intraday_flow_end_to_end_with_mock_bars(self):
        """端到端：mock fetch 返回构造的 bars，验证快照正确生成。"""
        import naked_k_intraday_flow as mod
        
        bars = make_bars(n=200, start="2026-08-19 10:00")
        original = mod.fetch_intraday_bars
        try:
            mod.fetch_intraday_bars = lambda ticker: bars
            snap = mod.collect_intraday_flow("TEST")
            self.assertEqual(snap.status, "OK")
            self.assertEqual(snap.quality, "PROXY")
            self.assertEqual(snap.bar_count, 200)
            self.assertEqual(snap.ticker, "TEST")
            self.assertEqual(snap.session_date, "2026-08-19")
        finally:
            mod.fetch_intraday_bars = original


if __name__ == "__main__":
    unittest.main()
