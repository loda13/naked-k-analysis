import unittest
from types import SimpleNamespace

import pandas as pd

import naked_k_backtest


class NakedKBacktestTests(unittest.TestCase):
    def test_walk_forward_windows_do_not_overlap_train_and_test(self):
        frame = pd.DataFrame(
            {"Close": range(20)},
            index=pd.date_range("2026-01-01", periods=20, freq="D"),
        )

        windows = naked_k_backtest.build_walk_forward_windows(frame, train_size=8, test_size=4, step=4)

        self.assertEqual(len(windows), 3)
        first = windows[0]
        self.assertLess(first["train_end"], first["test_start"])
        self.assertEqual(len(first["train"]), 8)
        self.assertEqual(len(first["test"]), 4)

    def test_calculates_professional_r_multiple_metrics(self):
        trades = [
            {"r_multiple": 1.5},
            {"r_multiple": -1.0},
            {"r_multiple": 2.0},
            {"r_multiple": -0.5},
        ]

        metrics = naked_k_backtest.calculate_performance_metrics(trades)

        self.assertEqual(metrics["trade_count"], 4)
        self.assertEqual(metrics["win_rate"], 50.0)
        self.assertEqual(metrics["profit_factor"], 2.33)
        self.assertEqual(metrics["average_r"], 0.5)
        self.assertEqual(metrics["maximum_drawdown_r"], 1.0)
        self.assertEqual(metrics["recovery_factor"], 2.0)

    def test_monte_carlo_simulation_is_seeded_and_reports_drawdown_distribution(self):
        trades = [{"r_multiple": value} for value in [1.0, -1.0, 2.0, -0.5, 0.5]]

        result = naked_k_backtest.run_monte_carlo_simulation(trades, iterations=50, seed=7)
        repeated = naked_k_backtest.run_monte_carlo_simulation(trades, iterations=50, seed=7)

        self.assertEqual(result, repeated)
        self.assertEqual(result["iterations"], 50)
        self.assertIn("ending_r_p05", result)
        self.assertIn("max_drawdown_r_p95", result)

    def test_evaluates_performance_by_market_cycle(self):
        trades = [
            {"r_multiple": 1.5, "regime": "trend"},
            {"r_multiple": 1.0, "regime": "trend"},
            {"r_multiple": -1.0, "regime": "range"},
            {"r_multiple": -0.5, "regime": "high_volatility"},
            {"r_multiple": 0.5, "regime": "low_volatility_compression"},
        ]

        validation = naked_k_backtest.evaluate_market_cycle_performance(
            trades,
            required_cycles=["trend", "range", "high_volatility", "low_volatility_compression", "bear"],
        )

        self.assertEqual(validation["cycles"]["trend"]["metrics"]["average_r"], 1.25)
        self.assertEqual(validation["cycles"]["range"]["metrics"]["trade_count"], 1)
        self.assertEqual(validation["coverage"]["missing_cycles"], ["bear"])
        self.assertEqual(validation["robustness"]["worst_cycle"], "range")
        self.assertTrue(validation["robustness"]["fragile"])

    def test_event_backtest_uses_signal_history_and_next_bar_execution(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0, 103.0, 104.0, 106.0],
                "High": [101.0, 102.0, 103.0, 104.0, 105.0, 111.0],
                "Low": [99.0, 100.0, 101.0, 102.0, 103.0, 105.0],
                "Close": [100.5, 101.5, 102.5, 103.5, 104.5, 110.0],
                "Volume": [1000, 1000, 1000, 1000, 1000, 1500],
            },
            index=pd.date_range("2026-01-01", periods=6, freq="D"),
        )
        signal_dates = []

        def plan_builder(name, ticker, daily, weekly, previous, intraday=None, monthly=None):
            signal_dates.append(daily.index[-1])
            return SimpleNamespace(
                ticker=ticker,
                action="买入",
                entry_trigger=105.0,
                stop_loss=103.0,
                target_price=109.0,
                risk_per_share=2.0,
                reward_to_risk=2.0,
                signal_state="planned_long",
                latest_k_dates={"daily": daily.index[-1].strftime("%Y-%m-%d")},
                trade_setup={"key": "fixture"},
                market_regime={"state": "fixture"},
            )

        result = naked_k_backtest.run_event_backtest(
            name="测试",
            ticker="TEST",
            daily=frame,
            weekly=frame,
            min_history=5,
            plan_builder=plan_builder,
        )

        self.assertEqual(signal_dates, [pd.Timestamp("2026-01-05")])
        self.assertEqual(len(result["trades"]), 1)
        self.assertIn("cycle_validation", result)
        trade = result["trades"][0]
        self.assertEqual(trade["signal_date"], "2026-01-05")
        self.assertEqual(trade["execution_date"], "2026-01-06")
        self.assertEqual(trade["exit_reason"], "target")
        self.assertEqual(trade["r_multiple"], 2.0)
        self.assertTrue(result["audit"]["no_lookahead"])

    def test_event_backtest_skips_untriggered_plans_without_counting_trade(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0, 103.0, 104.0, 104.2],
                "High": [101.0, 102.0, 103.0, 104.0, 104.8, 104.9],
                "Low": [99.0, 100.0, 101.0, 102.0, 103.0, 103.8],
                "Close": [100.5, 101.5, 102.5, 103.5, 104.5, 104.0],
                "Volume": [1000, 1000, 1000, 1000, 1000, 900],
            },
            index=pd.date_range("2026-01-01", periods=6, freq="D"),
        )

        def plan_builder(name, ticker, daily, weekly, previous, intraday=None, monthly=None):
            return SimpleNamespace(
                ticker=ticker,
                action="小仓试错",
                entry_trigger=106.0,
                stop_loss=103.0,
                target_price=112.0,
                risk_per_share=3.0,
                reward_to_risk=2.0,
                signal_state="planned_long",
                latest_k_dates={"daily": daily.index[-1].strftime("%Y-%m-%d")},
                trade_setup={"key": "fixture"},
                market_regime={"state": "fixture"},
            )

        result = naked_k_backtest.run_event_backtest(
            name="测试",
            ticker="TEST",
            daily=frame,
            weekly=frame,
            min_history=5,
            plan_builder=plan_builder,
        )

        self.assertEqual(result["trades"], [])
        self.assertEqual(result["skipped"][0]["reason"], "not_triggered")
        self.assertEqual(result["metrics"]["trade_count"], 0)

    def test_walk_forward_event_backtest_aggregates_test_window_trades(self):
        frame = pd.DataFrame(
            {
                "Open": [10.0] * 12,
                "High": [12.5] * 12,
                "Low": [10.5] * 12,
                "Close": [12.0] * 12,
                "Volume": [1000] * 12,
            },
            index=pd.date_range("2026-01-01", periods=12, freq="D"),
        )

        def plan_builder(name, ticker, daily, weekly, previous, intraday=None, monthly=None):
            return SimpleNamespace(
                ticker=ticker,
                action="买入",
                entry_trigger=11.0,
                stop_loss=10.0,
                target_price=12.0,
                risk_per_share=1.0,
                reward_to_risk=1.0,
                signal_state="planned_long",
                latest_k_dates={"daily": daily.index[-1].strftime("%Y-%m-%d")},
                trade_setup={"key": "fixture"},
                market_regime={"state": "fixture"},
            )

        result = naked_k_backtest.run_walk_forward_event_backtest(
            name="测试",
            ticker="TEST",
            daily=frame,
            train_size=5,
            test_size=3,
            step=3,
            plan_builder=plan_builder,
        )

        self.assertEqual(len(result["windows"]), 2)
        self.assertEqual(result["metrics"]["trade_count"], 6)
        self.assertIn("cycle_validation", result)
        for window in result["windows"]:
            test_start = pd.Timestamp(window["test_start"])
            test_end = pd.Timestamp(window["test_end"])
            for trade in window["trades"]:
                execution_date = pd.Timestamp(trade["execution_date"])
                self.assertGreaterEqual(execution_date, test_start)
                self.assertLessEqual(execution_date, test_end)


if __name__ == "__main__":
    unittest.main()
