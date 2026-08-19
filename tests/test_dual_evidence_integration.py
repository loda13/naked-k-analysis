"""
tests/test_dual_evidence_integration.py

端到端集成测试 - 验证 dual-evidence 架构在主流程中的集成
"""

import unittest
import pandas as pd

import naked_k_planner


class TestDualEvidenceIntegration(unittest.TestCase):
    """测试 dual-evidence 集成到主流程"""

    def test_build_trade_plan_includes_dual_evidence_fields(self):
        """验证 build_trade_plan 返回的报告包含 dual-evidence 字段"""
        # 创建测试数据
        dates = pd.date_range(start='2026-01-01', periods=30, freq='D')
        daily = pd.DataFrame({
            'Open': [100.0] * 30,
            'High': [102.0] * 30,
            'Low': [98.0] * 30,
            'Close': [101.0] * 30,
            'Volume': [1000000] * 30,
        }, index=dates)
        daily.attrs = {'source': 'test'}

        weekly = pd.DataFrame({
            'Open': [100.0] * 5,
            'High': [105.0] * 5,
            'Low': [95.0] * 5,
            'Close': [102.0] * 5,
            'Volume': [5000000] * 5,
        }, index=pd.date_range(start='2026-01-01', periods=5, freq='W'))
        weekly.attrs = {'source': 'test'}

        # 调用 build_trade_plan
        report = naked_k_planner.build_trade_plan(
            name="测试股票",
            ticker="0700.HK",
            daily=daily,
            weekly=weekly,
            previous=None,
            config=None,
        )

        # 验证报告包含 dual-evidence 字段
        self.assertIsNotNone(report)
        self.assertTrue(hasattr(report, 'dual_evidence_fusion'))
        self.assertTrue(hasattr(report, 'price_evidences'))
        self.assertTrue(hasattr(report, 'trade_flow_evidences'))

        # 验证字段类型
        self.assertIsInstance(report.price_evidences, list)
        self.assertIsInstance(report.trade_flow_evidences, list)

    def test_non_hk_stock_skips_trade_flow(self):
        """验证非港股跳过 trade_flow 采集"""
        dates = pd.date_range(start='2026-01-01', periods=30, freq='D')
        daily = pd.DataFrame({
            'Open': [100.0] * 30,
            'High': [102.0] * 30,
            'Low': [98.0] * 30,
            'Close': [101.0] * 30,
            'Volume': [1000000] * 30,
        }, index=dates)
        daily.attrs = {'source': 'test'}

        weekly = pd.DataFrame({
            'Open': [100.0] * 5,
            'High': [105.0] * 5,
            'Low': [95.0] * 5,
            'Close': [102.0] * 5,
            'Volume': [5000000] * 5,
        }, index=pd.date_range(start='2026-01-01', periods=5, freq='W'))
        weekly.attrs = {'source': 'test'}

        # 调用 build_trade_plan（美股）
        report = naked_k_planner.build_trade_plan(
            name="测试美股",
            ticker="AAPL",
            daily=daily,
            weekly=weekly,
            previous=None,
            config=None,
        )

        # 验证 trade_flow_evidences 为空
        self.assertEqual(len(report.trade_flow_evidences), 0)

    def test_report_has_basic_fields(self):
        """验证报告包含基本字段且不会崩溃"""
        dates = pd.date_range(start='2026-01-01', periods=30, freq='D')
        daily = pd.DataFrame({
            'Open': [100.0] * 30,
            'High': [102.0] * 30,
            'Low': [98.0] * 30,
            'Close': [101.0] * 30,
            'Volume': [1000000] * 30,
        }, index=dates)
        daily.attrs = {'source': 'test'}

        weekly = pd.DataFrame({
            'Open': [100.0] * 5,
            'High': [105.0] * 5,
            'Low': [95.0] * 5,
            'Close': [102.0] * 5,
            'Volume': [5000000] * 5,
        }, index=pd.date_range(start='2026-01-01', periods=5, freq='W'))
        weekly.attrs = {'source': 'test'}

        # 调用应该成功
        report = naked_k_planner.build_trade_plan(
            name="测试股票",
            ticker="0700.HK",
            daily=daily,
            weekly=weekly,
            previous=None,
            config=None,
        )

        # 验证报告包含基本字段
        self.assertIsNotNone(report)
        self.assertIsNotNone(report.action)
        self.assertIsNotNone(report.name)
        self.assertIsNotNone(report.ticker)


if __name__ == "__main__":
    unittest.main()
