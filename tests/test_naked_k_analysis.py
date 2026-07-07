import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo
import json

import pandas as pd

import naked_k_config
import naked_k_llm
import naked_k_analysis


class NakedKAnalysisTests(unittest.TestCase):
    def test_build_breakout_trigger_uses_signal_bar_extreme_with_buffer(self):
        bar = pd.Series({"High": 100.0, "Low": 95.0})

        trigger = naked_k_analysis.build_breakout_trigger(bar, side="bullish", buffer_ratio=0.01)
        invalidation = naked_k_analysis.build_invalidation_level(bar, side="bullish", buffer_ratio=0.01)

        self.assertEqual(trigger, 101.0)
        self.assertEqual(invalidation, 94.05)

    def test_volatility_buffer_expands_when_atr_is_large(self):
        quiet = pd.DataFrame(
            {
                "High": [100.5] * 20,
                "Low": [99.5] * 20,
                "Close": [100.0] * 20,
            }
        )
        volatile = pd.DataFrame(
            {
                "High": [110.0] * 20,
                "Low": [90.0] * 20,
                "Close": [100.0] * 20,
            }
        )

        quiet_buffer = naked_k_analysis.build_volatility_buffer_ratio(quiet)
        volatile_buffer = naked_k_analysis.build_volatility_buffer_ratio(volatile)

        self.assertEqual(quiet_buffer, 0.002)
        self.assertGreater(volatile_buffer, quiet_buffer)

    def test_price_action_context_flags_failed_breakout_rejection(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
                "High": [106.0, 107.0, 108.0, 109.0, 110.0, 112.0],
                "Low": [98.0, 99.0, 100.0, 101.0, 102.0, 103.0],
                "Close": [104.0, 105.0, 106.0, 107.0, 108.0, 106.0],
                "Volume": [1000, 980, 1020, 1010, 990, 1800],
            },
            index=pd.date_range("2026-06-22", periods=6, freq="D"),
        )

        context = naked_k_analysis.analyze_price_action_context(frame, lookback=5)

        self.assertEqual(context["bias"], "bearish")
        self.assertIn("上破5日高点失败", context["signals"])
        self.assertIn("上影线压力", context["candle"])
        self.assertGreater(context["close_position_pct"], 0)
        self.assertLess(context["close_position_pct"], 50)
        self.assertEqual(context["volume_pressure"], "派发压力")
        self.assertIn("放量上破失败", context["warnings"])

    def test_price_action_context_flags_trend_volume_and_volatility_confirmation(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 102.0, 104.0, 106.0, 108.0, 110.0],
                "High": [103.0, 105.0, 107.0, 109.0, 111.0, 118.0],
                "Low": [99.0, 101.0, 103.0, 105.0, 107.0, 109.0],
                "Close": [102.0, 104.0, 106.0, 108.0, 110.0, 117.0],
                "Volume": [1000, 1050, 980, 1020, 1010, 1900],
            },
            index=pd.date_range("2026-06-22", periods=6, freq="D"),
        )

        context = naked_k_analysis.analyze_price_action_context(frame, lookback=5)

        self.assertEqual(context["bias"], "bullish")
        self.assertEqual(context["trend"]["direction"], "up")
        self.assertEqual(context["trend"]["strength"], "strong")
        self.assertEqual(context["volatility_state"], "突破扩张")
        self.assertEqual(context["volume_pressure"], "量价确认")
        self.assertIn("趋势结构向上", context["signals"])
        self.assertIn("放量突破扩张", context["signals"])

    def test_price_action_context_classifies_bullish_pullback_depth(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 106.0, 112.0, 118.0, 118.0, 115.0],
                "High": [106.0, 113.0, 120.0, 121.0, 119.0, 116.0],
                "Low": [99.0, 105.0, 111.0, 116.0, 114.0, 112.0],
                "Close": [105.0, 112.0, 119.0, 118.0, 115.0, 113.0],
                "Volume": [1000, 1100, 1300, 1200, 900, 850],
            },
            index=pd.date_range("2026-06-22", periods=6, freq="D"),
        )

        context = naked_k_analysis.analyze_price_action_context(frame, lookback=5)

        self.assertEqual(context["pullback"]["direction"], "bullish")
        self.assertEqual(context["pullback"]["zone"], "健康回撤")
        self.assertAlmostEqual(context["pullback"]["depth_pct"], 36.4, places=1)

    def test_price_action_context_flags_failed_breakdown_reclaim(self):
        frame = pd.DataFrame(
            {
                "Open": [102.0, 101.0, 100.0, 99.0, 98.0, 97.0],
                "High": [108.0, 107.0, 106.0, 105.0, 104.0, 101.0],
                "Low": [96.0, 95.0, 95.5, 95.2, 95.1, 93.0],
                "Close": [100.0, 99.0, 98.0, 97.0, 96.0, 100.0],
                "Volume": [1000, 980, 1020, 1010, 990, 1800],
            },
            index=pd.date_range("2026-06-22", periods=6, freq="D"),
        )

        context = naked_k_analysis.analyze_price_action_context(frame, lookback=5)

        self.assertEqual(context["bias"], "bullish")
        self.assertIn("下破5日低点收回", context["signals"])
        self.assertIn("下影线承接", context["candle"])
        self.assertGreater(context["close_position_pct"], 75)

    def test_trade_plan_uses_price_action_breakout_when_no_named_pattern(self):
        daily = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0, 103.0, 104.0, 108.0],
                "High": [106.0, 107.0, 108.0, 109.0, 110.0, 113.0],
                "Low": [98.0, 99.0, 100.0, 101.0, 102.0, 107.0],
                "Close": [104.0, 105.0, 106.0, 107.0, 108.0, 112.0],
                "Volume": [1000, 980, 1020, 1010, 990, 1800],
            },
            index=pd.date_range("2026-06-22", periods=6, freq="D"),
        )
        weekly = daily.copy()

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, weekly, previous=None)

        self.assertEqual(report.action, "小仓试错")
        self.assertEqual(report.signal_state, "planned_long")
        self.assertEqual(report.price_action["bias"], "bullish")
        self.assertIn("收盘突破5日高点", report.price_action["signals"])
        self.assertIn("裸K结构", report.rationale)

    def test_trade_plan_reports_market_structure_and_regime(self):
        daily = pd.DataFrame(
            {
                "Open": [9.0, 10.5, 10.0, 12.5, 12.0, 14.5, 14.0, 15.5, 15.0, 18.0],
                "High": [10.0, 12.0, 11.0, 14.0, 13.0, 16.0, 15.0, 17.0, 16.0, 19.0],
                "Low": [8.0, 9.0, 8.5, 10.0, 9.5, 12.0, 11.0, 13.0, 12.5, 15.0],
                "Close": [9.0, 11.0, 10.0, 13.0, 12.0, 15.0, 14.0, 16.0, 15.0, 18.5],
                "Volume": [1000, 1200, 950, 1300, 980, 1400, 1000, 1500, 1050, 1800],
            },
            index=pd.date_range("2026-06-01", periods=10, freq="D"),
        )
        weekly = daily.copy()

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, weekly, previous=None)
        text = naked_k_analysis.format_report("2026-06-12 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertEqual(report.market_structure["sequence"], "HH/HL")
        self.assertEqual(report.market_structure["latest_event"]["kind"], "BOS")
        self.assertEqual(report.market_regime["state"], "trend")
        self.assertIn("- 市场结构：", text)
        self.assertIn("BOS", text)
        self.assertIn("- 市场状态：趋势市场", text)

    def test_trade_plan_reports_multitimeframe_context(self):
        daily = pd.DataFrame(
            {
                "Open": [18.0, 19.0, 20.0, 21.0, 22.0, 23.0],
                "High": [20.0, 21.0, 22.0, 23.0, 24.0, 26.0],
                "Low": [17.0, 18.0, 19.0, 20.0, 21.0, 22.0],
                "Close": [19.0, 20.0, 21.0, 22.0, 23.0, 25.0],
                "Volume": [1000, 1000, 1000, 1000, 1000, 1600],
            },
            index=pd.date_range("2026-06-01", periods=6, freq="D"),
        )
        weekly = daily.copy()
        monthly = daily.copy()

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, weekly, previous=None, monthly=monthly)
        text = naked_k_analysis.format_report("2026-06-12 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertEqual(report.timeframe_context["macro"]["role"], "长期方向")
        self.assertIn("大周期方向", report.timeframe_context["framework"])
        self.assertIn("- 多周期框架：", text)

    def test_trade_plan_reports_trader_brief(self):
        daily = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0, 103.0, 104.0, 108.0],
                "High": [106.0, 107.0, 108.0, 109.0, 110.0, 113.0],
                "Low": [98.0, 99.0, 100.0, 101.0, 102.0, 107.0],
                "Close": [104.0, 105.0, 106.0, 107.0, 108.0, 112.0],
                "Volume": [1000, 980, 1020, 1010, 990, 1800],
            },
            index=pd.date_range("2026-06-22", periods=6, freq="D"),
        )
        weekly = daily.copy()

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, weekly, previous=None)
        text = naked_k_analysis.format_report("2026-06-29 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertIn("交易计划", report.trader_brief)
        self.assertIn("胜率估计", report.trader_brief["交易计划"])
        self.assertIn("- 交易员简报：", text)

    def test_trade_plan_reports_structured_risk_plan(self):
        daily = pd.DataFrame(
            {
                "Open": [100.0, 140.0, 101.0, 100.0, 94.0],
                "High": [102.0, 140.0, 102.0, 101.0, 107.0],
                "Low": [98.0, 110.0, 95.0, 94.0, 93.0],
                "Close": [101.0, 120.0, 100.0, 95.0, 106.0],
                "Volume": [1000, 1000, 1000, 1000, 1200],
            },
            index=pd.to_datetime(["2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"]),
        )
        weekly = daily.copy()

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, weekly, previous=None)
        text = naked_k_analysis.format_report("2026-06-26 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertEqual(report.risk_plan["direction"], "long")
        self.assertEqual(report.risk_plan["status"], "active")
        self.assertIn("1R", report.risk_plan["targets_by_r"])
        self.assertEqual(report.position_size, report.risk_plan["position_size"])
        self.assertIn("- 风险计划：", text)
        self.assertIn("账户风险", text)

    def test_trade_plan_accepts_configured_risk_limits(self):
        config = naked_k_config.TradingConfig(
            risk=naked_k_config.RiskConfig(
                account_risk_pct=0.5,
                action_gross_caps={"买入": 8.0, "小仓试错": 4.0, "减仓": 5.0, "回避": 0.0, "观望": 0.0},
            )
        )
        daily = pd.DataFrame(
            {
                "Open": [100.0, 140.0, 101.0, 100.0, 94.0],
                "High": [102.0, 140.0, 102.0, 101.0, 107.0],
                "Low": [98.0, 110.0, 95.0, 94.0, 93.0],
                "Close": [101.0, 120.0, 100.0, 95.0, 106.0],
                "Volume": [1000, 1000, 1000, 1000, 1200],
            },
            index=pd.to_datetime(["2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"]),
        )

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, daily.copy(), previous=None, config=config)

        self.assertEqual(report.risk_plan["base_account_risk_pct"], 0.5)
        self.assertEqual(report.risk_plan["max_gross_pct"], config.risk.action_gross_caps[report.action])

    def test_trade_plan_reports_trade_setup_playbook(self):
        daily = pd.DataFrame(
            {
                "Open": [9.0, 10.5, 10.0, 12.5, 12.0, 14.5, 14.0, 15.5, 15.0, 18.0],
                "High": [10.0, 12.0, 11.0, 14.0, 13.0, 16.0, 15.0, 17.0, 16.0, 19.0],
                "Low": [8.0, 9.0, 8.5, 10.0, 9.5, 12.0, 11.0, 13.0, 12.5, 15.0],
                "Close": [9.0, 11.0, 10.0, 13.0, 12.0, 15.0, 14.0, 16.0, 15.0, 18.5],
                "Volume": [1000, 1200, 950, 1300, 980, 1400, 1000, 1500, 1050, 1800],
            },
            index=pd.date_range("2026-06-01", periods=10, freq="D"),
        )
        weekly = daily.copy()

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, weekly, previous=None)
        text = naked_k_analysis.format_report("2026-06-12 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertEqual(report.trade_setup["key"], "bullish_bos_continuation")
        self.assertEqual(report.trade_setup["direction"], "long")
        self.assertIn("多头BOS趋势延续", text)
        self.assertIn("- 交易剧本：", text)

    def test_trade_plan_reports_structured_price_zones(self):
        daily = pd.DataFrame(
            {
                "Open": [100, 105, 101, 106, 102, 107, 103, 106, 102, 105],
                "High": [104, 111.0, 105, 111.4, 106, 111.2, 107, 110.8, 106, 108],
                "Low": [98, 102, 99, 103, 100, 104, 101, 103, 99, 101],
                "Close": [103, 104, 104, 105, 105, 106, 106, 104, 103, 104],
                "Volume": [1000, 1700, 1000, 1800, 1000, 1750, 1000, 1600, 1000, 1000],
            },
            index=pd.date_range("2026-06-01", periods=10, freq="D"),
        )
        weekly = daily.copy()

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, weekly, previous=None)
        text = naked_k_analysis.format_report("2026-06-12 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertEqual(report.price_zones["nearest_resistance"]["kind"], "supply")
        self.assertEqual(report.price_zones["liquidity_pools"][0]["kind"], "buy_side_liquidity")
        self.assertEqual(report.resistance, report.price_zones["nearest_resistance"]["midpoint"])
        self.assertIn("- 关键价格区域：", text)
        self.assertIn("供给区", text)
        self.assertIn("上方买方流动性池", text)

    def test_position_guidance_is_capped_by_risk_budget(self):
        guidance = naked_k_analysis.build_position_guidance(
            action="小仓试错",
            entry_trigger=105.0,
            stop_loss=95.0,
        )

        self.assertIn("最高约10.5%", guidance)
        self.assertIn("按1%账户风险", guidance)

    def test_bullish_trade_plan_includes_target_and_reward_to_risk(self):
        daily = pd.DataFrame(
            {
                "Open": [100.0, 140.0, 101.0, 100.0, 94.0],
                "High": [102.0, 140.0, 102.0, 101.0, 107.0],
                "Low": [98.0, 110.0, 95.0, 94.0, 93.0],
                "Close": [101.0, 120.0, 100.0, 95.0, 106.0],
                "Volume": [1000, 1000, 1000, 1000, 1200],
            },
            index=pd.to_datetime(["2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"]),
        )
        weekly = daily.copy()

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, weekly, previous=None)

        self.assertEqual(report.action, "买入")
        self.assertGreater(report.target_price, report.entry_trigger)
        self.assertGreater(report.reward_to_risk, 0)
        self.assertIn("最高约", report.position_size)
        self.assertEqual(report.signal_state, "planned_long")

    def test_bullish_trade_plan_downgrades_when_first_target_has_poor_reward_to_risk(self):
        daily = pd.DataFrame(
            {
                "Open": [100.0, 110.0, 101.0, 100.0, 94.0],
                "High": [102.0, 120.0, 102.0, 101.0, 107.0],
                "Low": [98.0, 105.0, 95.0, 94.0, 93.0],
                "Close": [101.0, 108.0, 100.0, 95.0, 106.0],
                "Volume": [1000, 1000, 1000, 1000, 1200],
            },
            index=pd.to_datetime(["2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"]),
        )
        weekly = daily.copy()

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, weekly, previous=None)

        self.assertEqual(report.action, "观望")
        self.assertEqual(report.signal_state, "watching")
        self.assertIsNone(report.target_price)
        self.assertIsNone(report.reward_to_risk)
        self.assertEqual(report.position_size, "0%-10%")
        self.assertIn("盈亏比不足", report.rationale)

    def test_intraday_status_marks_confirmed_breakout(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 105.0],
                "High": [106.0, 108.0],
                "Low": [99.0, 104.0],
                "Close": [105.5, 107.2],
                "Volume": [1000, 1200],
            },
            index=pd.to_datetime(["2026-06-29 10:30:00", "2026-06-29 11:30:00"]),
        )

        status = naked_k_analysis.build_intraday_status(frame, "小仓试错", entry_trigger=106.0, stop_loss=95.0)

        self.assertEqual(status["status"], "盘中确认")
        self.assertEqual(status["latest_close"], 107.2)

    def test_intraday_status_marks_unconfirmed_breakout(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0],
                "High": [106.5],
                "Low": [99.0],
                "Close": [105.2],
                "Volume": [1000],
            },
            index=pd.to_datetime(["2026-06-29 10:30:00"]),
        )

        status = naked_k_analysis.build_intraday_status(frame, "小仓试错", entry_trigger=106.0, stop_loss=95.0)

        self.assertEqual(status["status"], "盘中突破未确认")

    def test_intraday_status_downgrades_zero_volume_latest_bar(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 106.0],
                "High": [105.0, 108.0],
                "Low": [99.0, 106.0],
                "Close": [104.0, 108.0],
                "Volume": [1000, 0],
            },
            index=pd.to_datetime(["2026-06-29 10:30:00", "2026-06-29 11:19:22"]),
        )

        status = naked_k_analysis.build_intraday_status(frame, "小仓试错", entry_trigger=106.0, stop_loss=95.0)

        self.assertEqual(status["status"], "盘中数据未确认")
        self.assertEqual(status["latest_volume"], 0)

    def test_intraday_status_marks_near_trigger_and_near_stop(self):
        near_trigger = pd.DataFrame(
            {
                "Open": [100.0],
                "High": [105.4],
                "Low": [99.0],
                "Close": [105.1],
                "Volume": [1000],
            },
            index=pd.to_datetime(["2026-06-29 10:30:00"]),
        )
        near_stop = pd.DataFrame(
            {
                "Open": [100.0],
                "High": [101.0],
                "Low": [95.4],
                "Close": [95.8],
                "Volume": [1000],
            },
            index=pd.to_datetime(["2026-06-29 10:30:00"]),
        )

        trigger_status = naked_k_analysis.build_intraday_status(
            near_trigger,
            "小仓试错",
            entry_trigger=106.0,
            stop_loss=95.0,
        )
        stop_status = naked_k_analysis.build_intraday_status(
            near_stop,
            "小仓试错",
            entry_trigger=106.0,
            stop_loss=95.0,
        )

        self.assertEqual(trigger_status["status"], "接近触发")
        self.assertEqual(stop_status["status"], "接近失效位")

    def test_format_report_does_not_append_r_to_missing_reward_to_risk(self):
        report = naked_k_analysis.InstrumentReport(
            name="测试",
            ticker="TEST",
            action="观望",
            entry_trigger=101.0,
            stop_loss=95.0,
            target_price=None,
            risk_per_share=6.0,
            reward_to_risk=None,
            signal_state="watching",
            resistance=100.0,
            support=95.0,
            position_size="0%-10%",
            rationale="无明确信号",
            daily_patterns=[],
            weekly_patterns=[],
            weekly_context="周线中性",
            data_sources={"daily": "fixture", "weekly": "fixture"},
            latest_k_dates={"daily": "2026-06-26", "weekly": "2026-06-26"},
            latest_closes={"daily": 99.0, "weekly": 99.0},
            review={"status": "观察中", "error_type": None, "note": "测试"},
            improvement="测试",
            intraday_status={"status": "盘中观察", "note": "测试"},
        )

        text = naked_k_analysis.format_report("2026-06-29 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertIn("- 目标盈亏比：暂无\n", text)
        self.assertNotIn("暂无R", text)

    def test_format_report_includes_intraday_status(self):
        report = naked_k_analysis.InstrumentReport(
            name="测试",
            ticker="TEST",
            action="小仓试错",
            entry_trigger=106.0,
            stop_loss=95.0,
            target_price=120.0,
            risk_per_share=11.0,
            reward_to_risk=1.27,
            signal_state="planned_long",
            resistance=120.0,
            support=95.0,
            position_size="最高约9.6%仓位",
            rationale="测试",
            daily_patterns=["🟢看涨吸收"],
            weekly_patterns=[],
            weekly_context="周线中性",
            data_sources={"daily": "fixture", "weekly": "fixture"},
            latest_k_dates={"daily": "2026-06-26", "weekly": "2026-06-26"},
            latest_closes={"daily": 105.0, "weekly": 105.0},
            review={"status": "观察中", "error_type": None, "note": "测试"},
            improvement="测试",
            intraday_status={
                "status": "盘中确认",
                "note": "最近有效1h收盘站上触发位",
                "latest_time": "2026-06-29 11:30:00",
                "latest_close": 107.2,
                "source": "fixture",
            },
        )

        text = naked_k_analysis.format_report("2026-06-29 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertIn("- 盘中状态：盘中确认", text)
        self.assertIn("最近有效1h收盘站上触发位", text)

    def test_format_report_includes_price_action_context(self):
        report = naked_k_analysis.InstrumentReport(
            name="测试",
            ticker="TEST",
            action="小仓试错",
            entry_trigger=113.2,
            stop_loss=106.8,
            target_price=None,
            risk_per_share=6.4,
            reward_to_risk=None,
            signal_state="planned_long",
            resistance=113.0,
            support=101.0,
            position_size="最高约15.0%仓位",
            rationale="测试",
            daily_patterns=[],
            weekly_patterns=[],
            weekly_context="周线中性",
            data_sources={"daily": "fixture", "weekly": "fixture"},
            latest_k_dates={"daily": "2026-06-26", "weekly": "2026-06-26"},
            latest_closes={"daily": 112.0, "weekly": 112.0},
            review={"status": "观察中", "error_type": None, "note": "测试"},
            improvement="测试",
            intraday_status={"status": "盘中观察", "note": "测试"},
            price_action={
                "bias": "bullish",
                "candle": ["强阳收近高点"],
                "signals": ["收盘突破5日高点"],
                "close_position_pct": 83.3,
                "trend": {"state": "上升结构", "strength": "strong"},
                "volatility_state": "突破扩张",
                "volume_pressure": "量价确认",
                "pullback": {"direction": "bullish", "zone": "健康回撤", "depth_pct": 36.4},
            },
        )

        text = naked_k_analysis.format_report("2026-06-29 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertIn("- 裸K解读：", text)
        self.assertIn("强阳收近高点", text)
        self.assertIn("收盘突破5日高点", text)
        self.assertIn("上升结构", text)
        self.assertIn("突破扩张", text)
        self.assertIn("健康回撤", text)
        self.assertIn("量价确认", text)

    def test_format_report_uses_none_for_best_trial_when_no_actionable_setups(self):
        report = naked_k_analysis.InstrumentReport(
            name="测试",
            ticker="TEST",
            action="观望",
            entry_trigger=101.0,
            stop_loss=95.0,
            target_price=None,
            risk_per_share=6.0,
            reward_to_risk=None,
            signal_state="watching",
            resistance=100.0,
            support=95.0,
            position_size="0%-10%",
            rationale="测试",
            daily_patterns=[],
            weekly_patterns=[],
            weekly_context="周线中性",
            data_sources={"daily": "fixture", "weekly": "fixture"},
            latest_k_dates={"daily": "2026-06-26", "weekly": "2026-06-26"},
            latest_closes={"daily": 99.0, "weekly": 99.0},
            review={"status": "观察中", "error_type": None, "note": "测试"},
            improvement="测试",
            intraday_status={"status": "盘中观察", "note": "测试"},
        )

        text = naked_k_analysis.format_report("2026-06-29 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertIn("- 最值得试错：暂无（无满足触发条件标的）", text)

    def test_format_report_includes_portfolio_exposure_summary(self):
        report = naked_k_analysis.InstrumentReport(
            name="测试",
            ticker="0700.HK",
            action="小仓试错",
            entry_trigger=101.0,
            stop_loss=95.0,
            target_price=112.0,
            risk_per_share=6.0,
            reward_to_risk=1.83,
            signal_state="planned_long",
            resistance=112.0,
            support=95.0,
            position_size="最高约10.0%仓位",
            rationale="测试",
            daily_patterns=[],
            weekly_patterns=[],
            weekly_context="周线中性",
            data_sources={"daily": "fixture", "weekly": "fixture"},
            latest_k_dates={"daily": "2026-06-26", "weekly": "2026-06-26"},
            latest_closes={"daily": 99.0, "weekly": 99.0},
            review={"status": "观察中", "error_type": None, "note": "测试"},
            improvement="测试",
            intraday_status={"status": "盘中观察", "note": "测试"},
            risk_plan={"direction": "long", "suggested_gross_pct": 10.0, "effective_account_risk_pct": 0.8},
        )

        text = naked_k_analysis.format_report("2026-06-29 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertIn("- 组合风险：", text)
        self.assertIn("总仓位", text)

    def test_run_analysis_writes_structured_audit_events(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0, 103.0, 104.0, 108.0],
                "High": [106.0, 107.0, 108.0, 109.0, 110.0, 113.0],
                "Low": [98.0, 99.0, 100.0, 101.0, 102.0, 107.0],
                "Close": [104.0, 105.0, 106.0, 107.0, 108.0, 112.0],
                "Volume": [1000, 980, 1020, 1010, 990, 1800],
            },
            index=pd.date_range("2026-06-22", periods=6, freq="D"),
        )
        frame.attrs["source"] = "fixture"

        def fake_load_ohlcv(_ticker, interval, period):
            loaded = frame.copy()
            loaded.attrs["source"] = f"fixture-{interval}"
            return loaded

        with TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            audit_path = Path(tmpdir) / "audit.jsonl"
            with patch.object(naked_k_analysis, "load_ohlcv", side_effect=fake_load_ohlcv):
                _, reports = naked_k_analysis.run_analysis(
                    [("测试", "TEST")],
                    journal_path,
                    audit_path=audit_path,
                )

            events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]

        event_types = [event["event_type"] for event in events]
        self.assertIn("run_started", event_types)
        self.assertIn("data_loaded", event_types)
        self.assertIn("plan_generated", event_types)
        self.assertIn("portfolio_exposure", event_types)
        self.assertIn("run_completed", event_types)
        self.assertEqual(reports[0].ticker, "TEST")
        data_events = [event for event in events if event["event_type"] == "data_loaded"]
        self.assertEqual({event["payload"]["interval"] for event in data_events}, {"1d", "1wk", "1mo", "1h"})
        plan_event = next(event for event in events if event["event_type"] == "plan_generated")
        self.assertEqual(plan_event["payload"]["ticker"], "TEST")
        self.assertEqual(plan_event["payload"]["action"], reports[0].action)

    def test_run_analysis_attaches_llm_commentary_when_enabled(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0, 103.0, 104.0, 108.0],
                "High": [106.0, 107.0, 108.0, 109.0, 110.0, 113.0],
                "Low": [98.0, 99.0, 100.0, 101.0, 102.0, 107.0],
                "Close": [104.0, 105.0, 106.0, 107.0, 108.0, 112.0],
                "Volume": [1000, 980, 1020, 1010, 990, 1800],
            },
            index=pd.date_range("2026-06-22", periods=6, freq="D"),
        )

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": '{"market_reading":"突破测试","journal_note":"等待回踩确认"}'
                            }
                        }
                    ]
                }

        def fake_load_ohlcv(_ticker, interval, period):
            loaded = frame.copy()
            loaded.attrs["source"] = f"fixture-{interval}"
            return loaded

        def fake_post(url, headers, json, timeout):
            return FakeResponse()

        llm_config = naked_k_llm.LLMConfig(
            enabled=True,
            base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
            api_key="test-secret-key",
            model="glm-5.2",
        )

        with TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            audit_path = Path(tmpdir) / "audit.jsonl"
            with patch.object(naked_k_analysis, "load_ohlcv", side_effect=fake_load_ohlcv):
                _, reports = naked_k_analysis.run_analysis(
                    [("测试", "TEST")],
                    journal_path,
                    audit_path=audit_path,
                    llm_config=llm_config,
                    llm_post=fake_post,
                )

            audit_text = audit_path.read_text(encoding="utf-8")

        commentary = reports[0].ai_assistant["llm_commentary"]
        self.assertEqual(commentary["status"], "ok")
        self.assertEqual(commentary["parsed"]["journal_note"], "等待回踩确认")
        self.assertIn("llm_commentary_generated", audit_text)
        self.assertNotIn("test-secret-key", audit_text)

    def test_review_previous_bullish_call_flags_false_breakout(self):
        previous = {
            "action": "小仓试错",
            "entry_trigger": 101.0,
            "stop_loss": 94.0,
        }
        current_bar = pd.Series({"Open": 100.5, "High": 102.0, "Low": 96.0, "Close": 99.0})

        review = naked_k_analysis.review_previous_call(previous, current_bar, current_close=99.0)

        self.assertEqual(review["status"], "未命中")
        self.assertEqual(review["error_type"], "假突破")

    def test_review_previous_bullish_call_marks_trigger_without_entry_when_not_confirmed(self):
        previous = {
            "action": "买入",
            "entry_trigger": 101.0,
            "stop_loss": 94.0,
        }
        current_bar = pd.Series({"Open": 100.0, "High": 100.8, "Low": 97.0, "Close": 98.5})

        review = naked_k_analysis.review_previous_call(previous, current_bar, current_close=98.5)

        self.assertEqual(review["status"], "未触发")
        self.assertEqual(review["error_type"], "缺少确认K")

    def test_drop_incomplete_hk_daily_bar_before_close(self):
        frame = pd.DataFrame(
            {
                "Open": [420.0, 423.0],
                "High": [430.0, 425.0],
                "Low": [418.0, 420.0],
                "Close": [424.0, 423.6],
                "Volume": [1000, 900],
            },
            index=pd.to_datetime(["2026-06-26", "2026-06-29"]),
        )

        trimmed = naked_k_analysis.trim_to_closed_bars(
            frame,
            market="hk",
            interval="1d",
            now=pd.Timestamp("2026-06-29 10:55:00", tz=ZoneInfo("Asia/Shanghai")),
        )

        self.assertEqual(trimmed.index[-1].strftime("%Y-%m-%d"), "2026-06-26")

    def test_drop_incomplete_hk_weekly_bar_during_current_week(self):
        frame = pd.DataFrame(
            {
                "Open": [410.0, 423.0],
                "High": [438.0, 425.0],
                "Low": [405.0, 420.0],
                "Close": [424.0, 423.6],
                "Volume": [5000, 900],
            },
            index=pd.to_datetime(["2026-06-26", "2026-06-29"]),
        )

        trimmed = naked_k_analysis.trim_to_closed_bars(
            frame,
            market="hk",
            interval="1wk",
            now=pd.Timestamp("2026-06-29 10:55:00", tz=ZoneInfo("Asia/Shanghai")),
        )

        self.assertEqual(trimmed.index[-1].strftime("%Y-%m-%d"), "2026-06-26")

    def test_drop_incomplete_monthly_bar_during_current_month(self):
        frame = pd.DataFrame(
            {
                "Open": [410.0, 423.0],
                "High": [438.0, 425.0],
                "Low": [405.0, 420.0],
                "Close": [424.0, 423.6],
                "Volume": [5000, 900],
            },
            index=pd.to_datetime(["2026-05-31", "2026-06-01"]),
        )

        trimmed = naked_k_analysis.trim_to_closed_bars(
            frame,
            market="hk",
            interval="1mo",
            now=pd.Timestamp("2026-06-29 10:55:00", tz=ZoneInfo("Asia/Shanghai")),
        )

        self.assertEqual(trimmed.index[-1].strftime("%Y-%m-%d"), "2026-05-31")

    def test_drop_zero_volume_latest_intraday_bar(self):
        frame = pd.DataFrame(
            {
                "Open": [420.0, 423.0],
                "High": [424.0, 425.0],
                "Low": [419.0, 422.0],
                "Close": [423.5, 424.0],
                "Volume": [1200, 0],
            },
            index=pd.to_datetime(["2026-06-30 14:00:00", "2026-06-30 15:00:00"]),
        )

        trimmed = naked_k_analysis.trim_to_closed_bars(
            frame,
            market="hk",
            interval="1h",
            now=pd.Timestamp("2026-06-30 15:20:00", tz=ZoneInfo("Asia/Shanghai")),
        )

        self.assertEqual(len(trimmed), 1)
        self.assertEqual(trimmed.index[-1].strftime("%Y-%m-%d %H:%M:%S"), "2026-06-30 14:00:00")

    def test_latest_journal_entry_skips_same_trading_day(self):
        rows = [
            {"ticker": "PDD", "latest_k_dates": {"daily": "2026-06-25"}, "action": "观望"},
            {"ticker": "PDD", "latest_k_dates": {"daily": "2026-06-26"}, "action": "买入"},
        ]

        latest = naked_k_analysis.latest_journal_entry(rows, "PDD", current_daily_date="2026-06-26")

        self.assertEqual(latest["latest_k_dates"]["daily"], "2026-06-25")

    def test_latest_journal_entry_ignores_future_trading_day(self):
        rows = [
            {"ticker": "9992.HK", "latest_k_dates": {"daily": "2026-06-26"}, "action": "观望"},
            {"ticker": "9992.HK", "latest_k_dates": {"daily": "2026-06-29"}, "action": "买入"},
        ]

        latest = naked_k_analysis.latest_journal_entry(rows, "9992.HK", current_daily_date="2026-06-26")

        self.assertIsNone(latest)

    def test_append_journal_replaces_same_ticker_same_daily_bar(self):
        with TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            base_report = naked_k_analysis.InstrumentReport(
                name="PDD",
                ticker="PDD",
                action="观望",
                entry_trigger=76.0,
                stop_loss=72.0,
                target_price=None,
                risk_per_share=4.0,
                reward_to_risk=None,
                signal_state="watching",
                resistance=80.0,
                support=72.0,
                position_size="0%-10%",
                rationale="首次记录",
                daily_patterns=[],
                weekly_patterns=[],
                weekly_context="周线中性",
                data_sources={"daily": "fixture", "weekly": "fixture"},
                latest_k_dates={"daily": "2026-06-30", "weekly": "2026-06-27"},
                latest_closes={"daily": 75.0, "weekly": 75.0},
                review={"status": "观察中", "error_type": None, "note": "测试"},
                improvement="测试",
                intraday_status={"status": "盘中观察", "note": "测试"},
            )
            updated_report = naked_k_analysis.InstrumentReport(
                **{
                    **base_report.__dict__,
                    "action": "小仓试错",
                    "rationale": "重跑后的最终记录",
                    "latest_closes": {"daily": 76.5, "weekly": 75.0},
                }
            )

            naked_k_analysis.append_journal(journal_path, "2026-06-30 20:00:00 CST", base_report)
            naked_k_analysis.append_journal(journal_path, "2026-06-30 20:05:00 CST", updated_report)

            rows = naked_k_analysis.load_journal(journal_path)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["action"], "小仓试错")
            self.assertEqual(rows[0]["latest_closes"]["daily"], 76.5)


if __name__ == "__main__":
    unittest.main()
