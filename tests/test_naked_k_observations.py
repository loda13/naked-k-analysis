import json
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

import naked_k_observations as o
import naked_k_analysis as a
from naked_k_trend import analyze_trend


def prices(values, volume=100.):
    close = np.asarray(values, dtype=float)
    return pd.DataFrame({'Open': close - .1, 'High': close + .5, 'Low': close - .5,
                         'Close': close, 'Volume': volume},
                        index=pd.bdate_range('2025-01-01', periods=len(close)))


class ObservationTests(unittest.TestCase):
    def test_formula_values_and_warmups(self):
        data = prices(np.arange(100., 160.))
        result = o.observation_frame(data)
        self.assertTrue(pd.isna(result.rsi14.iloc[13]))
        self.assertEqual(result.rsi14.iloc[14], 100.)
        self.assertAlmostEqual(result.macd.iloc[-1], 7.)
        self.assertAlmostEqual(result.macd_signal.iloc[-1], 7.)
        self.assertAlmostEqual(result.macd_hist.iloc[-1], 0.)
        self.assertAlmostEqual(result.sma20.iloc[-1], 149.5)
        self.assertAlmostEqual(result.boll_upper.iloc[-1], 149.5 + 2 * np.std(np.arange(140., 160.)))
        self.assertAlmostEqual(result.roc12.iloc[-1], (159 / 147 - 1) * 100)
        self.assertAlmostEqual(result.cci20.iloc[-1], 9.5 / (.015 * 5))
        self.assertAlmostEqual(result.williams_r14.iloc[-1], -100 * .5 / 14)
        self.assertEqual(result.obv.iloc[-1], 5900.)
        self.assertEqual(result.mfi14.iloc[-1], 100.)
        self.assertAlmostEqual(result.cmf20.iloc[-1], 0.)
        self.assertAlmostEqual(result.vwma20.iloc[-1], 149.5)
        self.assertAlmostEqual(result.kdj_k.iloc[8], 50 * 2 / 3 + (8.5 / 9 * 100) / 3)
        self.assertTrue(pd.isna(result.sma250.iloc[-1]))
        self.assertEqual(result.aroon_up.iloc[-1], 100.)
        self.assertEqual(result.aroon_down.iloc[-1], 0.)

    def test_sar_seed_reversal_and_trix_warmup(self):
        result = o.observation_frame(prices([10., 11., 12., 13., 14., 8.]))
        self.assertAlmostEqual(result.sar.iloc[2], 9.5)
        self.assertAlmostEqual(result.sar.iloc[3], 9.62)
        self.assertEqual(result.sar.iloc[-1], 14.5)
        result = o.observation_frame(prices(np.arange(100., 180.)))
        self.assertTrue(pd.isna(result.trix.iloc[42]))
        self.assertTrue(pd.notna(result.trix.iloc[43]))

    def test_opposite_momentum_periods_are_mixed_and_ma_position_is_explicit(self):
        for roc_base, momentum_base in [(90., 110.), (110., 90.)]:
            with self.subTest(roc_base=roc_base):
                values = np.full(60, 100.)
                values[-13], values[-11] = roc_base, momentum_base
                result = o.analyze_observations(prices(values))
                roc = next(x for x in result['indicators'] if x['id'] == 'roc')
                self.assertEqual(roc['side'], 'mixed')
                self.assertNotIn(roc['name'], result['bullish_evidence'] + result['bearish_evidence'])
        for values, expected in [(np.arange(160., 100., -1), '收盘在线下'),
                                 (np.arange(100., 160.), '收盘在线上'),
                                 ([100.] * 60, '收盘与均线持平')]:
            result = o.analyze_observations(prices(values))
            ma = next(x for x in result['indicators'] if x['id'] == 'sma5')
            self.assertEqual(ma['interpretation'], expected)

    def test_recent_rsi_divergence_and_triangle_are_text_candidates(self):
        values = list(np.linspace(100, 130, 40)) + [135, 140, 135, 130, 133, 136, 140, 141, 139, 138]
        result = o.analyze_observations(prices(values))
        self.assertTrue(any(x['id'] == 'rsi_bearish_divergence' and x['status'] == 'pending' for x in result['patterns']))
        # Three confirmed highs fall while three confirmed lows rise.
        values = list(np.linspace(95, 100, 25)) + [110, 108, 105, 90, 94, 99, 108, 105, 99, 92, 95, 99, 106, 104, 100, 94, 97, 99]
        result = o.analyze_observations(prices(values))
        self.assertTrue(any(x['id'] == 'triangle' and x['status'] == 'pending' for x in result['patterns']))

    def test_flat_missing_volume_and_short_history_are_explicit(self):
        flat = prices([100.] * 80)
        flat[['Open', 'High', 'Low']] = 100.
        result = o.observation_frame(flat)
        self.assertEqual(result.rsi14.iloc[-1], 50.)
        self.assertTrue(pd.isna(result.boll_percent_b.iloc[-1]))
        self.assertTrue(pd.isna(result.kdj_k.iloc[-1]))
        flat['Volume'] = np.nan
        result = o.observation_frame(flat)
        for key in ['obv', 'adl', 'cmf20', 'mfi14', 'vwma20', 'relative_volume']:
            self.assertTrue(pd.isna(result[key].iloc[-1]), key)
        for size in [1, 8, 14, 20, 54]:
            report = o.analyze_observations(flat.iloc[:size])
            json.dumps(report, allow_nan=False)
            self.assertIn('unavailable', {x['status'] for x in report['indicators']})

    def test_calculations_are_prefix_causal_and_do_not_mutate_inputs(self):
        data = prices(100 + np.arange(90) * .1 + np.sin(np.arange(90)))
        original = data.copy(deep=True)
        full, prefix = o.observation_frame(data), o.observation_frame(data.iloc[:60])
        pd.testing.assert_frame_equal(prefix, full.iloc[:60])
        pd.testing.assert_frame_equal(data, original)
        result = o.analyze_observations(data)
        json.dumps(result, allow_nan=False)
        self.assertNotIn('score', result)
        self.assertNotIn('action', result)

    def test_double_bottom_waits_for_pivot_and_neckline_then_can_fail(self):
        values = list(np.linspace(130, 106, 25)) + [104, 102, 100, 103, 107, 112, 109, 105, 102, 100.2, 103, 106, 109]
        data = prices(values)
        patterns = o.analyze_observations(data)['patterns']
        bottom = next(x for x in patterns if x['id'] == 'double_bottom')
        self.assertEqual(bottom['status'], 'pending')
        self.assertGreaterEqual(bottom['detected_at'], data.index[36].date().isoformat())
        earlier = o.analyze_observations(data.iloc[:36])['patterns']
        self.assertFalse(any(x['id'] == 'double_bottom' for x in earlier))
        confirmed = o.analyze_observations(prices(values + [114]))['patterns']
        bottom = next(x for x in confirmed if x['id'] == 'double_bottom')
        self.assertEqual(bottom['status'], 'confirmed')
        self.assertEqual(bottom['confirmed_at'], prices(values + [114]).index[-1].date().isoformat())
        failed = o.analyze_observations(prices(values + [114, 98]))['patterns']
        self.assertEqual(next(x for x in failed if x['id'] == 'double_bottom')['status'], 'failed')

    def test_head_shoulders_and_false_breakout_have_observable_confirmation(self):
        values = list(np.linspace(85, 105, 25)) + [108, 112, 109, 105, 102, 107, 114, 118, 114, 107, 103, 106, 110, 112, 109, 106, 100]
        result = o.analyze_observations(prices(values))
        pattern = next(x for x in result['patterns'] if x['id'] == 'head_shoulders_top')
        self.assertEqual(pattern['status'], 'confirmed')
        self.assertEqual(pattern['side'], 'bearish')
        flat = [100.] * 30
        before = o.analyze_observations(prices(flat + [103]))
        self.assertFalse(any(x['id'] == 'false_breakout_up' for x in before['patterns']))
        after = o.analyze_observations(prices(flat + [103, 100]))
        failure = next(x for x in after['patterns'] if x['id'] == 'false_breakout_up')
        self.assertEqual(failure['confirmed_at'], prices(flat + [103, 100]).index[-1].date().isoformat())

    def test_text_report_persists_observations_without_changing_v2_plan(self):
        data = prices(np.linspace(100, 140, 260))
        expected = analyze_trend(data)
        report = a.build_trade_plan('测试', 'TEST', data)
        self.assertEqual(report.trend, expected)
        self.assertEqual(report.observations['version'], o.OBSERVATION_VERSION)
        text = a.format_report('2026-09-29', [report], Path('unused'))
        for name in ['MACD', 'RSI', 'KDJ', '布林', 'OBV', 'MFI', 'CMF', '偏多', '偏空', '待确认']:
            self.assertIn(name, text)
        self.assertNotIn('![', text)
        self.assertNotIn('<svg', text)
        self.assertEqual(a.serialize_report(report)['observations'], report.observations)
        with patch('naked_k_planner.naked_k_observations.analyze_observations', return_value={}):
            plain = a.build_trade_plan('测试', 'TEST', data)
        for key in ['action', 'signal_state', 'risk_plan', 'management']:
            self.assertEqual(getattr(report, key), getattr(plain, key))


if __name__ == '__main__':
    unittest.main()
