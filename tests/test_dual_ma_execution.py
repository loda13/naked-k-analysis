import unittest
from unittest.mock import patch

import naked_k_backtest as backtest
import naked_k_planner as planner
from naked_k_config import TradingConfig, DualMAConfig
from tests.test_dual_ma_system import candles, breakout_frame
from tests.test_naked_k_backtest import bars, candidate, scripted
from tests.test_naked_k_account import account


def target_signal():
    return {**candidate(maximum=110), 'setup': {'kind': 'cluster_breakout'},
            'exit_plan': {'method': 'fixed_r', 'target_r': 3, 'target_price': 130, 'min_reward_risk': 3}}


class DualMAExecutionTests(unittest.TestCase):
    def test_slippage_cannot_turn_a_gap_back_into_the_band_into_a_valid_setup(self):
        from naked_k_trend import analyze_trend
        signal = analyze_trend(breakout_frame())
        result = backtest.run_event_backtest('X', 'X', bars([100, 100, 99.95]), commission_bps=0,
            slippage_bps=20, min_history=2, signal_builder=scripted({2: signal}))
        self.assertEqual(result['audit']['entries'], 0)
        self.assertEqual(result['audit']['rejected_entries'][0]['reason'], 'open_back_inside_setup')

    def test_pullback_stop_uses_only_completed_bar_and_never_loosens(self):
        base = {**target_signal(), 'setup': {'kind': 'first_pullback_20'}}
        next_signal = {'direction': 'up', 'status': 'ready', 'entry_candidate': False,
                       'indicators': {'ma20': 95, 'ema20': 96},
                       'strategy': {'parameters': {'stop_buffer_pct': 0}}}
        frame = bars([100, 100, 100, 96], lows=[99, 99, 94, 94])
        result = backtest.run_event_backtest('X', 'X', frame, commission_bps=0, slippage_bps=0,
            min_history=2, signal_builder=scripted({2: base, 3: next_signal}))
        self.assertEqual(result['trades'][0]['exit_date'], '2025-01-04')
        self.assertEqual(result['trades'][0]['exit_price'], 95)

    def test_target_is_frozen_at_actual_fill_and_hit_later(self):
        frame = bars([100, 100, 102, 135], lows=[99, 99, 101, 130])
        frame.iloc[-1, frame.columns.get_loc('High')] = 140
        result = backtest.run_event_backtest('X', 'X', frame, commission_bps=10, slippage_bps=10,
            min_history=2, signal_builder=scripted({2: target_signal()}))
        trade = result['trades'][0]
        self.assertEqual(trade['exit_reason'], 'target')
        self.assertAlmostEqual(trade['target'], trade['entry_price'] + 3 * (trade['entry_price'] - 90))
        self.assertAlmostEqual(trade['exit_price'], trade['target'] * .999)

    def test_same_bar_stop_and_target_uses_stop_unless_target_hit_at_open(self):
        for opening, low, expected in [(100, 80, 'stop'), (140, 80, 'target_gap')]:
            with self.subTest(opening=opening):
                frame = bars([100, 100, 100, opening], lows=[99, 99, 99, low])
                frame.iloc[-1, frame.columns.get_loc('High')] = 145
                result = backtest.run_event_backtest('X', 'X', frame, commission_bps=0, slippage_bps=0,
                    min_history=2, signal_builder=scripted({2: target_signal()}))
                self.assertEqual(result['trades'][0]['exit_reason'], expected)

    def test_entry_bar_can_take_profit_and_cluster_stop_does_not_follow_other_setup(self):
        frame = bars([100, 100, 100], lows=[99, 99, 99])
        frame.iloc[-1, frame.columns.get_loc('High')] = 140
        result = backtest.run_event_backtest('X', 'X', frame, commission_bps=0, slippage_bps=0,
            min_history=2, signal_builder=scripted({2: target_signal()}))
        self.assertEqual(result['trades'][0]['exit_reason'], 'target')
        self.assertEqual(result['trades'][0]['holding_days'], 0)
        result = backtest.run_event_backtest('X', 'X', bars([100, 100, 100, 96], lows=[99, 99, 99, 94]),
            commission_bps=0, slippage_bps=0, min_history=2,
            signal_builder=scripted({2: target_signal(), 3: {**target_signal(), 'stop_loss': 98}}))
        self.assertEqual(result['trades'], [])
        self.assertEqual(result['open_position']['stop'], 90)
        self.assertEqual(result['open_position']['target'], 130)

    def test_live_plan_and_production_backtest_use_same_config_and_target(self):
        frame = candles([100.] * 125 + [102., 102., 102.])
        config = TradingConfig(strategy=DualMAConfig(take_profit_r=5))
        report = planner.build_trade_plan('X', 'X', frame.iloc[:-1], config=config)
        result = backtest.run_event_backtest('X', 'X', frame, commission_bps=0, slippage_bps=0, config=config)
        self.assertEqual(report.signal_state, 'planned_long')
        self.assertEqual(report.target_price, result['open_position']['target'])
        self.assertEqual(report.stop_loss, result['open_position']['stop'])
        self.assertEqual(report.reward_to_risk, 5)

    def test_holdings_keep_their_original_stop_family_and_unknown_stays_unknown(self):
        frame = breakout_frame()
        as_of = str(frame.index[-1].date())
        for kind, expected in [(None, 95), ('cluster_breakout', 95), ('first_pullback_20', 100.0998)]:
            holding = {'ticker': 'X', 'gross_pct': 10, 'account_risk_pct': 1, 'stop_loss': 95}
            if kind:
                holding['entry_setup'] = kind
            state = account(as_of=as_of, positions=[holding])
            report = planner.build_trade_plan('X', 'X', frame, account_state=state)
            self.assertAlmostEqual(report.management['suggested_stop'], expected)
            self.assertFalse(report.management['exit_next_open'])
            self.assertIsNone(report.entry_trigger)
            self.assertIsNone(report.risk_per_share)
            self.assertIsNone(report.reward_to_risk)
        report = planner.build_trade_plan('X', 'X', frame)
        self.assertEqual(report.account['status'], 'unknown')

    def test_snapshot_target_breach_requests_check_without_inventing_execution(self):
        frame = breakout_frame()
        state = account(as_of=str(frame.index[-1].date()), positions=[{
            'ticker': 'X', 'gross_pct': 10, 'account_risk_pct': 1, 'stop_loss': 95, 'target_price': 101}])
        report = planner.build_trade_plan('X', 'X', frame, account_state=state)
        self.assertTrue(report.management['target_reached'])
        self.assertEqual(report.signal_state, 'exit_pending')
        self.assertEqual(report.risk_plan['suggested_gross_pct'], 0)
