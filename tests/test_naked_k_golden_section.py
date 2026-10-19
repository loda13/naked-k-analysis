import copy
import json
import unittest

import numpy as np
import pandas as pd

import naked_k_analysis as analysis
import naked_k_verification as v
from tests.test_naked_k_verification import bars


def wave(knots=None, timeframe='daily'):
    knots = knots or [(0, 115), (5, 101), (30, 199), (60, 101), (66, 120)]
    positions, prices = zip(*knots)
    values = np.interp(range(positions[-1] + 1), positions, prices).tolist()
    return bars(values, pd.date_range(end='2026-10-16', periods=len(values),
                                     freq='B' if timeframe == 'daily' else 'W-FRI'))


class GoldenSectionTests(unittest.TestCase):
    def test_rise_retracement_and_fall_rebound_have_different_618_levels(self):
        for timeframe in ('daily', 'weekly'):
            with self.subTest(timeframe=timeframe):
                result = v.recent_golden_section(wave(timeframe=timeframe), timeframe)
                rise, fall = result['rising'], result['falling']
                self.assertEqual((rise['low'], rise['high']), (100., 200.))
                self.assertEqual((fall['low'], fall['high']), (100., 200.))
                self.assertAlmostEqual(rise['level_618'], 138.2)
                self.assertAlmostEqual(fall['level_618'], 161.8)
                self.assertEqual(rise['move_pct'], 100.)
                self.assertEqual(fall['move_pct'], -50.)
                self.assertEqual(rise['counter_move_pct'], 80.)
                self.assertEqual(fall['counter_move_pct'], 20.)
                self.assertEqual(rise['anchor_status'], 'confirmed_candidate')
                self.assertEqual(fall['anchor_status'], 'confirmed_candidate')
                self.assertEqual(rise['position'], 'below')
                self.assertEqual(result['reference_price'], 120.)
                json.dumps(result, allow_nan=False)

    def test_latest_qualified_leg_wins_over_older_largest_move(self):
        data = wave([(0, 150), (5, 101), (30, 299), (60, 151),
                     (85, 239), (115, 181), (130, 205)])
        result = v.recent_golden_section(data, 'daily')
        self.assertEqual((result['rising']['low'], result['rising']['high']), (150., 240.))
        self.assertEqual((result['falling']['low'], result['falling']['high']), (180., 240.))
        self.assertEqual(result['rising']['end_at'], data.index[85].isoformat())
        self.assertEqual(result['falling']['end_at'], data.index[115].isoformat())

    def test_confirmation_requires_available_following_bars(self):
        data = wave()
        pending = v.recent_golden_section(data.iloc[:35], 'daily')['rising']
        self.assertEqual(pending['anchor_status'], 'provisional_candidate')
        self.assertIsNone(pending['confirmed_at'])
        confirmed = v.recent_golden_section(data.iloc[:36], 'daily')['rising']
        self.assertEqual(confirmed['anchor_status'], 'confirmed_candidate')
        self.assertEqual(confirmed['confirmed_at'], data.index[35].isoformat())
        self.assertEqual(pending['level_618'], confirmed['level_618'])
        # Later extremes must not be visible in an earlier prefix's result.
        later = data.copy()
        later.loc[later.index[50], 'High'] = 500.
        self.assertEqual(pending, v.recent_golden_section(later.iloc[:35], 'daily')['rising'])

    def test_same_bar_high_low_order_is_not_invented(self):
        data = wave().iloc[:31].copy()
        data.loc[data.index[-1], 'Low'] = 50.
        self.assertEqual(v.recent_golden_section(data, 'daily')['rising']['status'], 'unavailable')

    def test_small_or_short_moves_are_not_called_major_phases(self):
        small = wave([(0, 105), (5, 101), (30, 106), (60, 102), (75, 104)])
        short = wave([(0, 115), (5, 101), (10, 199), (15, 150)])
        for data in (small, short):
            with self.subTest(rows=len(data)):
                result = v.recent_golden_section(data, 'daily')
                self.assertEqual(result['rising']['status'], 'unavailable')
                self.assertEqual(result['falling']['status'], 'unavailable')

    def test_exact_ten_percent_decline_qualifies(self):
        data = wave([(0, 95), (5, 99), (30, 91), (36, 95)])
        fall = v.recent_golden_section(data, 'daily')['falling']
        self.assertEqual(fall['status'], 'ready')
        self.assertEqual((fall['high'], fall['low']), (100., 90.))
        self.assertAlmostEqual(fall['move_pct'], -10.)

    def test_daily_window_does_not_reach_back_to_an_older_larger_extreme(self):
        data = wave([(0, 999), (40, 500), (100, 200), (130, 115), (135, 101),
                     (160, 199), (190, 101), (300, 120)])
        result = v.recent_golden_section(data, 'daily')
        self.assertEqual(result['rows'], 252)
        self.assertEqual(result['sample_start'], data.index[-252].isoformat())
        self.assertNotEqual(result['falling'].get('high'), 1000.)

    def test_boundary_origin_is_provisional_and_input_is_not_mutated(self):
        data = wave([(0, 101), (25, 199), (50, 150)])
        before = data.copy(deep=True)
        result = v.recent_golden_section(data, 'daily')
        self.assertEqual(result['rising']['anchor_status'], 'provisional_candidate')
        pd.testing.assert_frame_equal(data, before)

    def test_broken_origin_and_outside_range_are_not_clipped(self):
        data = wave()
        data.loc[data.index[-1], 'Low'] = 90.
        result = v.recent_golden_section(data, 'daily', reference_price=90.)
        rise = result['rising']
        self.assertAlmostEqual(rise['counter_move_pct'], 110.)
        self.assertTrue(rise['start_breached_since_end'])
        self.assertEqual((rise['low'], rise['high']), (100., 200.))
        recovered = v.recent_golden_section(data, 'daily', reference_price=120.)['rising']
        self.assertTrue(recovered['start_breached_since_end'])
        # A later comparable daily quote can cross a completed weekly leg's origin.
        quoted = v.recent_golden_section(wave(), 'weekly', reference_price=90.)
        self.assertTrue(quoted['rising']['start_breached_since_end'])

    def test_missing_data_and_invalid_reference_are_explicit(self):
        for data in (None, wave().iloc[:0]):
            self.assertEqual(v.recent_golden_section(data, 'weekly')['status'], 'unavailable')
        for price in (0., -1., float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                v.recent_golden_section(wave(), 'daily', reference_price=price)

    def test_independent_timeframes_respect_adjustment_basis_and_keep_main_plan(self):
        daily, weekly = wave(), wave(timeframe='weekly')
        weekly[['Open', 'High', 'Low', 'Close']] *= 2
        weekly.attrs['adjustment'] = 'qfq'
        report = analysis.build_trade_plan('测试', 'TEST', daily)
        before = copy.deepcopy(analysis.serialize_report(report))
        result = v.build_verification('TEST', daily, weekly, None, report.trend,
                                      pd.Timestamp('2026-10-18', tz='UTC'))
        golden = result['golden_section']
        self.assertEqual(golden['version'], 'golden-section-v1')
        self.assertEqual(set(golden['timeframes']), {'daily', 'weekly'})
        self.assertEqual(golden['timeframes']['weekly']['reference_basis'], 'weekly_close_only')
        self.assertEqual(golden['timeframes']['weekly']['reference_price'], 240.)
        self.assertEqual(golden['timeframes']['daily']['reference_price'], 120.)
        self.assertEqual(analysis.serialize_report(report), before)
        text = '\n'.join(v.format_verification(result))
        self.assertIn('### 黄金分割点判断（日线 / 周线）', text)
        self.assertIn('上涨回撤', text)
        self.assertIn('下跌反弹', text)
        self.assertIn('138.20', text)
        self.assertIn('161.80', text)
        self.assertIn('不是投资建议', text)

    def test_missing_weekly_keeps_daily_and_unclosed_week_cannot_supply_anchor(self):
        daily = wave()
        trend = analysis.build_trade_plan('测试', 'TEST', daily).trend
        now = pd.Timestamp('2026-10-19 11:00', tz='America/New_York')
        result = v.build_verification('TEST', daily, None, None, trend, now)
        self.assertEqual(result['golden_section']['timeframes']['daily']['status'], 'ready')
        self.assertEqual(result['golden_section']['timeframes']['weekly']['status'], 'unavailable')
        weekly = wave(timeframe='weekly')
        future = bars([999.], pd.to_datetime(['2026-10-23']))
        combined = pd.concat([weekly, future])
        combined.attrs.update(weekly.attrs, week_ending=True)
        baseline = v.build_verification('TEST', daily, weekly, None, trend, now)
        extended = v.build_verification('TEST', daily, combined, None, trend, now)
        self.assertEqual(baseline['golden_section'], extended['golden_section'])

    def test_same_date_close_mismatch_keeps_weekly_reference_separate(self):
        daily, weekly = wave(), wave(timeframe='weekly')
        weekly.loc[weekly.index[-1], ['Open', 'High', 'Low', 'Close']] = [125., 126., 124., 125.]
        trend = analysis.build_trade_plan('测试', 'TEST', daily).trend
        result = v.build_verification('TEST', daily, weekly, None, trend,
                                      pd.Timestamp('2026-10-18', tz='UTC'))
        self.assertEqual(result['golden_section']['timeframes']['weekly']['reference_price'], 125.)
        self.assertEqual(result['golden_section']['timeframes']['weekly']['reference_basis'], 'weekly_close_only')


if __name__ == '__main__':
    unittest.main()
