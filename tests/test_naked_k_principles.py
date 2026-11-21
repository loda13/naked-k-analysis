import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

import naked_k_analysis as cli
import naked_k_principles as rules
from naked_k_verification import closed_session_moves
from naked_k_observations import observation_frame
from naked_k_portfolio import assess_account
from tests.test_naked_k_analysis import market_frame
from tests.test_naked_k_observations import prices


def check_frame(frame, *, ticker='600000.SS', positions=None, snapshot=None, as_of=None):
    day = frame.index[-1].date().isoformat()
    state = None if positions is None else {
        'as_of': as_of or day, 'positions': positions, 'current_drawdown_pct': 0, 'consecutive_losses': 0}
    return rules.assess(observation_frame(frame), ticker, assess_account(state, day), snapshot)


def context(frame, **values):
    return {'as_of': frame.index[-1].date().isoformat(), 'source': 'test fixture', **values}


def position(ticker='600000.SS', **values):
    return {'ticker': ticker, 'gross_pct': 5, 'account_risk_pct': .1, **values}


class PriceVolumeTests(unittest.TestCase):
    def test_five_prior_positive_sessions_and_strict_volume_boundaries(self):
        frame = prices([100.] * 25 + [107.])
        for volume, expected in [(49., True), (50., False), (150., False)]:
            frame.loc[frame.index[-1], 'Volume'] = volume
            result = check_frame(frame)['checks']['volume_setup']['values']
            self.assertEqual(result['volume_ratio_5'], volume / 100)
            self.assertIs(result['dry_new_high'], expected)
            self.assertNotEqual(result['pullback_stage'], 'breakout')
        for invalid in [0., float('nan')]:
            frame.loc[frame.index[-3], 'Volume'] = invalid
            self.assertIsNone(check_frame(frame)['checks']['volume_setup']['values']['volume_ratio_5'])
        one = check_frame(frame.iloc[:1])
        self.assertEqual(len(one['checks']), 10)
        json.dumps(one, allow_nan=False)

    def test_breakout_pullback_is_dated_and_intervening_failure_stays_failed(self):
        frame = prices([100.] * 27 + [103., 100.7])
        frame.loc[frame.index[-2:], 'Volume'] = [160., 55.]
        at_breakout = check_frame(frame.iloc[:-1])['checks']['volume_setup']['values']
        self.assertEqual(at_breakout['pullback_stage'], 'breakout')
        latest = check_frame(frame)['checks']['volume_setup']['values']
        self.assertEqual(latest['pullback_stage'], 'held')
        self.assertEqual(latest['breakout_date'], frame.index[-2].date().isoformat())
        self.assertEqual(latest['breakout_level'], 100.5)
        later = prices([100.] * 27 + [103., 99., 102., 100.7])
        later.loc[later.index[-4:], 'Volume'] = [160., 55., 90., 55.]
        self.assertEqual(check_frame(later)['checks']['volume_setup']['values']['pullback_stage'], 'failed')

    def test_ma_cross_and_volume_price_state_are_specific_to_the_ticker(self):
        frame = prices([100.] * 25 + [106.], volume=[100.] * 25 + [210.])
        checks = check_frame(frame)['checks']
        self.assertEqual(checks['ma_trend']['values']['ma20_event'], 'volume_breakout')
        self.assertEqual(checks['ma_trend']['values']['ma5_event'], 'volume_breakout')
        self.assertEqual(checks['price_volume']['values']['daily_pattern'], 'volume_surge')
        frame.loc[frame.index[-1], ['Open', 'High', 'Low', 'Close']] = [99., 100., 97., 98.]
        checks = check_frame(frame)['checks']
        self.assertEqual(checks['ma_trend']['values']['ma20_event'], 'breakdown')
        self.assertIn('跌破', checks['ma_trend']['detail'])
        self.assertEqual(checks['price_volume']['values']['daily_pattern'], 'expanded_decline')

    def test_impulse_contraction_small_body_dates_and_low_invalidation(self):
        frame = prices([100.] * 22 + [106., 105., 105.5])
        frame.iloc[-3:] = [[100., 107., 99., 106., 200.], [106., 106., 100., 105., 100.],
                           [105., 106., 100., 105.5, 80.]]
        for stop, stage in [(-2, 'impulse'), (-1, 'contraction'), (None, 'confirmed')]:
            item = check_frame(frame.iloc[:stop])['checks']['volume_candles']
            self.assertEqual(item['values']['stage'], stage)
            self.assertEqual(item['values']['impulse_date'], frame.index[-3].date().isoformat())
        for which in [-1, -2]:
            broken = frame.copy()
            broken.loc[broken.index[which], 'Low'] = 98.
            self.assertEqual(check_frame(broken)['checks']['volume_candles']['values']['stage'], 'invalidated')
        frame.loc[frame.index[-2], 'Volume'] = 101.
        self.assertNotEqual(check_frame(frame)['checks']['volume_candles']['values']['stage'], 'confirmed')


class DisciplineAndContextTests(unittest.TestCase):
    def test_loss_floor_armed_profit_floor_and_unknown_peak(self):
        frame = prices([100.] * 25)
        for pnl, peak, expected in [(-5.01, None, 'loss_limit'), (-5., 6., 'tracking'),
                                    (10., 15., 'profit_floor'), (11., 15., 'armed'),
                                    (15., None, 'armed'), (10., None, 'peak_unknown')]:
            values = check_frame(frame, positions=[position(pnl_pct=pnl, peak_pnl_pct=peak)])['checks']
            self.assertEqual(values['profit_discipline']['values']['stage'], expected)
        for stamp in ['2020-01-01', '2030-01-01']:
            values = check_frame(frame, positions=[position(pnl_pct=-8.)], as_of=stamp)['checks']
            self.assertEqual(values['profit_discipline']['status'], 'unavailable')
            self.assertIsNone(values['portfolio_focus']['values']['held_count'])
        with self.assertRaises(ValueError):
            check_frame(frame, positions=[position(pnl_pct=12., peak_pnl_pct=9.)])

    def test_portfolio_counts_only_actual_holdings_and_handles_missing_returns(self):
        frame = prices([100.] * 25 + [95.])
        holdings = [position(pnl_pct=-6.)] + [position(f'X{i}', pnl_pct=-1.) for i in range(3)]
        holdings += [position('UNKNOWN'), position('PROFIT', pnl_pct=2.), position('ZERO', gross_pct=0, account_risk_pct=0)]
        values = check_frame(frame, positions=holdings)['checks']['portfolio_focus']['values']
        self.assertEqual((values['held_count'], values['losing_count'], values['pnl_unknown_count']), (6, 4, 1))
        self.assertIs(values['review_weak_holding'], True)
        del holdings[0]['pnl_pct']
        self.assertIsNone(check_frame(frame, positions=holdings)['checks']['portfolio_focus']['values']['majority_losing'])
        self.assertEqual(check_frame(frame, positions=[])['checks']['portfolio_focus']['values']['held_count'], 0)
        self.assertIsNone(check_frame(frame)['checks']['portfolio_focus']['values']['held_count'])

    def test_dated_supplement_for_turnover_stress_sector_and_a_share_limit_events(self):
        frame = prices([100.] * 25 + [106.], volume=[100.] * 25 + [180.])
        facts = context(frame, turnover_pct=5., limit_state='opened', prior_limit_up_days=2,
                        stress={'time': '10:30', 'advancers': 20, 'decliners': 80,
                                'ticker_change_pct': -1., 'index_change_pct': -3.},
                        sector={'name': '示例板块', 'rank': 2, 'count': 10, 'change_pct': 1.5,
                                'previous_change_pct': .4, 'flow_direction': 'in'})
        checks = check_frame(frame, snapshot=facts)['checks']
        for key in ['turnover', 'market_stress', 'sector_theme', 'limit_disagreement']:
            self.assertEqual(checks[key]['status'], 'met', key)
        for rate, expected in [(4.99, 'not_met'), (30., 'met'), (30.01, 'not_met')]:
            checks = check_frame(frame, snapshot={**facts, 'turnover_pct': rate})['checks']
            self.assertEqual(checks['turnover']['status'], expected)
        stale = check_frame(frame, snapshot={**facts, 'as_of': '2030-01-01'})
        self.assertEqual(stale['context_status'], 'future')
        self.assertEqual(stale['checks']['market_stress']['status'], 'unavailable')
        self.assertIsNone(stale['checks']['turnover']['values']['turnover_pct'])
        for symbol in ['QQQ', '0700.HK', '005930.KS']:
            checks = check_frame(frame, ticker=symbol, snapshot=facts)['checks']
            self.assertEqual(checks['limit_disagreement']['status'], 'not_applicable')
        for invalid in [{'turnover_pct': False}, {'turnover_pct': float('inf')}, {'limit_state': 'guessed'},
                        {'stress': {**facts['stress'], 'advancers': -1}},
                        {'stress': {**facts['stress'], 'time': '23:59'}},
                        {'stress': {**facts['stress'], 'time': '12:30'}}]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                check_frame(frame, snapshot={**facts, **invalid})

    def test_limit_up_and_turnover_are_never_inferred_from_daily_price(self):
        frame = prices([100.] * 25 + [110.], volume=[100.] * 25 + [80.])
        checks = check_frame(frame)['checks']
        self.assertIsNone(checks['volume_setup']['values']['light_limit_up'])
        self.assertEqual(checks['limit_disagreement']['status'], 'unavailable')
        light = check_frame(frame, snapshot=context(frame, limit_state='closed', prior_limit_up_days=2))
        self.assertIs(light['checks']['volume_setup']['values']['light_limit_up'], True)
        self.assertEqual(light['checks']['limit_disagreement']['values']['stage'], 'sealed_contraction')
        frame.loc[frame.index[-1], ['Open', 'High', 'Low', 'Close', 'Volume']] = [100., 110.5, 99., 105., 180.]
        self.assertEqual(check_frame(frame, snapshot=context(frame, turnover_pct=8.))['checks']['turnover']['status'], 'not_met')

    def test_intraday_requires_a_complete_matching_session(self):
        day = '2026-11-20'
        clock = pd.Timestamp(day + ' 16:01', tz='America/New_York')
        hours = prices([97., 99., 99., 99., 99., 99., 103.])
        hours.index = pd.date_range(day + ' 09:30', periods=7, freq='h', tz='America/New_York').tz_convert('UTC')
        hours.iloc[0] = [100., 100., 96., 97., 100.]
        hours.iloc[-1] = [99., 104., 98., 103., 100.]
        hours.attrs['source'] = 'yahoo_chart'
        session = closed_session_moves('TEST', day, hours, clock)
        self.assertAlmostEqual(session['opening_low_pct'], -4.)
        self.assertAlmostEqual(session['close_from_open_pct'], 3.)
        self.assertGreater(session['last_bar_pct'], 3.)
        for subset, now in [(hours.iloc[:-1], clock), (hours.drop(hours.index[2]), clock),
                            (hours, clock - pd.Timedelta(hours=1))]:
            self.assertIsNone(closed_session_moves('TEST', day, subset, now))
        self.assertIsNone(closed_session_moves('TEST', '2026-11-19', hours, clock))
        frame = prices([100.] * 25)
        values = check_frame(frame, snapshot=context(frame, session={
            'opening_low_pct': -4., 'close_from_open_pct': 3., 'last_bar_pct': 4.}))['checks']['price_volume']['values']
        self.assertIs(values['opening_drop_recovered'], True)
        self.assertIs(values['late_surge'], True)

    def test_a_share_session_uses_four_end_stamped_tencent_bars_with_lunch(self):
        day = '2026-11-20'
        times = ['10:30', '11:30', '14:00', '15:00']
        frame = prices([10., 10., 10., 11.])
        local = pd.DatetimeIndex([day + ' ' + t for t in times], tz='Asia/Shanghai')
        frame.index = local.tz_convert('UTC').tz_localize(None)
        frame.attrs['source'] = 'tencent'
        session = closed_session_moves('600000.SS', day, frame, local[-1])
        self.assertEqual(session['source'], 'tencent')
        self.assertAlmostEqual(session['close_from_open_pct'], (11. / 9.9 - 1) * 100)
        self.assertIsNone(closed_session_moves('600000.SS', day, frame.iloc[:-1], local[-1]))
        self.assertIsNone(closed_session_moves('600000.SS', day, frame, local[-2]))

    def test_same_day_provider_facts_and_explicit_source_precedence(self):
        frame = prices([100.] * 25 + [106.], volume=[100.] * 25 + [180.])
        frame.attrs['closing_quote'] = {**context(frame, turnover_pct=8., limit_state='untouched'),
                                        'source': 'tencent_qt', 'ticker': '600000.SS'}
        auto = check_frame(frame)
        self.assertEqual(auto['checks']['turnover']['status'], 'met')
        self.assertEqual(auto['checks']['limit_disagreement']['status'], 'not_met')
        manual = check_frame(frame, snapshot=context(frame, turnover_pct=3.))
        self.assertEqual(manual['checks']['turnover']['values']['turnover_pct'], 3.)
        self.assertEqual(manual['checks']['turnover']['values']['source'], 'test fixture')
        for other in (check_frame(frame.iloc[:-1]), check_frame(frame, ticker='600001.SS')):
            self.assertIsNone(other['checks']['turnover']['values']['turnover_pct'])

    def test_quote_published_later_than_replay_clock_is_excluded(self):
        daily = market_frame()
        daily.attrs['closing_quote'] = {**context(daily, turnover_pct=8.), 'ticker': '600000.SS',
                                        'source': 'tencent_qt', 'observed_at': '2026-09-04T16:15:00+08:00'}
        with TemporaryDirectory() as root, patch.object(cli, 'load_ohlcv', return_value=daily):
            _, reports = cli.run_analysis([('TEST', '600000.SS')], Path(root) / 'j',
                                          now=pd.Timestamp('2026-09-04 16:05', tz='Asia/Shanghai'))
        self.assertIsNone(reports[0].principles['provider_quote'])
        self.assertIn('closing_quote', daily.attrs)

    def test_report_cli_journal_audit_and_decision_isolation(self):
        daily = market_frame()
        with TemporaryDirectory() as root, patch.object(cli, 'load_ohlcv', return_value=daily):
            path = Path(root)
            context_path = path / 'c.json'
            context_path.write_text(json.dumps({'TEST': context(daily, turnover_pct=8.)}))
            args = ['naked_k_analysis.py', 'TEST', '--json', '--context-path', str(context_path),
                    '--report-path', str(path / 'r.md'), '--journal-path', str(path / 'j'),
                    '--audit-path', str(path / 'a')]
            output = io.StringIO()
            with patch('sys.argv', args), redirect_stdout(output):
                self.assertEqual(cli.main(), 0)
            payload = json.loads(output.getvalue())
            item, text = payload['items'][0], payload['report']
            self.assertEqual((path / 'r.md').read_text(), text)
            self.assertEqual(item['principles'], json.loads((path / 'j').read_text())['principles'])
            self.assertIn('### 交易理念核对', text)
            self.assertIn('黄金分割点判断', text)
            self.assertIn('技术信号观察附录', text)
            self.assertNotIn('币哥', text.splitlines()[0])
            events = [json.loads(line) for line in (path / 'a').read_text().splitlines()]
            self.assertEqual(next(e['payload'] for e in events if e['event_type'] == 'plan_generated')['principles_version'],
                             item['principles']['version'])
        with patch('naked_k_planner.naked_k_principles.assess', return_value={}):
            baseline = cli.build_trade_plan('TEST', 'TEST', daily)
        evaluated = cli.build_trade_plan('TEST', 'TEST', daily, context=context(daily, turnover_pct=8.))
        for key in ['trend', 'action', 'signal_state', 'risk_plan', 'management', 'stop_loss', 'target_price', 'observations']:
            self.assertEqual(getattr(baseline, key), getattr(evaluated, key))
