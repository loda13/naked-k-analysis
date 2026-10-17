"""Behaviour contract for the source-based daily dual-MA adaptation."""
import json
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import naked_k_config as config
import naked_k_trend as trend


def candles(values):
    values = np.asarray(values, dtype=float)
    return pd.DataFrame({'Open': values, 'High': values + .3, 'Low': values - .3,
                         'Close': values, 'Volume': 1000.},
                        index=pd.bdate_range('2025-01-01', periods=len(values)))


def breakout_frame():
    return candles([100.] * 125 + [102., 102.])


class DualMATests(unittest.TestCase):
    def test_six_lines_and_full_history_are_required(self):
        for length in (55, 119, 120, 205):
            signal = trend.analyze_trend(candles(np.linspace(100, 150, length)))
            self.assertEqual(signal['rule_version'], 'bige-dual-ma-v1')
            self.assertEqual(signal['status'], 'ready' if length >= 120 else 'insufficient_history')
            for period in (20, 60, 120):
                self.assertIn(f'ma{period}', signal['indicators'])
                self.assertIn(f'ema{period}', signal['indicators'])
            if length < 120:
                self.assertFalse(signal['entry_candidate'])
                self.assertIsNone(signal['indicators']['ma120'])
                self.assertEqual(signal['direction'], 'unknown')

    def test_requires_compression_and_two_closed_confirmations(self):
        frame = breakout_frame()
        pending = trend.analyze_trend(frame.iloc[:-1])
        signal = trend.analyze_trend(frame)
        self.assertFalse(pending['entry_candidate'])
        self.assertEqual(pending['setup_state'], 'breakout_pending')
        self.assertTrue(signal['entry_candidate'])
        self.assertEqual(signal['setup']['kind'], 'cluster_breakout')
        self.assertAlmostEqual(signal['stop_loss'], 99.9)
        self.assertAlmostEqual(signal['target_price'], 108.3)
        self.assertEqual(signal['exit_plan']['method'], 'fixed_r')
        repeated = trend.analyze_trend(candles([100.] * 125 + [102., 102., 103.]))
        self.assertFalse(repeated['entry_candidate'])
        no_cluster = trend.analyze_trend(candles(np.linspace(100, 300, 240)))
        self.assertFalse(no_cluster['entry_candidate'])

    def test_reversal_below_current_six_lines_is_not_a_confirmed_long_candidate(self):
        signal = trend.analyze_trend(candles([100.] * 125 + [150., 101.]))
        self.assertEqual(signal['direction'], 'transition')
        self.assertFalse(signal['entry_candidate'])
        self.assertIn('price_not_above_six_lines', signal['reasons'])

    def test_bearish_setup_is_visible_but_never_opens_short(self):
        signal = trend.analyze_trend(candles([100.] * 125 + [98., 98.]))
        self.assertEqual(signal['direction'], 'down')
        self.assertEqual(signal['setup']['side'], 'short')
        self.assertFalse(signal['entry_candidate'])
        self.assertFalse(trend.evaluate_entry(signal, 98)['eligible'])

    def test_first_pullback_is_causal_and_only_the_first_touch_counts(self):
        base = candles([100.] * 125 + [102., 102.] + list(np.linspace(103, 110, 8)))
        data = candles(list(base.Close) + [float(base.Close.iloc[-1])])
        ind = trend.indicator_frame(data).iloc[-1]
        data.iloc[-1, data.columns.get_loc('Low')] = min(ind.ma20, ind.ema20) + .01
        first = trend.analyze_trend(data)
        self.assertTrue(first['entry_candidate'])
        self.assertEqual(first['setup']['kind'], 'first_pullback_20')
        self.assertAlmostEqual(first['stop_loss'], min(ind.ma20, ind.ema20) * .999)
        later = pd.concat([data, data.iloc[-1:].set_axis([data.index[-1] + pd.offsets.BDay()])])
        self.assertFalse(trend.analyze_trend(later)['entry_candidate'])
        failed = data.copy()
        failed.iloc[-1, failed.columns.get_loc('Close')] = min(ind.ma20, ind.ema20) - 1
        failed.iloc[-1, failed.columns.get_loc('Low')] = min(ind.ma20, ind.ema20) - 2
        self.assertFalse(trend.analyze_trend(failed)['entry_candidate'])

    def test_price_zones_volume_and_old_indicators_do_not_vote(self):
        frame = breakout_frame()
        original = trend.analyze_trend(frame)
        blocked_zone = {'zones': [], 'nearest_support': None,
                        'nearest_resistance': {'lower': 102.01, 'upper': 105, 'midpoint': 103},
                        'anchored_vwap': None}
        with patch.object(trend, 'detect_price_zones', return_value=blocked_zone):
            changed = trend.analyze_trend(frame.assign(Volume=0))
        for key in ('entry_candidate', 'stop_loss', 'target_price', 'setup', 'direction'):
            self.assertEqual(original[key], changed[key])
        indicators = trend.indicator_frame(frame)
        indicators[['ema50', 'ema200', 'atr', 'adx', 'channel_high', 'channel_low']] = 10000.
        with patch.object(trend, 'indicator_frame', return_value=indicators):
            changed = trend.analyze_trend(frame)
        for key in ('entry_candidate', 'stop_loss', 'target_price', 'setup', 'direction'):
            self.assertEqual(original[key], changed[key])

    def test_expired_cluster_does_not_create_a_late_entry(self):
        settings = config.DualMAConfig(setup_max_bars=1, confirmation_bars=3)
        signal = trend.analyze_trend(candles([100.] * 125 + [102., 102., 102.]), settings)
        self.assertFalse(signal['entry_candidate'])
        self.assertEqual(signal['setup_state'], 'expired')

    def test_sma_and_ema_60_120_have_explicit_seeds(self):
        frame = trend.indicator_frame(candles(np.arange(1, 131) + 100))
        for period in (60, 120):
            self.assertAlmostEqual(frame[f'ma{period}'].iloc[period-1], 100 + (period+1)/2)
            self.assertAlmostEqual(frame[f'ema{period}'].iloc[period-1], 100 + (period+1)/2)
            previous = frame[f'ema{period}'].iloc[period-1]
            self.assertAlmostEqual(frame[f'ema{period}'].iloc[period], previous + 2/(period+1) * (101+period-previous))

    def test_actual_open_recomputes_fixed_r_and_rejects_gap_into_band(self):
        signal = trend.analyze_trend(breakout_frame())
        check = trend.evaluate_entry(signal, 102.2)
        self.assertTrue(check['eligible'])
        self.assertAlmostEqual(check['target'], 102.2 + 3 * (102.2 - 99.9))
        self.assertAlmostEqual(check['reward_to_risk'], 3)
        self.assertFalse(trend.evaluate_entry(signal, 99.95)['eligible'])
        self.assertFalse(trend.evaluate_entry(signal, signal['max_entry'] + .01)['eligible'])

    def test_previous_cluster_has_no_fabricated_target_when_missing(self):
        settings = config.DualMAConfig(exit_method='previous_cluster')
        signal = trend.analyze_trend(breakout_frame(), settings)
        self.assertFalse(signal['entry_candidate'])
        self.assertIsNone(signal['target_price'])
        self.assertIn('target_unavailable', signal['reasons'])

    def test_previous_cluster_target_uses_only_older_cluster(self):
        frame = candles([120.] * 125 + list(np.linspace(118, 100, 30)) + [100.] * 220 + [102., 102.])
        signal = trend.analyze_trend(frame, config.DualMAConfig(exit_method='previous_cluster'))
        self.assertTrue(signal['entry_candidate'])
        self.assertAlmostEqual(signal['target_price'], 120)
        self.assertGreaterEqual(signal['reward_to_risk'], 3)

    def test_fibonacci_requires_explicit_past_anchors_and_actual_break(self):
        frame = candles([120.] * 125 + [90.] * 160 + [122., 122.])
        anchors = {'X': {'high_date': str(frame.index[124].date()), 'low_date': str(frame.index[125].date())}}
        settings = config.DualMAConfig(exit_method='fibonacci', fibonacci_anchors=anchors)
        signal = trend.analyze_trend(frame, settings, ticker='X')
        self.assertAlmostEqual(signal['target_price'], 89.7 + 1.618 * (120.3 - 89.7))
        self.assertFalse(signal['entry_candidate'])  # The very wide stop fails the required 3R.
        unknown = trend.analyze_trend(frame, settings, ticker='OTHER')
        self.assertIsNone(unknown['target_price'])
        prefix = trend.analyze_trend(frame.iloc[:125], settings, ticker='X')
        self.assertIsNone(prefix['target_price'])

    def test_appending_future_changes_neither_signal_nor_indicator_prefix(self):
        frame = breakout_frame()
        longer = pd.concat([frame, candles([500.]).set_axis([frame.index[-1] + pd.offsets.BDay()])])
        pd.testing.assert_frame_equal(trend.indicator_frame(frame), trend.indicator_frame(longer).iloc[:len(frame)], check_freq=False)
        self.assertEqual(trend.analyze_trend(frame), trend.analyze_trend(longer.iloc[:len(frame)]))
        json.dumps(trend.analyze_trend(frame), allow_nan=False)

    def test_strategy_config_is_validated_and_old_risk_config_still_loads(self):
        self.assertEqual(config.build_trading_config({'risk': {'account_risk_pct': .5}}).strategy.take_profit_r, 3)
        for values in ({'cluster_width_pct': float('nan')}, {'cluster_min_bars': True},
                       {'confirmation_bars': 0}, {'exit_method': 'magic'},
                       {'take_profit_r': 2}, {'fibonacci_ratio': 4.36},
                       {'fibonacci_anchors': {'X': {'high_date': '2099-01-02', 'low_date': '2000-01-01'}}}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                config.build_trading_config({'strategy': values})


if __name__ == '__main__':
    unittest.main()
