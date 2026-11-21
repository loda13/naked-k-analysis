"""Dated, read-only checks for ten trading principles, using closed daily bars."""
from __future__ import annotations

from datetime import date, time
from math import inf

import pandas as pd

from naked_k_config import number
from naked_k_portfolio import classify_market
from naked_k_trend import _number
from naked_k_verification import _session

VERSION = 'market-principles-v1'
TITLES = {
    'profit_discipline': '持仓止损与利润保护', 'volume_setup': '缩量新高与放量突破回踩',
    'portfolio_focus': '持仓数量与弱势仓位', 'price_volume': '日内节奏与量价',
    'ma_trend': 'MA5 短线与 MA20 波段', 'market_stress': '市场情绪与个股相对强弱',
    'sector_theme': '题材、资金与板块承接', 'turnover': '强势日量能与换手',
    'volume_candles': '倍阳缩倍阴', 'limit_disagreement': '连板分歧与一致性',
}
STATUS = {'met': '条件符合', 'not_met': '条件未满足', 'watch': '跟踪', 'review': '需复核',
          'observed': '已观察', 'unavailable': '资料不足', 'not_applicable': '不适用'}


def _check(status, detail, **values):
    return {'status': status, 'detail': detail, 'values': values}


def _fmt(value, unit=''):
    return '未知' if value is None else f'{value:.2f}{unit}'


def _day(data, i):
    return data.index[i].date().isoformat()


def _fields(value, name, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError(f'invalid {name} fields')


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value.splitlines()) != 1:
        raise ValueError(f'{name} must be nonempty single-line text')


def _count(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')


def _context(snapshot, as_of, market):
    if snapshot is None:
        return {}, 'missing'
    _fields(snapshot, 'context', ('as_of', 'source'),
            ('turnover_pct', 'limit_state', 'prior_limit_up_days', 'stress', 'sector', 'session'))
    _text(snapshot['source'], 'context.source')
    try:
        day = date.fromisoformat(snapshot['as_of']).isoformat()
    except (ValueError, TypeError):
        raise ValueError('context.as_of must be YYYY-MM-DD') from None
    if day != snapshot['as_of']:
        raise ValueError('context.as_of must be YYYY-MM-DD')
    if day != as_of:
        return {}, 'stale' if day < as_of else 'future'
    if 'turnover_pct' in snapshot:
        number(snapshot['turnover_pct'], 'turnover_pct', 0, inf)
    if 'limit_state' in snapshot and snapshot['limit_state'] not in ('closed', 'opened', 'touched_unsealed', 'untouched', 'no_limit'):
        raise ValueError('invalid limit_state')
    if 'prior_limit_up_days' in snapshot:
        _count(snapshot['prior_limit_up_days'], 'prior_limit_up_days')
    if 'session' in snapshot:
        moves = snapshot['session']
        _fields(moves, 'session', ('opening_low_pct', 'close_from_open_pct', 'last_bar_pct'))
        for key, value in moves.items():
            number(value, key, -100, 0 if key == 'opening_low_pct' else inf)
    if 'stress' in snapshot:
        sample = snapshot['stress']
        _fields(sample, 'stress', ('time', 'advancers', 'decliners', 'ticker_change_pct', 'index_change_pct'))
        try:
            sample_time = time.fromisoformat(sample['time'])
        except (ValueError, TypeError):
            raise ValueError('stress.time requires local HH:MM') from None
        if sample_time.strftime('%H:%M') != sample['time']:
            raise ValueError('stress.time requires local HH:MM')
        opening, closing = _session(pd.Timestamp(day), market)
        sample_at = pd.Timestamp.combine(opening.date(), sample_time)
        lunch_start = {'cn': time(11, 30), 'hk': time(12)}.get(market)
        if not opening <= sample_at <= closing or (lunch_start and lunch_start < sample_time < time(13)):
            raise ValueError('stress.time is outside the regular local trading session')
        for key in ('advancers', 'decliners'):
            _count(sample[key], key)
        for key in ('ticker_change_pct', 'index_change_pct'):
            number(sample[key], key, -100, inf)
    if 'sector' in snapshot:
        sector = snapshot['sector']
        _fields(sector, 'sector', ('name', 'rank', 'count', 'change_pct', 'previous_change_pct'), ('flow_direction',))
        _text(sector['name'], 'sector.name')
        _count(sector['rank'], 'sector.rank', 1)
        _count(sector['count'], 'sector.count', sector['rank'])
        for key in ('change_pct', 'previous_change_pct'):
            number(sector[key], key, -100, inf)
        if sector.get('flow_direction') not in (None, 'in', 'out', 'flat'):
            raise ValueError('invalid sector.flow_direction')
    return snapshot, 'matched'


def _discipline(held, account_status):
    pnl, peak = (held or {}).get('pnl_pct'), (held or {}).get('peak_pnl_pct')
    if account_status != 'known':
        stage, status, detail = 'unknown_position', 'unavailable', '需行情日的真实账户快照。'
    elif held is None:
        stage, status, detail = 'no_position', 'not_applicable', '同日快照中该标的持仓为零。'
    elif pnl is None:
        stage, status, detail = 'missing_return', 'unavailable', '缺少这笔持仓的收盘盈亏率。'
    elif pnl < -5:
        stage, status, detail = 'loss_limit', 'review', '单笔亏损超过成本的 5%，复核止损纪律。'
    elif peak is not None and peak >= 15 and pnl <= 10:
        stage, status, detail = 'profit_floor', 'review', '曾达到 +15%，现已回落至 +10% 或以下，复核利润保护。'
    elif pnl >= 15 or (peak is not None and peak >= 15):
        stage, status, detail = 'armed', 'watch', '已达到 +15% 启动条件，跟踪 +10% 利润保护线。'
    elif peak is None:
        stage, status, detail = 'peak_unknown', 'unavailable', '持仓期间最高收盘盈亏率未知，利润保护的启动状态待核实。'
    else:
        stage, status, detail = 'tracking', 'not_met', '当前未触及单笔亏损或利润保护条件。'
    if held is not None:
        detail += f' 本笔盈亏 {_fmt(pnl, "%")}，持仓期最高 {_fmt(peak, "%")}。'
    return _check(status, detail, stage=stage, pnl_pct=pnl, peak_pnl_pct=peak)


def _portfolio(positions, held, row):
    if positions is None:
        return _check('unavailable', '持仓只数与亏损分布需要同日账户快照。', held_count=None,
                      losing_count=None, pnl_unknown_count=None, majority_losing=None, review_weak_holding=None)
    n = len(positions)
    losing = sum(p.get('pnl_pct') is not None and p['pnl_pct'] < 0 for p in positions)
    missing = sum(p.get('pnl_pct') is None for p in positions)
    majority = True if losing * 2 > n else False if (losing + missing) * 2 <= n else None
    weak = None if pd.isna(row.sma20) else bool(row.Close < row.sma20)
    priority = False
    if n > 5 and held is not None and majority is not False and weak is not False:
        priority = True if majority is True and weak is True else None
    if n == 0:
        note = '账户空仓。'
    elif n <= 3:
        note = '只数落在 2–3 只观察范围。' if n >= 2 else '当前集中于一只标的。'
    else:
        note = '已达 4 只观察上限。' if n == 4 else '超过 4 只观察上限。'
    if priority:
        note += ' 超过 5 只且多数亏损，本标的收在 MA20 下方，列入优先复核。'
    elif priority is None:
        note += ' 多数亏损或本标的 MA20 位置尚待核实。'
    return _check('review' if n > 4 else 'observed',
                  f'实持 {n} 只，已知亏损 {losing} 只，盈亏未知 {missing} 只。{note}',
                  held_count=n, losing_count=losing, pnl_unknown_count=missing,
                  majority_losing=majority, review_weak_holding=priority)


def _ma_event(data, period, ratio):
    ma = data[f'sma{period}']
    close, line = data.Close.iloc[-1], ma.iloc[-1]
    if pd.isna(line):
        return 'unavailable'
    if len(data) > 1 and pd.notna(ma.iloc[-2]):
        previous = data.Close.iloc[-2]
        if previous <= ma.iloc[-2] and close > line:
            return 'volume_breakout' if ratio is not None and ratio > 1.5 else 'breakout'
        if previous >= ma.iloc[-2] and close < line:
            return 'breakdown'
    return 'above' if close > line else 'below' if close < line else 'at'


def _ma_trend(data, ratio):
    labels = {'unavailable': '样本不足', 'volume_breakout': '放量上穿', 'breakout': '上穿',
              'breakdown': '跌破', 'above': '线上', 'below': '线下', 'at': '与均线持平'}
    values, parts = {}, []
    for period in (5, 20):
        key = f'ma{period}'
        line = _number(data[f'sma{period}'].iloc[-1])
        event = _ma_event(data, period, ratio)
        values.update({key: line, f'{key}_event': event})
        parts.append(f'MA{period} {_fmt(line)}（{labels[event]}）')
    return _check('unavailable' if values['ma5'] is None else 'observed', '，'.join(parts) + '。', **values)


def _pullback(data, ratios):
    last = len(data) - 1
    for i in range(last, max(0, last - 6), -1):
        bar, previous = data.iloc[i], data.iloc[i - 1]
        if not ratios.iloc[i] > 1.5:
            continue
        if bar.Close > bar.channel_high:
            level = float(bar.channel_high)
        elif previous.Close <= previous.sma20 and bar.Close > bar.sma20:
            level = float(bar.sma20)
        else:
            continue
        if i == last:
            stage = 'breakout'
        elif (data.Close.iloc[i + 1:] < level).any():
            stage = 'failed'
        elif pd.isna(ratios.iloc[-1]):
            stage = 'unknown_volume'
        elif (data.Close.iloc[-1] < data.Close.iloc[-2] and data.Low.iloc[-1] <= level * 1.01
              and ratios.iloc[-1] < 1 and data.Volume.iloc[-1] < bar.Volume):
            stage = 'held'
        else:
            stage = 'waiting'
        return stage, _day(data, i), level
    covered = len(data) >= 26 and ratios.iloc[-6:].notna().all()
    return ('none' if covered else 'insufficient'), None, None


def _volume_setup(data, ratios, facts, market):
    row = data.iloc[-1]
    ratio = _number(ratios.iloc[-1])
    high = _number(row.channel_high)
    dry = bool(ratio < .5 and row.Close > high) if ratio is not None and high is not None else None
    rising = (bool(row.Close > row.sma20 > data.sma20.iloc[-2])
              if len(data) > 1 and pd.notna(data.sma20.iloc[-2]) else None)
    limit = facts.get('limit_state') if market == 'cn' else None
    light = bool(limit == 'closed' and ratio < 1) if limit in ('opened', 'closed', 'touched_unsealed', 'untouched') and ratio is not None else None
    stage, day, level = _pullback(data, ratios)
    stages = {'breakout': '当日放量突破', 'failed': '突破位已被收盘跌破', 'held': '缩量回踩守位',
              'waiting': '等待缩量回踩', 'unknown_volume': '回踩日量能不足', 'none': '近六日未见放量突破',
              'insufficient': '突破窗口资料不足'}
    details = [f'日量比 {_fmt(ratio, " 倍")}', stages[stage] + (f'（{day} 突破位 {_fmt(level)}）' if day else '')]
    if ratio is not None and ratio < .5:
        details.append('明显缩量')
    if dry:
        details.append('收盘超过前 20 日最高价' + ('，MA20 上行且收盘在线上' if rising else ''))
    if light:
        details.append('当日缩量封板')
    if dry or light or stage == 'held':
        status = 'met'
    elif stage == 'failed':
        status = 'review'
    elif stage in ('waiting', 'breakout'):
        status = 'watch'
    elif ratio is None or stage in ('insufficient', 'unknown_volume'):
        status = 'unavailable'
    else:
        status = 'not_met'
    return _check(status, '，'.join(details) + '。', volume_ratio_5=ratio, prior_20_high=high,
                  dry_new_high=dry, rising_ma20=rising, light_limit_up=light,
                  pullback_stage=stage, breakout_date=day, breakout_level=level)


def _price_volume(data, change, ratio, session):
    pattern = 'unavailable'
    if change is not None and ratio is not None:
        pattern = 'ordinary'
        if change > 5 and ratio >= 2:
            pattern = 'volume_surge'
        elif abs(change) <= 1 and ratio > 1.5:
            pattern = 'expanded_stall'
        elif ratio > 1.5:
            pattern = 'expanded_rise' if change > 0 else 'expanded_decline'
        elif abs(change) <= 1 and ratio < .5 and len(data) >= 3 and data.Close.iloc[-2] < data.Close.iloc[-3]:
            pattern = 'contracted_stable'
        elif ratio < 1 and change != 0:
            pattern = 'contracted_rise' if change > 0 else 'contracted_decline'
    labels = {'unavailable': '日量价缺数据', 'ordinary': '未触及特定量价条件', 'volume_surge': '巨量急涨',
              'expanded_rise': '放量上涨', 'expanded_decline': '放量下跌',
              'expanded_stall': '放量滞涨或横盘', 'contracted_stable': '前日下跌后缩量企稳候选',
              'contracted_rise': '缩量上涨', 'contracted_decline': '缩量下跌'}
    detail = f'收盘涨跌 {_fmt(change, "%")}，{labels[pattern]}。'
    recovered, late = None, None
    if session:
        opening, close, tail = (session[k] for k in ('opening_low_pct', 'close_from_open_pct', 'last_bar_pct'))
        recovered, late = opening <= -3 and close >= 0, tail >= 3
        detail += f' 首小时低点较开盘 {_fmt(opening, "%")}，首根开盘至末根收盘 {_fmt(close, "%")}，尾段涨跌 {_fmt(tail, "%")}。'
        if recovered:
            detail += ' 早盘急跌后收复开盘价。'
        if late:
            detail += ' 尾段急涨。'
    else:
        detail += ' 缺少当日完整分时，早盘与尾段节奏待核。'
    return _check('unavailable' if pattern == 'unavailable' and session is None else 'observed', detail,
                  change_pct=change, daily_pattern=pattern, session=session,
                  opening_drop_recovered=recovered, late_surge=late)


def _stress(sample):
    if not sample:
        return _check('unavailable', '需盘中同一时点的涨跌家数、标的与指数涨跌幅。')
    total = sample['advancers'] + sample['decliners']
    share = sample['advancers'] / total * 100 if total else None
    spread = sample['ticker_change_pct'] - sample['index_change_pct']
    status = 'unavailable' if share is None else 'met' if share <= 20 and spread > 0 else 'not_met'
    detail = (f"{sample['time']} 上涨 {sample['advancers']} 家、下跌 {sample['decliners']} 家，"
              f"上涨占比 {_fmt(share, '%')}，个股相对指数 {spread:+.2f} 个百分点。")
    if status == 'met':
        detail += ' 该采样点广度偏弱，个股相对抗跌。'
    return _check(status, detail, **sample, advancing_pct=share, relative_points=spread)


def _sector(sector):
    if not sector:
        return _check('unavailable', '需同日板块排名、连续两日涨跌及有来源的资金方向。消息催化可对照新闻事实附录。')
    flow = sector.get('flow_direction')
    flow_label = {'in': '净流入', 'flat': '持平', 'out': '净流出', None: '未知'}[flow]
    leading = sector['rank'] / sector['count'] <= .2
    sustained = sector['change_pct'] > 0 and sector['previous_change_pct'] > 0
    status = 'not_met' if not leading or not sustained or flow in ('flat', 'out') else 'met' if flow == 'in' else 'unavailable'
    detail = (f"{sector['name']} 排名 {sector['rank']}/{sector['count']}，前日 {sector['previous_change_pct']:+.2f}%，"
              f"当日 {sector['change_pct']:+.2f}%，来源记录的板块资金方向为{flow_label}。")
    return _check(status, detail, **sector, leading=leading, two_positive_days=sustained)


def _turnover(change, ratio, turnover, source):
    detail = f'涨跌 {_fmt(change, "%")}，日量比 {_fmt(ratio)}，换手率 {_fmt(turnover, "%")}。'
    if turnover is None:
        detail += ' 缺少同日换手率。'
    tests = (change > 5 if change is not None else None,
             ratio > 1 if ratio is not None else None,
             5 <= turnover <= 30 if turnover is not None else None)
    status = 'not_met' if False in tests else 'unavailable' if None in tests else 'met'
    return _check(status, detail, change_pct=change, volume_ratio_5=ratio, turnover_pct=turnover, source=source)


def _volume_candles(data):
    last = len(data) - 1
    stage, day, floor = 'none', None, None
    for i in range(last, max(0, last - 3), -1):
        bar, previous = data.iloc[i], data.iloc[i - 1]
        if bar.Close <= bar.Open or bar.Close <= previous.Close * 1.05:
            continue
        if not (bar.Volume > 0 and previous.Volume > 0):
            stage = 'insufficient'
            break
        if bar.Volume < 2 * previous.Volume:
            continue
        day, floor, stage = _day(data, i), float(bar.Low), 'impulse'
        if i == last:
            break
        second = data.iloc[i + 1]
        if second.Low < floor:
            stage = 'invalidated'
        elif second.Close >= second.Open:
            stage = 'no_contraction'
        elif not second.Volume > 0:
            stage = 'insufficient'
        elif second.Volume > bar.Volume / 2:
            stage = 'no_contraction'
        elif i + 1 == last:
            stage = 'contraction'
        elif data.Low.iloc[-1] < floor:
            stage = 'invalidated'
        elif abs(data.Close.iloc[-1] - data.Open.iloc[-1]) <= data.Open.iloc[-1] * .02:
            stage = 'confirmed'
        else:
            stage = 'no_small_body'
        break
    if stage == 'none' and len(data) < 4:
        stage = 'insufficient'
    labels = {'none': '近三根未见合格起始阳线', 'impulse': '倍量阳线，待下一根缩量阴线',
              'contraction': '缩量阴线守住低点，待小实体整理', 'confirmed': '三根顺序、量能与低点均符合',
              'invalidated': '回调跌破起始阳线低点', 'no_contraction': '次日未形成合格缩量阴线',
              'no_small_body': '第三日未形成小实体', 'insufficient': '样本或成交量不足'}
    status = {'confirmed': 'met', 'invalidated': 'review', 'impulse': 'watch', 'contraction': 'watch',
              'insufficient': 'unavailable'}.get(stage, 'not_met')
    return _check(status, labels[stage] + (f'。起始日 {day}，低点 {_fmt(floor)}。' if day else '。'),
                  stage=stage, impulse_date=day, impulse_low=floor)


def _limit(market, facts, ratio):
    state, streak = facts.get('limit_state'), facts.get('prior_limit_up_days')
    if market != 'cn' or state == 'no_limit':
        return _check('not_applicable', '此项只覆盖当日适用涨停制度的 A 股标的。', stage='not_applicable')
    if state == 'untouched':
        return _check('not_met', '当日未触及已公布的涨停价。', stage='untouched',
                      limit_state=state, prior_limit_up_days=streak)
    if state == 'touched_unsealed':
        return _check('unavailable', '日高触及涨停价而收盘低于该价，是否曾经封住需要分时板态记录。', stage='seal_unknown',
                      limit_state=state, prior_limit_up_days=streak)
    if not state or streak is None:
        label = {'closed': '收在涨停价。', 'opened': '已记录炸板。'}.get(state, '')
        return _check('unavailable', label + '需当日板态和截至前一日的连板数。', stage='missing',
                      limit_state=state, prior_limit_up_days=streak)
    if streak < 2:
        status, stage, note = 'not_met', 'none', '未形成连板后的封板或炸板组合'
    elif ratio is None:
        status, stage, note = 'unavailable', 'missing_volume', '量比缺失'
    elif state == 'opened' and ratio > 1.5:
        status, stage, note = 'met', 'opened_expansion', '炸板放量，出现分歧候选'
    elif state == 'closed' and ratio < 1:
        status, stage, note = 'met', 'sealed_contraction', '缩量封板，出现一致性候选'
    else:
        status, stage, note = 'not_met', 'none', '板态与量能组合未满足'
    return _check(status, f'此前连板 {streak} 日，日量比 {_fmt(ratio)}，{note}。',
                  stage=stage, limit_state=state, prior_limit_up_days=streak, volume_ratio_5=ratio)


def assess(data, ticker, account, context=None, session=None):
    """Use the existing observation frame; emit facts and reasons in source-principle order."""
    as_of = _day(data, -1)
    market = classify_market(ticker)
    facts, context_status = _context(context, as_of, market)
    quote = data.attrs.get('closing_quote', {})
    if quote.get('as_of') != as_of or quote.get('ticker') != ticker:
        quote = {}
    turnover_source = facts.get('source') if 'turnover_pct' in facts else quote.get('source')
    facts = {**quote, **facts}
    positions = None
    held = None
    if account['status'] == 'known':
        positions = [p for p in account['positions'] if p['gross_pct'] > 0]
        held = next((p for p in positions if p['ticker'] == ticker), None)
    # MA/channel columns are already warm. Only the short, recent event windows are scanned here.
    data = data.tail(26)
    volumes = data.Volume.where(data.Volume > 0)
    ratios = volumes / volumes.shift().rolling(5).mean()
    ratio = _number(ratios.iloc[-1])
    change = None if len(data) < 2 else float((data.Close.iloc[-1] - data.Close.iloc[-2]) / data.Close.iloc[-2] * 100)
    if session is None and 'session' in facts and market != 'crypto':
        session = {**facts['session'], 'source': facts['source']}
    checks = {
        'profit_discipline': _discipline(held, account['status']),
        'volume_setup': _volume_setup(data, ratios, facts, market),
        'portfolio_focus': _portfolio(positions, held, data.iloc[-1]),
        'price_volume': _price_volume(data, change, ratio, session),
        'ma_trend': _ma_trend(data, ratio),
        'market_stress': _stress(facts.get('stress')),
        'sector_theme': _sector(facts.get('sector')),
        'turnover': _turnover(change, ratio, facts.get('turnover_pct'), turnover_source if 'turnover_pct' in facts else None),
        'volume_candles': _volume_candles(data),
        'limit_disagreement': _limit(market, facts, ratio),
    }
    return {'version': VERSION, 'as_of': as_of, 'scope': 'observation_only', 'validation_status': 'UNVALIDATED',
            'context_status': context_status, 'context_as_of': (context or {}).get('as_of'),
            'context_source': (context or {}).get('source'), 'provider_quote': quote or None, 'checks': checks}


def format_principles(result, markdown_label):
    if not result:
        return []
    lines = ['', '### 交易理念核对', '',
             f"截至 {result['as_of']} 收盘。日量比取当日成交量除以前五个交易日均量。下列十项用于复核。"]
    if result.get('provider_quote'):
        lines.append('腾讯同日收盘快照提供可用的换手率和涨停价记录。')
    if result['context_status'] != 'missing':
        state = {'matched': '与行情同日', 'stale': '早于行情日，未采用', 'future': '晚于行情日，未采用'}
        lines.append(f"补充资料来自 {markdown_label(result['context_source'])}（{result['context_as_of']}，"
                     f"{state[result['context_status']]}）。")
    lines.append('')
    for key, item in result['checks'].items():
        lines.append(f"- **{TITLES[key]}** · {STATUS[item['status']]}。{markdown_label(item['detail'])}")
    return lines
