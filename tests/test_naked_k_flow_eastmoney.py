"""
tests/test_naked_k_flow_eastmoney.py

东方财富逐笔成交 provider 测试
"""

import unittest
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import shutil

from naked_k_flow_eastmoney import (
    fetch_trade_flow,
    save_snapshot,
    _hk_ticker_to_eastmoney_code,
    _parse_eastmoney_response,
)


class TestTickerMapping(unittest.TestCase):
    """测试港股代码映射"""

    def test_hk_ticker_to_eastmoney_code(self):
        """标准港股代码映射"""
        self.assertEqual(_hk_ticker_to_eastmoney_code("0700.HK"), "116.00700")
        self.assertEqual(_hk_ticker_to_eastmoney_code("1810.HK"), "116.01810")
        self.assertEqual(_hk_ticker_to_eastmoney_code("9992.HK"), "116.09992")

    def test_non_hk_ticker_raises(self):
        """非港股代码应报错"""
        with self.assertRaises(ValueError):
            _hk_ticker_to_eastmoney_code("AAPL")


class TestResponseParsing(unittest.TestCase):
    """测试响应解析"""

    def test_parse_empty_response(self):
        """空响应返回 UNAVAILABLE 状态"""
        response = {"data": {"details": ""}}
        snapshot = _parse_eastmoney_response(
            response,
            "0700.HK",
            "2026-08-19",
            datetime.now(timezone.utc),
        )
        self.assertEqual(snapshot.status, "UNAVAILABLE")
        self.assertEqual(snapshot.trade_count, 0)
        self.assertIn("no_data", snapshot.limitations)

    def test_parse_valid_response(self):
        """有效响应解析成功"""
        response = {
            "data": {
                "code": "116.00700",
                "market": 116,
                "details": "时间,价格,数量,方向\n09:30:03,372.20,10000,1\n09:30:05,372.40,5000,1\n09:30:08,372.00,8000,2"
            }
        }
        snapshot = _parse_eastmoney_response(
            response,
            "0700.HK",
            "2026-08-19",
            datetime.now(timezone.utc),
        )

        self.assertEqual(snapshot.status, "OK")
        self.assertEqual(snapshot.trade_count, 3)
        self.assertEqual(snapshot.ticker, "0700.HK")
        self.assertEqual(snapshot.market, "hk")
        self.assertEqual(snapshot.currency, "HKD")

        # 检查第一笔
        first_trade = snapshot.trades[0]
        self.assertEqual(first_trade.price, 372.20)
        self.assertEqual(first_trade.volume, 10000)
        self.assertAlmostEqual(first_trade.notional, 3722000.0, places=2)
        self.assertEqual(first_trade.tick_direction, "unknown")  # 第一笔无参考

        # 检查第二笔（价格上涨）
        second_trade = snapshot.trades[1]
        self.assertEqual(second_trade.tick_direction, "uptick")

        # 检查第三笔（价格下跌）
        third_trade = snapshot.trades[2]
        self.assertEqual(third_trade.tick_direction, "downtick")

    def test_tick_direction_zero_tick_inherits(self):
        """同价tick继承上一次非零方向"""
        response = {
            "data": {
                "details": "时间,价格,数量,方向\n09:30:03,100.00,1000,1\n09:30:05,101.00,1000,1\n09:30:08,101.00,1000,1"
            }
        }
        snapshot = _parse_eastmoney_response(
            response,
            "0700.HK",
            "2026-08-19",
            datetime.now(timezone.utc),
        )

        trades = snapshot.trades
        self.assertEqual(trades[0].tick_direction, "unknown")  # 第一笔
        self.assertEqual(trades[1].tick_direction, "uptick")   # 价格上涨
        self.assertEqual(trades[2].tick_direction, "uptick")   # 同价，继承 uptick

    def test_parse_list_format_details(self):
        """解析列表格式的 details 字段"""
        response = {
            "data": {
                "code": "116.00700",
                "market": 116,
                "details": [
                    "09:30:03,372.20,10000,1",
                    "09:30:05,372.40,5000,1",
                    "09:30:08,372.00,8000,2"
                ]
            }
        }
        snapshot = _parse_eastmoney_response(
            response,
            "0700.HK",
            "2026-08-19",
            datetime.now(timezone.utc),
        )

        self.assertEqual(snapshot.status, "OK")
        self.assertEqual(snapshot.trade_count, 3)
        self.assertEqual(snapshot.trades[0].price, 372.20)
        self.assertEqual(snapshot.trades[1].tick_direction, "uptick")
        self.assertEqual(snapshot.trades[2].tick_direction, "downtick")


class TestSnapshotPersistence(unittest.TestCase):
    """测试快照持久化"""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_snapshot_creates_file(self):
        """保存快照创建文件"""
        response = {
            "data": {
                "details": "时间,价格,数量,方向\n09:30:03,372.20,10000,1"
            }
        }
        snapshot = _parse_eastmoney_response(
            response,
            "0700.HK",
            "2026-08-19",
            datetime.now(timezone.utc),
        )

        filepath = save_snapshot(snapshot, self.temp_dir)
        self.assertTrue(filepath.exists())
        self.assertTrue(filepath.name.endswith(".raw.json.gz"))

        # 验证目录结构
        self.assertEqual(filepath.parent.name, "0700.HK")
        self.assertEqual(filepath.parent.parent.name, "2026-08-19")


class TestFetchTradeFlow(unittest.TestCase):
    """测试实时数据获取（集成测试，需要网络）"""

    @unittest.skip("需要网络连接，手动测试时启用")
    def test_fetch_0700_hk(self):
        """获取 0700.HK 实时数据"""
        snapshot = fetch_trade_flow("0700.HK", "2026-08-19")

        self.assertEqual(snapshot.ticker, "0700.HK")
        self.assertEqual(snapshot.provider, "eastmoney")
        # 状态可能是 OK 或 UNAVAILABLE（取决于交易时段）
        self.assertIn(snapshot.status, ["OK", "UNAVAILABLE"])

        if snapshot.status == "OK":
            self.assertGreater(snapshot.trade_count, 0)
            self.assertIsNotNone(snapshot.total_volume)
            self.assertIsNotNone(snapshot.total_notional)

    def test_fetch_invalid_ticker(self):
        """非港股代码返回 INVALID 状态"""
        snapshot = fetch_trade_flow("AAPL", "2026-08-19")
        self.assertEqual(snapshot.status, "INVALID")
        self.assertTrue(any("invalid_ticker" in lim for lim in snapshot.limitations))


if __name__ == "__main__":
    unittest.main()
