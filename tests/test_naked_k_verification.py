import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

import naked_k_analysis as analysis
import naked_k_verification as v
from tests.test_naked_k_analysis import market_frame


def bars(values, index, source='yahoo_chart', adjustment='split_only'):
    data = pd.DataFrame({'Open': values, 'High': [x + 1 for x in values],
                         'Low': [x - 1 for x in values], 'Close': values,
                         'Volume': [100.] * len(values)}, index=index)
    data.attrs.update(source=source, adjustment=adjustment)
    return data


class VerificationTests(unittest.TestCase):
    def test_retracement_measures_rise_not_price_drop(self):
        data = bars([105, 104, 101, 108, 119, 115, 113, 110], pd.date_range('2026-01-02', periods=8, freq='W-FRI'))
        fib = v.major_retracement(data, 110.)
        self.assertEqual((fib['low'], fib['high']), (100., 120.))
        self.assertEqual(fib['retracement_pct'], 50.)
        self.assertAlmostEqual(fib['drawdown_from_high_pct'], 100 / 12)
        self.assertAlmostEqual(next(p['price'] for p in fib['levels'] if p['ratio'] == .618), 107.64)
        self.assertEqual(fib['anchor_status'], 'confirmed_candidate')
        broken = v.major_retracement(data, 99.)
        self.assertEqual(broken['origin_status'], 'below_origin')
        self.assertEqual(broken['low'], 100.)
        self.assertIsNone(broken['nearest_support'])
        self.assertEqual(v.major_retracement(data, 121.)['origin_status'], 'above_anchor_high')
        data.loc[data.index[-1], 'Low'] = 99.
        reclaimed = v.major_retracement(data, 110.)
        self.assertEqual(reclaimed['origin_status'], 'reclaimed_after_break')
        self.assertEqual(reclaimed['low'], 100.)

    def test_endpoint_and_same_bar_order_are_not_invented(self):
        data = bars([100., 110., 120.], pd.date_range('2026-01-02', periods=3, freq='W-FRI'))
        self.assertEqual(v.major_retracement(data, 120.)['anchor_status'], 'provisional_candidate')
        data.loc[data.index[-1], 'Low'] = 80.
        self.assertEqual(v.major_retracement(data, 120.)['status'], 'unavailable')

    def test_weekly_utc_calendar_duplicate_quote_and_future_are_checked(self):
        data = bars([100., 110., 111., 999.], pd.to_datetime(
            ['2026-10-04 15:00', '2026-10-11 15:00', '2026-10-16 06:30', '2026-10-18 15:00']))
        result = v.prepare_weekly(data, '005930.KS', pd.Timestamp('2026-10-17', tz='Asia/Seoul'))
        self.assertEqual(result.index.strftime('%Y-%m-%d').tolist(), ['2026-10-09', '2026-10-16'])
        self.assertEqual(result.Close.tolist(), [100., 110.])
        self.assertEqual(result.attrs['duplicate_week_rows_removed'], 1)
        self.assertTrue(result.equals(v.prepare_weekly(result, '005930.KS', pd.Timestamp('2026-10-17', tz='Asia/Seoul'))))
        before_close = v.prepare_weekly(data, '005930.KS', pd.Timestamp('2026-10-16 15:00', tz='Asia/Seoul'))
        self.assertEqual(len(before_close), 1)

    def test_hourly_bar_must_finish_and_four_hour_never_crosses_sessions(self):
        index = pd.date_range('2026-10-15 09:30', periods=7, freq='h', tz='America/New_York').append(
            pd.date_range('2026-10-16 09:30', periods=7, freq='h', tz='America/New_York'))
        data = bars(list(range(100, 114)), index.tz_convert('UTC').tz_localize(None))
        hourly, four = v.prepare_intraday(data, 'TEST', pd.Timestamp('2026-10-16 10:00', tz='America/New_York'))
        self.assertEqual(len(hourly), 7)
        self.assertEqual(len(four), 2)
        self.assertEqual(four.Volume.tolist(), [400., 300.])
        hourly, four = v.prepare_intraday(data, 'TEST', pd.Timestamp('2026-10-16 16:00', tz='America/New_York'))
        self.assertEqual(len(hourly), 14)
        self.assertEqual(len(four), 4)
        self.assertEqual(four.Close.tolist(), [103., 106., 110., 113.])

    def test_missing_korean_tail_is_not_repaired_with_a_zero_volume_quote(self):
        index = pd.date_range('2026-10-16 09:00', periods=7, freq='h', tz='Asia/Seoul')
        data = bars([100.] * 7, index.tz_convert('UTC').tz_localize(None))
        data.iloc[-1] = [100., 100., 100., 100., 0.]
        hourly, four = v.prepare_intraday(data, '005930.KS', pd.Timestamp('2026-10-17', tz='Asia/Seoul'))
        self.assertEqual(len(hourly), 6)
        self.assertEqual(hourly.attrs['verification_status'], 'partial_session')
        self.assertTrue(four.empty)
        self.assertIn('尾盘', four.attrs['verification_reason'])

    def test_verification_cannot_mutate_signal_or_infer_support_from_fib(self):
        daily = market_frame()
        report = analysis.build_trade_plan('测试', 'TEST', daily)
        before = copy.deepcopy(analysis.serialize_report(report))
        weekly = bars([231 - i for i in range(130)], pd.date_range(end='2026-09-04', periods=130, freq='W-FRI'), source='fixture', adjustment='qfq')
        result = v.build_verification('TEST', daily, weekly, None, report.trend, pd.Timestamp('2026-09-06', tz='UTC'))
        self.assertEqual(result['timeframes']['weekly']['relation_to_daily'], 'conflicting')
        self.assertEqual(result['status'], 'mixed')
        self.assertEqual(analysis.serialize_report(report), before)
        self.assertNotIn('entry_candidate', result)
        self.assertNotIn('risk_plan', result)
        json.dumps(result, allow_nan=False)

    def test_same_date_weekly_close_mismatch_blocks_confluence(self):
        daily = market_frame()
        weekly = bars([105, 104, 101, 108, 119, 115, 113, 110], pd.date_range(end='2026-09-04', periods=8, freq='W-FRI'), source='fixture', adjustment='qfq')
        trend = analysis.build_trade_plan('测试', 'TEST', daily).trend
        result = v.build_verification('TEST', daily, weekly, None, trend, pd.Timestamp('2026-09-06', tz='UTC'))
        self.assertFalse(result['timeframes']['weekly']['comparable_to_daily'])
        self.assertEqual(result['major_retracement']['reference_basis'], 'weekly_close_only')
        self.assertTrue(any('收盘不一致' in line for line in result['limitations']))

    def test_mixed_adjustment_cannot_conflate_price_levels(self):
        daily = market_frame()
        weekly = bars([100., 110., 120., 111.], pd.date_range(end='2026-09-04', periods=4, freq='W-FRI'))
        trend = analysis.build_trade_plan('测试', 'TEST', daily).trend
        result = v.build_verification('TEST', daily, weekly, None, trend, pd.Timestamp('2026-09-06', tz='UTC'))
        self.assertFalse(result['timeframes']['weekly']['comparable_to_daily'])
        self.assertEqual(result['major_retracement']['reference_price'], 111.)
        self.assertEqual(result['major_retracement']['reference_basis'], 'weekly_close_only')
        self.assertFalse(any(p['nearby_references'] for p in result['major_retracement']['levels']))

    def test_aligned_averages_do_not_confirm_a_provisional_wave(self):
        daily = bars(list(range(100, 230)), pd.date_range(end='2026-09-04', periods=130, freq='B'))
        weekly = bars(list(range(100, 230)), pd.date_range(end='2026-09-04', periods=130, freq='W-FRI'))
        days = pd.date_range(end='2026-09-04', periods=65, freq='B', tz='America/New_York')
        index = pd.DatetimeIndex([day + pd.Timedelta(minutes=570 + 60 * i) for day in days for i in range(7)])
        hourly = bars([100 + 129 * i / (len(index) - 1) for i in range(len(index))], index.tz_convert('UTC').tz_localize(None))
        trend = analysis.build_trade_plan('测试', 'TEST', daily).trend
        now = pd.Timestamp('2026-09-06', tz='UTC')
        result = v.build_verification('TEST', daily, weekly, hourly, trend, now)
        self.assertEqual(len(result['supporting']), 3)
        self.assertEqual(result['major_retracement']['anchor_status'], 'provisional_candidate')
        self.assertEqual(result['status'], 'partial')
        short = daily.tail(20).copy()
        unknown = v.build_verification('TEST', short, weekly, hourly,
                                       analysis.build_trade_plan('测试', 'TEST', short).trend, now)
        self.assertFalse(unknown['conflicting'])
        self.assertFalse(unknown['supporting'])
        self.assertTrue(any('日线' in line and '不足' in line for line in unknown['limitations']))

    def test_two_transition_timeframes_are_uncertain_not_opposite(self):
        daily = bars([100.] * 130, pd.date_range(end='2026-09-04', periods=130, freq='B'))
        weekly = bars([100.] * 130, pd.date_range(end='2026-09-04', periods=130, freq='W-FRI'))
        trend = analysis.build_trade_plan('测试', 'TEST', daily).trend
        result = v.build_verification('TEST', daily, weekly, None, trend, pd.Timestamp('2026-09-06', tz='UTC'))
        self.assertEqual(trend['direction'], 'transition')
        self.assertFalse(result['conflicting'])
        self.assertEqual(result['timeframes']['weekly']['relation_to_daily'], 'indeterminate')

    def test_integrated_report_keeps_plan_first_and_failure_is_nonfatal(self):
        daily = market_frame()
        weekly = daily.copy()
        def load(ticker, interval, period):
            if interval == '1h': raise ValueError('hourly unavailable')
            return daily.copy() if interval == '1d' else weekly.copy()
        with TemporaryDirectory() as directory, patch.object(analysis, 'load_ohlcv', side_effect=load):
            text, reports = analysis.run_analysis([('测试', 'TEST')], Path(directory) / 'j.jsonl', now=pd.Timestamp('2026-09-06', tz='UTC'))
            self.assertLess(text.index('双均线主线与交易计划'), text.index('交叉验证'))
            self.assertLess(text.index('交叉验证'), text.index('辅助结构'))
            self.assertEqual(reports[0].trend, analysis.build_trade_plan('测试', 'TEST', daily).trend)
            saved = json.loads((Path(directory) / 'j.jsonl').read_text())
            self.assertEqual(saved['verification'], reports[0].verification)
            self.assertIn('数据不足', text)


if __name__ == '__main__':
    unittest.main()
