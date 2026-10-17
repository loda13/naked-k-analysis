"""Read-only evidence beside the daily dual-MA plan; never generates orders."""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

from naked_k_portfolio import classify_market, market_timezone_name
from naked_k_trend import MIN_HISTORY, MA_PERIODS, indicator_frame
from naked_k_zones import detect_price_zones, validate_ohlcv
from westock_wrapper import adjustments_comparable

VERSION = 'dual-ma-verification-v1'
RATIOS = (0., .236, .382, .5, .618, .786, 1.)
LABELS = {'weekly': '周线', 'daily': '日线', 'four_hour': '4小时', 'hourly': '1小时'}
DIRECTIONS = {'up': '六线上方', 'down': '六线下方', 'transition': '六线之间', 'unknown': '数据不足'}


def _clock(ticker, now):
    zone = market_timezone_name(classify_market(ticker))
    stamp = pd.Timestamp(now)
    return stamp.tz_localize(zone) if stamp.tzinfo is None else stamp.tz_convert(zone)


def _local_index(frame, ticker, hourly=False):
    zone = market_timezone_name(classify_market(ticker))
    index = pd.DatetimeIndex(frame.index)
    if index.tz is None:
        utc = hourly or (frame.attrs.get('source') == 'yahoo_chart' and not frame.attrs.get('week_ending'))
        index = index.tz_localize('UTC' if utc else zone)
    return index.tz_convert(zone)


def _session(day, market):
    opening, closing = {'us': (570, 960), 'hk': (570, 960), 'cn': (570, 900),
                        'kr': (540, 930), 'crypto': (0, 1440)}[market]
    return day + pd.Timedelta(minutes=opening), day + pd.Timedelta(minutes=closing)


def prepare_weekly(frame, ticker, now):
    data = validate_ohlcv(frame)
    local = _local_index(data, ticker)
    market = classify_market(ticker)
    periods = local.tz_localize(None).to_period('W-SUN' if market == 'crypto' else 'W-FRI')
    labels = periods.end_time.normalize()
    clock = _clock(ticker, now)
    closes = [(_session(day.tz_localize(clock.tz), market)[1]) for day in labels]
    data = data.loc[[end <= clock for end in closes]].copy()
    data.index = labels[[end <= clock for end in closes]]
    # Yahoo appends a daily quote to the weekly series; never sum it twice.
    duplicates = int(data.index.duplicated(keep='first').sum())
    data = data.loc[~data.index.duplicated(keep='first')].copy()
    data.attrs.update(week_ending=True, duplicate_week_rows_removed=duplicates or frame.attrs.get('duplicate_week_rows_removed', 0))
    return data


def _empty(frame, reason):
    data = frame.iloc[:0].copy()
    data.attrs.update(verification_status='unavailable', verification_reason=reason)
    return data


def prepare_intraday(frame, ticker, now):
    data = validate_ohlcv(frame)
    if data.attrs.get('source') not in {'yahoo_chart', 'yfinance'}:
        raise ValueError('该小时源的K线起止时间定义尚未核验')
    market, clock = classify_market(ticker), _clock(ticker, now)
    data.index = _local_index(data, ticker, hourly=True)
    keep = []
    for stamp, row in data.iterrows():
        start, end = _session(stamp.normalize(), market)
        flat_quote = row.Volume == 0 and row.Open == row.High == row.Low == row.Close
        keep.append(start <= stamp < end and min(stamp + pd.Timedelta(hours=1), end) <= clock and not flat_quote)
    data = data.loc[keep].copy()
    if data.empty:
        return _empty(data, '没有完整小时K线'), _empty(data, '没有完整小时K线可供聚合')
    if market == 'cn':
        data.attrs.update(verification_status='partial_session', verification_reason='午休小时格线尚未核验')
        return data, _empty(data, '午休小时格线尚未核验，暂不合成4小时')

    groups = list(data.groupby(data.index.normalize()))
    completed = [(day, group) for day, group in groups if _session(day, market)[1] <= clock]
    missing_tail = False
    if completed:
        day, group = completed[-1]
        start, end = _session(day, market)
        expected = pd.date_range(start, end, freq='h', inclusive='left')
        missing_tail = not expected.equals(group.index)
    data.attrs.update(verification_status='partial_session' if missing_tail else 'ready',
                      verification_reason='最近完整交易日缺尾盘或中间小时，不能假定完整时段' if missing_tail else '')
    if missing_tail:
        return data, _empty(data, '最近交易日缺尾盘或中间小时，不能合成完整4小时序列')

    rows, dates, missing = [], [], 0
    for day, group in groups:
        opening, closing = _session(day, market)
        for start in pd.date_range(opening, closing, freq='4h', inclusive='left'):
            end = min(start + pd.Timedelta(hours=4), closing)
            if end > clock:
                continue
            expected = pd.date_range(start, end, freq='h', inclusive='left')
            chunk = group.loc[(group.index >= start) & (group.index < end)]
            if not expected.equals(chunk.index):
                missing += 1
                continue
            rows.append({'Open': chunk.Open.iloc[0], 'High': chunk.High.max(), 'Low': chunk.Low.min(),
                         'Close': chunk.Close.iloc[-1], 'Volume': chunk.Volume.sum(min_count=1)})
            dates.append(start)
    four = pd.DataFrame(rows, index=pd.DatetimeIndex(dates), columns=data.columns)
    four.attrs.update(data.attrs, aggregation='session_open_4_clock_hours_with_short_tail', incomplete_windows_removed=missing)
    if four.empty:
        four = _empty(four, '没有完整4小时窗口')
    return data, four


def major_retracement(frame, reference_price):
    data = validate_ohlcv(frame)
    if not math.isfinite(reference_price) or reference_price <= 0:
        raise ValueError('回撤参考价必须是有限正数')
    unavailable = {'status': 'unavailable', 'reason': '没有可核验的先低后高上涨段'}
    if len(data) < 2:
        return unavailable
    hi = int(data.index.get_loc(data.High.idxmax()))
    if hi == 0:
        return unavailable
    lo = int(data.index.get_loc(data.iloc[:hi].Low.idxmin()))
    low, high = float(data.Low.iloc[lo]), float(data.High.iloc[hi])
    if high <= low or data.iloc[lo:hi + 1].Low.min() < low:
        return unavailable
    levels = [{'ratio': ratio, 'price': high - ratio * (high - low), 'nearby_references': []} for ratio in RATIOS]
    for point in levels:
        point['side'] = 'support_reference' if point['price'] < reference_price else 'resistance_reference' if point['price'] > reference_price else 'at_price'
    confirmed = lo >= 2 and hi + 2 < len(data) and (data.Low.iloc[lo + 1:lo + 3] > low).all() and (data.High.iloc[hi + 1:hi + 3] < high).all()
    lowest_after_high = float(data.Low.iloc[hi:].min())
    origin_status = ('below_origin' if reference_price < low else 'above_anchor_high' if reference_price > high
                     else 'reclaimed_after_break' if lowest_after_high < low else 'within_leg')
    return {'status': 'ready', 'selection': 'visible_weekly_max_high_and_lowest_preceding_low',
            'anchor_status': 'confirmed_candidate' if confirmed else 'provisional_candidate',
            'low_at': data.index[lo].isoformat(), 'low': low, 'high_at': data.index[hi].isoformat(), 'high': high,
            'sample_start': data.index[0].isoformat(), 'sample_end': data.index[-1].isoformat(),
            'reference_price': float(reference_price), 'retracement_pct': (high - reference_price) / (high - low) * 100,
            'drawdown_from_high_pct': (high - reference_price) / high * 100,
            'origin_status': origin_status, 'lowest_after_high': lowest_after_high, 'levels': levels,
            'nearest_support': max((p for p in levels if p['price'] < reference_price), key=lambda p: p['price'], default=None),
            'nearest_resistance': min((p for p in levels if p['price'] > reference_price), key=lambda p: p['price'], default=None),
            'checks': {'low_precedes_high': True, 'leg_extremes_checked': True, 'available_history_only': True}}


def _snapshot(frame):
    if frame is None or frame.empty:
        return {'status': 'unavailable', 'reason': (frame.attrs.get('verification_reason') if frame is not None else None) or '未取得该周期数据'}
    data = validate_ohlcv(frame)
    row = indicator_frame(data).iloc[-1]
    bands = {}
    for period in MA_PERIODS:
        values = (row[f'ma{period}'], row[f'ema{period}'])
        bands[str(period)] = {'lower': float(min(values)), 'upper': float(max(values))} if all(pd.notna(x) for x in values) else None
    complete = len(data) >= MIN_HISTORY
    direction, order = 'unknown', '数据不足'
    if complete:
        values = list(bands.values())
        direction = 'up' if row.Close > max(b['upper'] for b in values) else 'down' if row.Close < min(b['lower'] for b in values) else 'transition'
        order = '多头排列' if all(values[i]['lower'] > values[i + 1]['upper'] for i in (0, 1)) else '空头排列' if all(values[i]['upper'] < values[i + 1]['lower'] for i in (0, 1)) else '交错'
    points = detect_price_zones(data.tail(240))['zones']
    low = next((p for p in reversed(points) if p['kind'] == 'support'), None)
    return {'status': data.attrs.get('verification_status', 'ready') if complete else 'insufficient',
            'reason': data.attrs.get('verification_reason', '') if complete else '不足120根完整K线，六线不可比较',
            'rows': len(data), 'as_of': data.index[-1].isoformat(), 'close': float(row.Close), 'direction': direction,
            'ma_order': order, 'bands': bands, 'last_confirmed_low': low,
            'source': str(data.attrs.get('source', 'unknown')), 'adjustment': str(data.attrs.get('adjustment', 'unknown')),
            'incomplete_windows_removed': int(data.attrs.get('incomplete_windows_removed', 0)),
            'duplicate_week_rows_removed': int(data.attrs.get('duplicate_week_rows_removed', 0))}


def build_verification(ticker, daily, weekly, hourly, trend, now):
    limits, frames = [], {'weekly': None, 'daily': daily, 'four_hour': None, 'hourly': None}
    if weekly is not None:
        try:
            frames['weekly'] = prepare_weekly(weekly, ticker, now)
        except ValueError:
            limits.append('周线数据校验失败，未用于交叉验证')
    if hourly is not None:
        try:
            frames['hourly'], frames['four_hour'] = prepare_intraday(hourly, ticker, now)
        except ValueError as exc:
            limits.append(str(exc))
    snapshots = {key: _snapshot(frame) for key, frame in frames.items()}
    baseline = snapshots['daily']
    supporting, conflicting = [], []
    if baseline['status'] != 'ready' or trend['direction'] == 'unknown':
        limits.append('日线主线数据不足，不能验证其他周期与主线的方向关系')
    for key, item in snapshots.items():
        known_basis = item.get('adjustment', 'unknown') != 'unknown' and baseline.get('adjustment', 'unknown') != 'unknown'
        item['comparable_to_daily'] = bool(known_basis and adjustments_comparable(baseline.get('adjustment'), item.get('adjustment'), baseline.get('source'), item.get('source')))
        if key == 'weekly' and item.get('as_of', '')[:10] == baseline.get('as_of', '')[:10] and not math.isclose(item['close'], baseline['close'], rel_tol=1e-6):
            item['comparable_to_daily'] = False
            limits.append('周线与日线同一日期收盘不一致，不能直接叠加价位，需要核对行情源')
        item['relation_to_daily'] = 'unavailable'
        if item.get('as_of') and key in {'hourly', 'four_hour'}:
            if pd.Timestamp(item['as_of']).date() < pd.Timestamp(baseline['as_of']).date():
                item.update(status='stale', reason='小时行情日期落后于已收盘日线，不能验证当前状态')
        if key == 'daily':
            continue
        if item.get('incomplete_windows_removed'):
            limits.append(f"{LABELS[key]}剔除了{item['incomplete_windows_removed']}个不完整历史窗口，均线存在缺口影响")
        if item['status'] != 'ready':
            limits.append(f"{LABELS[key]}数据不足：{item.get('reason') or item['status']}")
        elif not item['comparable_to_daily']:
            limits.append(f"{LABELS[key]}复权口径未知或与日线不一致，不叠加价位或方向结论")
        elif baseline['status'] != 'ready' or trend['direction'] == 'unknown':
            continue
        elif trend['direction'] in {'up', 'down'} and item['direction'] == trend['direction']:
            item['relation_to_daily'] = 'supporting'
            supporting.append(f"{LABELS[key]}价格也在{DIRECTIONS[item['direction']]}，与日线方向一致")
        elif {trend['direction'], item['direction']} == {'up', 'down'}:
            item['relation_to_daily'] = 'conflicting'
            conflicting.append(f"{LABELS[key]}价格在{DIRECTIONS[item['direction']]}，与日线方向相反")
        elif trend['direction'] == item['direction'] == 'transition':
            item['relation_to_daily'] = 'indeterminate'
            limits.append(f"{LABELS[key]}与日线均处于六线之间，方向尚未明确")
        else:
            item['relation_to_daily'] = 'different_phase'
            conflicting.append(f"{LABELS[key]}为{DIRECTIONS[item['direction']]}，与日线处于不同阶段")
    w = frames['weekly']
    comparable = snapshots['weekly']['comparable_to_daily']
    reference = float(daily.Close.iloc[-1]) if comparable else float(w.Close.iloc[-1]) if w is not None and not w.empty else 0.
    fib = major_retracement(w, reference) if w is not None and not w.empty else {'status': 'unavailable', 'reason': '缺少已收盘周线'}
    if fib['status'] == 'ready':
        if fib['anchor_status'] == 'provisional_candidate':
            limits.append('上涨波段锚点尚未确认，回撤比例只能作为暂定位置')
        fib['reference_basis'] = 'daily_close' if comparable else 'weekly_close_only'
        fib['reference_as_of'] = baseline['as_of'] if comparable else snapshots['weekly']['as_of']
        if comparable:
            for point in fib['levels']:
                price = point['price']
                for key, item in snapshots.items():
                    if item['status'] != 'ready' or not item['comparable_to_daily']:
                        continue
                    for period, band in item['bands'].items():
                        distance = max(band['lower'] - price, price - band['upper'], 0.) / price
                        if distance <= .01:
                            point['nearby_references'].append(f"{LABELS[key]}{period}带 {band['lower']:.2f}–{band['upper']:.2f}")
                nearby = [z for z in trend.get('zones', {}).get('zones', [])
                          if max(z['lower'] - price, price - z['upper'], 0.) / price <= .01]
                for zone in nearby[-2:]:
                    point['nearby_references'].append(f"历史水平区 {zone['lower']:.2f}–{zone['upper']:.2f}（{zone['swing_date']}）")
    else:
        limits.append('大波段回撤无法验证：' + fib['reason'])
    status = 'mixed' if conflicting else 'consistent' if len(supporting) == 3 and not limits else 'partial'
    return {'version': VERSION, 'status': status, 'supporting': supporting, 'conflicting': conflicting,
            'limitations': limits, 'timeframes': snapshots, 'major_retracement': fib,
            'scope': 'observation_only_no_signal_or_budget_effect', 'external_quote_check': 'not_performed_by_cli'}


def format_verification(result: dict[str, Any]) -> list[str]:
    if not result:
        return []
    lines = ['', '### 交叉验证（双均线主线不变）',
             '',
             '- 回撤、起涨点及其他周期用于核对位置和分歧，不投票修改日线开仓、止损或仓位。']
    for key, label in [('supporting', '支持证据'), ('conflicting', '冲突或周期差异'), ('limitations', '数据限制')]:
        for item in result.get(key, []):
            lines.append(f'- {label}：{item}')
    lines += ['', '| 周期 | 最后K线标签 | 价格与六线 | 20带 | 60带 | 120带 |', '|---|---|---|---|---|---|']
    for key, item in result.get('timeframes', {}).items():
        if 'bands' not in item:
            lines.append(f"| {LABELS[key]} | — | 数据不足 | — | — | — |")
            continue
        bands = [f"{b['lower']:.2f}–{b['upper']:.2f}" if b else '不可计算' for b in item['bands'].values()]
        lines.append(f"| {LABELS[key]} | {item['as_of']} | {item['close']:.2f}；{DIRECTIONS[item['direction']]} / {item['ma_order']}；{item['status']} | " + ' | '.join(bands) + ' |')
    lines.append('')
    for key, item in result.get('timeframes', {}).items():
        low = item.get('last_confirmed_low')
        if low:
            lines.append(f"- {LABELS[key]}最近已确认局部低点：{low['lower']:.2f}（{low['swing_date']}，{low['confirmed_at']}后才可知）；不自动等同新起涨点。")
    fib = result.get('major_retracement', {})
    if fib.get('status') != 'ready':
        lines.append('- 大波段回撤数据不足：' + fib.get('reason', '未取得有效锚点'))
    else:
        lines += ['', '#### 大波段回撤与水平位置核对',
                  '',
                  f"- 上涨候选：{fib['low_at'][:10]} {fib['low']:.2f} → {fib['high_at'][:10]} {fib['high']:.2f}；日期为周结束标签。",
                  '- 选点规则：可见周线样本最高点及此前最低点；这是程序候选，需要复核是否对应所讨论的上一轮上涨，不声称作者会选同一波段。',
                  '- 端点检查：' + ('两根后续周K已提供局部极值观察。' if fib['anchor_status'] == 'confirmed_candidate' else '端点处于样本边界或缺两根后续周K，锚点待确认。'),
                  f"- 参考价 {fib['reference_price']:.2f}（{fib['reference_as_of']}，{'日线收盘' if fib['reference_basis'] == 'daily_close' else '仅周线自身收盘，不与日线混算'}）；回吐本段涨幅 {fib['retracement_pct']:.2f}%；相对高点下跌 {fib['drawdown_from_high_pct']:.2f}%。",
                  '- 公式：（高点−参考价）÷（高点−起涨点）。回撤比例描述位置，不单独证明支撑或趋势反转。']
        if fib['origin_status'] != 'within_leg':
            lines.append('- 原波段状态：' + {'below_origin': '已跌破原起涨点，不能继续称原上涨守住。',
                         'reclaimed_after_break': '曾跌破起涨点后收回，不能表述为原上涨始终守住。',
                         'above_anchor_high': '已越过原高点，原回撤图不再描述当前回调。'}[fib['origin_status']])
        lines += ['', '| 回撤比例 | 价位 | 相对参考价 | 邻近参照 |', '|---|---:|---|---|']
        for point in fib['levels']:
            side = {'support_reference': '下方观察', 'resistance_reference': '上方观察', 'at_price': '当前所在'}[point['side']]
            lines.append(f"| {point['ratio']:g} | {point['price']:.2f} | {side} | {'；'.join(point['nearby_references']) or '无'} |")
        lines += ['', '- 邻近表示距离不超过回撤价的1%，是展示口径；端点两根确认也是工程定义，均非作者公布的精确交易参数。']
    for key, item in result.get('timeframes', {}).items():
        if item.get('incomplete_windows_removed'):
            lines.append(f"- {LABELS[key]}已剔除{item['incomplete_windows_removed']}个不完整历史窗口，均线可能与完整平台历史不同。")
        if item.get('duplicate_week_rows_removed'):
            lines.append(f"- 已移除{item['duplicate_week_rows_removed']}条同周重复报价，未重复计入周线。")
    lines += ['- 股票4小时按交易所当地开盘起每4小时聚合，尾盘可较短，不跨夜；未接入完整半日市日历。',
              '- 程序复核价格结构、锚点先后、计算及时间口径；不等于独立行情源复核或策略收益验证。',
              '- 来源：[起涨点与回撤](https://www.youtube.com/watch?v=kH7GOeas17A&t=41s)；[多周期观察](https://www.youtube.com/watch?v=h1wIpEPXx-A&t=534s)。']
    return lines
