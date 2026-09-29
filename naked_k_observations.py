"""Text-only, causal observations. These never vote on the v2 trade plan."""
from __future__ import annotations

import math
from collections import Counter
from typing import Any

import numpy as np
import pandas as pd

from naked_k_trend import _number, _smooth, indicator_frame
from naked_k_zones import detect_price_zones

OBSERVATION_VERSION = 'technical-observations-v1'
PATTERN_WINDOW = 120
RECENT_BARS = 5
PATTERN_MAX_AGE = 20


def _sar(frame: pd.DataFrame) -> pd.Series:
    result = pd.Series(np.nan, index=frame.index)
    if len(frame) < 2:
        return result
    rising = frame.Close.iloc[1] >= frame.Close.iloc[0]
    value = frame.Low.iloc[0] if rising else frame.High.iloc[0]
    extreme = frame.High.iloc[:2].max() if rising else frame.Low.iloc[:2].min()
    acceleration = .02
    result.iloc[1] = value
    for i in range(2, len(frame)):
        high, low = frame.High.iloc[i], frame.Low.iloc[i]
        projected = value + acceleration * (extreme - value)
        projected = min(projected, frame.Low.iloc[i - 2:i].min()) if rising else max(projected, frame.High.iloc[i - 2:i].max())
        if (rising and low < projected) or (not rising and high > projected):
            value, rising = extreme, not rising
            extreme, acceleration = (high if rising else low), .02
        else:
            value = projected
            if (rising and high > extreme) or (not rising and low < extreme):
                extreme, acceleration = (high if rising else low), min(.2, acceleration + .02)
        result.iloc[i] = value
    return result


def observation_frame(frame: pd.DataFrame) -> pd.DataFrame:
    data = indicator_frame(frame)
    close, high, low, volume = data.Close, data.High, data.Low, data.Volume
    for period in (3, 5, 6, 10, 12, 20, 24, 60, 120, 250):
        data[f'sma{period}'] = close.rolling(period).mean()
    data['bbi'] = data[['sma3', 'sma6', 'sma12', 'sma24']].mean(axis=1, skipna=False)
    data['sar'] = _sar(data)
    data['aroon_up'] = high.rolling(26).apply(lambda x: 100 * (25 - np.argmax(x[::-1])) / 25, raw=True)
    data['aroon_down'] = low.rolling(26).apply(lambda x: 100 * (25 - np.argmin(x[::-1])) / 25, raw=True)
    smoothed = close
    for _ in range(3):
        smoothed = _smooth(smoothed.dropna(), 15, 2 / 16).reindex(data.index)
    data['trix'] = (smoothed / smoothed.shift() - 1) * 100
    data['trix_signal'] = data.trix.rolling(9).mean()
    data['macd'] = _smooth(close, 12, 2 / 13) - _smooth(close, 26, 2 / 27)
    data['macd_signal'] = _smooth(data.macd.dropna(), 9, 2 / 10).reindex(data.index)
    data['macd_hist'] = 2 * (data.macd - data.macd_signal)
    change = close.diff()
    for period in (6, 12, 14, 24):
        gains = _smooth(change.iloc[1:].clip(lower=0), period, 1 / period)
        losses = _smooth(-change.iloc[1:].clip(upper=0), period, 1 / period)
        total = gains + losses
        data[f'rsi{period}'] = (100 * gains / total).mask(total == 0, 50)
    for period in (6, 12, 24):
        data[f'bias{period}'] = (close / data[f'sma{period}'] - 1) * 100
    range9 = high.rolling(9).max() - low.rolling(9).min()
    rsv = 100 * (close - low.rolling(9).min()) / range9.replace(0, np.nan)
    k, d, ks, ds = 50., 50., [], []
    for value in rsv:
        if pd.isna(value):
            ks.append(np.nan)
            ds.append(np.nan)
            k = d = 50.
        else:
            k = (2 * k + value) / 3
            d = (2 * d + k) / 3
            ks.append(k)
            ds.append(d)
    data['kdj_k'], data['kdj_d'] = ks, ds
    data['kdj_j'] = 3 * data.kdj_k - 2 * data.kdj_d
    range14 = high.rolling(14).max() - low.rolling(14).min()
    raw_k = 100 * (close - low.rolling(14).min()) / range14.replace(0, np.nan)
    data['stoch_k'] = raw_k.rolling(3).mean()
    data['stoch_d'] = data.stoch_k.rolling(3).mean()
    data['williams_r14'] = raw_k - 100
    data['roc12'], data['momentum10'] = (close / close.shift(12) - 1) * 100, close - close.shift(10)
    typical = (high + low + close) / 3
    deviation = typical.rolling(20).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    data['cci20'] = (typical - typical.rolling(20).mean()) / (.015 * deviation.replace(0, np.nan))
    sigma = close.rolling(20).std(ddof=0)
    data['boll_upper'], data['boll_lower'] = data.sma20 + 2 * sigma, data.sma20 - 2 * sigma
    data['boll_width_pct'] = 4 * sigma / data.sma20 * 100
    data['boll_percent_b'] = (close - data.boll_lower) / (4 * sigma).replace(0, np.nan)
    data['keltner_upper'], data['keltner_lower'] = data.ema20 + 2 * data.atr, data.ema20 - 2 * data.atr
    data['hv20_pct'] = np.log(close / close.shift()).rolling(20).std(ddof=1) * math.sqrt(252) * 100
    for period in (20, 55):
        data[f'donchian_high{period}'] = high.shift().rolling(period).max()
        data[f'donchian_low{period}'] = low.shift().rolling(period).min()
    up, down = high.diff(), -low.diff()
    plus = pd.Series(np.where((up > down) & (up > 0), up, 0.), index=data.index)
    minus = pd.Series(np.where((down > up) & (down > 0), down, 0.), index=data.index)
    data['di_plus'] = (100 * _smooth(plus, 14, 1 / 14) / data.atr).mask(data.atr == 0, 0)
    data['di_minus'] = (100 * _smooth(minus, 14, 1 / 14) / data.atr).mask(data.atr == 0, 0)
    data['adxr'] = (data.adx + data.adx.shift(14)) / 2
    data['volume_ma5'], data['volume_ma20'] = volume.rolling(5).mean(), volume.rolling(20).mean()
    signed_volume = np.sign(change.fillna(0)) * volume
    data['obv'] = signed_volume.cumsum(skipna=False)
    spread = high - low
    multiplier = ((2 * close - high - low) / spread).mask(spread == 0, 0)
    money_volume = multiplier * volume
    data['adl'] = money_volume.cumsum(skipna=False)
    volume20 = volume.rolling(20).sum().replace(0, np.nan)
    data['cmf20'] = money_volume.rolling(20).sum() / volume20
    data['vwma20'] = (close * volume).rolling(20).sum() / volume20
    movement = typical.diff()
    positive = (typical * volume).where(movement > 0, 0).mask(volume.isna() | movement.isna())
    negative = (typical * volume).where(movement < 0, 0).mask(volume.isna() | movement.isna())
    positive, negative = positive.rolling(14).sum(), negative.rolling(14).sum()
    data['mfi14'] = 100 * positive / (positive + negative).replace(0, np.nan)
    return data


def _date(data: pd.DataFrame, position: int) -> str:
    return pd.Timestamp(data.index[position]).date().isoformat()


def _pattern(data, key, name, side, status, start, detected, event, evidence, trigger=None, invalidation=None):
    return {'id': key, 'name': name, 'side': side, 'status': status, 'start_at': _date(data, start),
            'detected_at': _date(data, detected), 'confirmed_at': _date(data, event) if event is not None else None,
            'as_of': _date(data, -1), 'evidence': evidence,
            'trigger': _number(trigger), 'invalidation': _number(invalidation)}


def _structural_patterns(data: pd.DataFrame, zones: dict) -> list[dict[str, Any]]:
    points = []
    dates = {_date(data, i): i for i in range(len(data))}
    raw = zones.get('zones', [])
    date_counts = Counter(point['swing_date'] for point in raw)
    for point in raw:
        position = dates[point['swing_date']]
        if position < len(data) - PATTERN_WINDOW:
            continue
        # A bar that is both a swing high and low has an unknowable intraday order.
        if date_counts[point['swing_date']] != 1:
            continue
        item = {'pos': position, 'known': dates[point['confirmed_at']], 'kind': point['kind'],
                'price': point['lower'] if point['kind'] == 'support' else point['upper']}
        if points and points[-1]['kind'] == item['kind']:
            more_extreme = item['price'] < points[-1]['price'] if item['kind'] == 'support' else item['price'] > points[-1]['price']
            if more_extreme:
                points[-1] = item
        else:
            points.append(item)
    found = {}
    for size in (3, 5):
        for end in range(size, len(points) + 1):
            p = points[end - size:end]
            bullish = p[0]['kind'] == 'support'
            side, sign = ('bullish', 1) if bullish else ('bearish', -1)
            extrema, necks = p[::2], p[1::2]
            first, last = p[0]['pos'], p[-1]['pos']
            atr = _number(data.atr.iloc[last])
            if atr is None or atr <= 0 or first < 10 or any(b['pos'] - a['pos'] < 3 for a, b in zip(p, p[1:])):
                continue
            if sign * (data.Close.iloc[first - 10] - data.Close.iloc[first]) <= atr:
                continue
            if abs(extrema[0]['price'] - extrema[-1]['price']) > atr:
                continue
            triple = size == 5 and max(x['price'] for x in extrema) - min(x['price'] for x in extrema) <= atr
            if size == 5 and not triple:
                shoulder = min(extrema[0]['price'], extrema[-1]['price']) if bullish else max(extrema[0]['price'], extrema[-1]['price'])
                if sign * (shoulder - extrema[1]['price']) < atr:
                    continue
            level = necks[-1]['price']
            if sign * (level - extrema[-1]['price']) < atr:
                continue
            known = max(x['known'] for x in p)
            slope = (necks[-1]['price'] - necks[0]['price']) / (necks[-1]['pos'] - necks[0]['pos']) if len(necks) == 2 else 0
            invalid = min(x['price'] for x in extrema) if bullish else max(x['price'] for x in extrema)
            confirmed, failed = None, None
            for i in range(known, len(data)):
                neckline = level + slope * (i - necks[-1]['pos'])
                if sign * (data.Close.iloc[i] - invalid) < 0:
                    failed = i
                    break
                if confirmed is None and sign * (data.Close.iloc[i] - neckline) > 0:
                    confirmed = i
            status = 'failed' if failed is not None else 'confirmed' if confirmed is not None else 'pending'
            event = failed if failed is not None else confirmed
            if len(data) - 1 - (event if event is not None else known) > PATTERN_MAX_AGE:
                continue
            key = ('double_bottom' if bullish else 'double_top') if size == 3 else ('head_shoulders_bottom' if bullish else 'head_shoulders_top')
            name = ('双底' if bullish else '双顶') if size == 3 else ('头肩底' if bullish else '头肩顶')
            if triple:
                key, name = ('triple_bottom', '三重底') if bullish else ('triple_top', '三重顶')
            trigger = level + slope * (len(data) - 1 - necks[-1]['pos'])
            evidence = f"已确认拐点 {'、'.join(_date(data, x['pos']) for x in p)}；颈线 {trigger:.2f}；收盘{'上破' if bullish else '下破'}才确认"
            found[key] = _pattern(data, key, name, side, status, first, known, event, evidence, trigger, invalid)
    for kind, direction, sign in [('support', 'bullish', 1), ('resistance', 'bearish', -1)]:
        pivots = [point for point in points if point['kind'] == kind]
        if len(pivots) < 2:
            continue
        first, second = pivots[-2:]
        if len(data) - 1 - second['known'] > RECENT_BARS or second['pos'] - first['pos'] < 5:
            continue
        for key, name in [('rsi14', 'RSI'), ('macd', 'MACD')]:
            a, b = data[key].iloc[first['pos']], data[key].iloc[second['pos']]
            if sign * (second['price'] - first['price']) < 0 and sign * (b - a) > 0:
                identity = f"{name.lower()}_{direction}_divergence"
                found[identity] = _pattern(data, identity, name + ('底背离候选' if sign > 0 else '顶背离候选'), direction,
                    'pending', first['pos'], second['known'], None,
                    f"已确认拐点价格 {first['price']:.2f}→{second['price']:.2f}，{name} {a:.2f}→{b:.2f}；背离不等于反转")
    if len(points) >= 6:
        recent = points[-6:]
        highs = [x for x in recent if x['kind'] == 'resistance']
        lows = [x for x in recent if x['kind'] == 'support']
        first, known = recent[0]['pos'], max(x['known'] for x in recent)
        atr = _number(data.atr.iloc[known])
        if len(highs) == len(lows) == 3 and atr is not None and atr > 0 and len(data) - 1 - known <= PATTERN_MAX_AGE:
            upper = np.polyfit([x['pos'] for x in highs], [x['price'] for x in highs], 1)
            lower = np.polyfit([x['pos'] for x in lows], [x['price'] for x in lows], 1)
            residual = max(abs(np.polyval(line, x['pos']) - x['price']) for line, group in [(upper, highs), (lower, lows)] for x in group)
            span = recent[-1]['pos'] - first
            high_change, low_change = upper[0] * span, lower[0] * span
            width = np.polyval(upper - lower, known)
            key = name = None
            if residual <= .5 * atr and width > atr:
                if high_change < -.3 * atr and low_change > .3 * atr:
                    key, name = 'triangle', '三角收敛'
                elif abs(high_change) <= .3 * atr and low_change > .5 * atr:
                    key, name = 'ascending_triangle', '上升三角'
                elif abs(low_change) <= .3 * atr and high_change < -.5 * atr:
                    key, name = 'descending_triangle', '下降三角'
                elif high_change > .3 * atr and low_change - high_change > .5 * atr:
                    key, name = 'rising_wedge', '上升楔形'
                elif low_change < -.3 * atr and low_change - high_change > .5 * atr:
                    key, name = 'falling_wedge', '下降楔形'
                elif abs(high_change) <= .5 * atr and abs(low_change) <= .5 * atr:
                    key, name = 'box', '箱体整理'
                elif first >= 10 and abs(high_change - low_change) <= .5 * atr:
                    impulse = data.Close.iloc[first] - data.Close.iloc[first - 10]
                    if abs(impulse) >= 3 * atr and impulse * high_change < 0 and max(abs(high_change), abs(low_change)) < .6 * abs(impulse):
                        key, name = ('bull_flag', '上涨后旗形整理') if impulse > 0 else ('bear_flag', '下跌后旗形整理')
            if key:
                event, direction, status = None, 'neutral', 'pending'
                for i in range(known, len(data)):
                    top, bottom = np.polyval(upper, i), np.polyval(lower, i)
                    if top <= bottom:
                        status = 'failed'
                        event = i
                        break
                    if event is None and (data.Close.iloc[i] > top or data.Close.iloc[i] < bottom):
                        event, direction, status = i, 'bullish' if data.Close.iloc[i] > top else 'bearish', 'confirmed'
                    elif event is not None and bottom <= data.Close.iloc[i] <= top:
                        status = 'failed'
                        event = i
                        break
                top, bottom = np.polyval(upper, len(data) - 1), np.polyval(lower, len(data) - 1)
                evidence = f'最近三组确认高低点拟合；上沿 {top:.2f}、下沿 {bottom:.2f}；最大拐点拟合误差不超过0.5ATR，方向以收盘越界为准'
                found[key] = _pattern(data, key, name, direction, status, first, known, event, evidence,
                                      top if direction == 'bullish' else bottom if direction == 'bearish' else None)
    return list(found.values())


def _price_patterns(data: pd.DataFrame) -> list[dict[str, Any]]:
    if len(data) < 2:
        return []
    found, last = {}, len(data) - 1
    row, previous = data.iloc[-1], data.iloc[-2]

    def add(key, name, side, evidence, *, start=None, status='confirmed', trigger=None, invalidation=None):
        found[key] = _pattern(data, key, name, side, status, last if start is None else start,
                              last, last if status != 'pending' else None, evidence, trigger, invalidation)

    for side, sign, column, key, label in [('bullish', 1, 'channel_high', 'up', '向上突破'),
                                         ('bearish', -1, 'channel_low', 'down', '向下破位')]:
        boundary = _number(row[column])
        if boundary is None:
            continue
        if sign * (row.Close - boundary) > 0 and sign * (previous.Close - previous[column]) <= 0:
            add('breakout_' + key, label, side, f'收盘 {row.Close:.2f} 越过之前20日边界 {boundary:.2f}（排除当日）', trigger=boundary)
        extreme = row.High if sign > 0 else row.Low
        if sign * (extreme - boundary) > 0 and sign * (row.Close - boundary) < 0:
            add('sweep_' + key, '冲高回落' if sign > 0 else '探底回收', 'bearish' if sign > 0 else 'bullish',
                f'盘中越过 {boundary:.2f} 后收回原区间；仅为价格行为', trigger=boundary,
                invalidation=row.High if sign > 0 else row.Low)
        for i in range(max(21, last - RECENT_BARS), last):
            level = float(data[column].iloc[i])
            crossed = sign * (data.Close.iloc[i] - level) > 0 and sign * (data.Close.iloc[i - 1] - data[column].iloc[i - 1]) <= 0
            if not crossed:
                continue
            interim = sign * (data.Close.iloc[i + 1:last] - level)
            if sign * (row.Close - level) < 0 and (interim >= 0).all():
                add('false_breakout_' + key, '向上假突破' if sign > 0 else '向下假破位',
                    'bearish' if sign > 0 else 'bullish', f'{_date(data, i)} 收盘越界，今日首次收回 {level:.2f} 内；失败今日才可识别', start=i, trigger=level)
            atr = _number(row.atr)
            touch = row.Low if sign > 0 else row.High
            if atr is not None and abs(touch - level) <= .3 * atr and sign * (row.Close - level) > 0 and (interim >= 0).all():
                add('retest_' + key, '突破回踩守住' if sign > 0 else '破位反抽受阻', side,
                    f'{_date(data, i)} 越界后回测 {level:.2f}，触及距离不超过0.3ATR且收盘仍在突破方向', start=i, trigger=level)

    spread, body = row.High - row.Low, abs(row.Close - row.Open)
    upper, lower = row.High - max(row.Open, row.Close), min(row.Open, row.Close) - row.Low
    rising = len(data) > 10 and previous.Close > data.Close.iloc[-11]
    falling = len(data) > 10 and previous.Close < data.Close.iloc[-11]
    if spread > 0:
        if body <= .1 * spread:
            add('doji', '十字星', 'neutral', '实体不超过振幅10%；方向待后续价格确认', status='pending')
        if lower >= 2 * max(body, .05 * spread) and upper <= .2 * spread and falling:
            add('hammer', '锤头探底候选', 'bullish', '下跌背景、长下影；后续收盘越过本K高点才确认止跌', status='pending', trigger=row.High, invalidation=row.Low)
        if upper >= 2 * max(body, .05 * spread) and lower <= .2 * spread and rising:
            add('shooting_star', '长上影受阻候选', 'bearish', '上涨背景、长上影；后续收盘跌破本K低点才确认转弱', status='pending', trigger=row.Low, invalidation=row.High)
            add('upper_wick_continuation', '仙人指路候选', 'bullish', '同一长上影也可能是延续前整理；须后续收盘越过本K高点，不能识别买方身份', status='pending', trigger=row.High, invalidation=row.Low)
        if row.Close > row.Open and previous.Close < previous.Open and row.Open <= previous.Close and row.Close >= previous.Open and falling:
            add('bullish_engulfing', '看涨吞没', 'bullish', '下跌背景，阳线实体覆盖前根阴线实体；反转仍需后续高点突破', invalidation=row.Low)
        if row.Close < row.Open and previous.Close > previous.Open and row.Open >= previous.Close and row.Close <= previous.Open and rising:
            add('bearish_engulfing', '看跌吞没', 'bearish', '上涨背景，阴线实体覆盖前根阳线实体；继续关注支撑', invalidation=row.High)
    for i in range(max(10, last - RECENT_BARS), last):
        candle = data.iloc[i]
        width, real = candle.High - candle.Low, abs(candle.Close - candle.Open)
        wick = candle.High - max(candle.Open, candle.Close)
        was_rising = data.Close.iloc[i - 1] > data.Close.iloc[i - 10]
        if width > 0 and was_rising and wick >= 2 * max(real, .05 * width) and min(candle.Open, candle.Close) - candle.Low <= .2 * width:
            interval = data.iloc[i + 1:last]
            if row.Close > candle.High and (interval.Close <= candle.High).all() and (data.Close.iloc[i + 1:] >= candle.Low).all():
                add('upper_wick_confirmed', '仙人指路式延续确认', 'bullish', f'项目口径：{_date(data, i)} 长上影后，今日首次收盘越过该K高点；未曾收破低点', start=i, trigger=candle.High, invalidation=candle.Low)
    if len(data) >= 13:
        first, middle = data.iloc[-3], data.iloc[-2]
        small = abs(middle.Close - middle.Open) <= .5 * abs(first.Close - first.Open)
        if small and first.Close < first.Open and row.Close > row.Open and row.Close > (first.Open + first.Close) / 2 and falling:
            add('morning_star', '早晨之星候选', 'bullish', '三K无缺口变体：阴线、小实体、阳线收复首根实体中点；项目口径', status='pending', invalidation=min(first.Low, middle.Low, row.Low))
        if small and first.Close > first.Open and row.Close < row.Open and row.Close < (first.Open + first.Close) / 2 and rising:
            add('evening_star', '黄昏之星候选', 'bearish', '三K无缺口变体：阳线、小实体、阴线跌回首根实体中点；项目口径', status='pending', invalidation=max(first.High, middle.High, row.High))
    if _number(row.relative_volume) is not None and row.relative_volume >= 1.5:
        if _number(row.channel_low) is not None and row.Low <= row.channel_low + row.atr and spread > 0 and (row.Close - row.Low) / spread >= .7:
            add('low_absorption', '低位放量承接线索', 'bullish', '接近前20日低位、量比至少1.5、收于当日振幅上部30%；身份未知，底部待确认', status='pending', invalidation=row.Low)
        if spread > 0 and (row.High - row.Close) / spread >= .6 and row.High >= row.channel_high - row.atr:
            add('high_rejection', '高位放量回落', 'bearish', '接近前20日高位、量比至少1.5、收盘远离当日高点；不推断卖方身份', invalidation=row.High)
    return list(found.values())


def analyze_observations(frame: pd.DataFrame, trend: dict | None = None) -> dict[str, Any]:
    data = observation_frame(frame)
    if data.empty:
        raise ValueError('OHLCV must contain at least one row')
    row, indicators = data.iloc[-1], []
    zones = trend['zones'] if trend is not None else detect_price_zones(frame)

    def add(key, name, group, keys, text, side='neutral'):
        values = {k: _number(row[k]) for k in keys}
        available = all(v is not None for v in values.values())
        indicators.append({'id': key, 'name': name, 'group': group, 'values': values,
                           'status': 'available' if available else 'unavailable',
                           'side': side if available else 'neutral',
                           'interpretation': text if available else '样本不足、缺量或分母为零；不可计算项保留为空'})

    def side(value):
        return 'bullish' if value > 0 else 'bearish' if value < 0 else 'neutral'

    def crossing(left, right):
        if len(data) < 2:
            return ''
        before = data[left].iloc[-2] - data[right].iloc[-2]
        now = row[left] - row[right]
        return '；今日上穿' if before <= 0 < now else '；今日下穿' if before >= 0 > now else ''

    for period in (5, 10, 20, 60, 120, 250):
        delta = row.Close - row[f'sma{period}']
        add(f'sma{period}', f'MA{period}', '趋势', [f'sma{period}'], '收盘在线上' if delta > 0 else '收盘在线下' if delta < 0 else '收盘与均线持平', side(delta))
    add('ema', 'EMA20/50/200', '趋势', ['ema20', 'ema50', 'ema200', 'ema50_slope'], '均线位置与EMA50近5日变化；完整/短历史趋势按v2单独评估')
    add('bbi', 'BBI(3/6/12/24)', '趋势', ['bbi'], '收盘与四周期均线均值比较', side(row.Close - row.bbi))
    add('sar', 'SAR(0.02,0.02,0.2)', '趋势', ['sar'], '初始方向由前两根收盘决定，前两根极值初始化；翻转仅作观察', side(row.Close - row.sar))
    add('aroon', 'Aroon25', '趋势', ['aroon_up', 'aroon_down'], '含当日26根统计距最近高低点的日数；相同极值取最近一次', side(row.aroon_up - row.aroon_down))
    add('trix', 'TRIX(15,9)', '趋势/动量', ['trix', 'trix_signal'], '三重EMA15的单日变化率及其9日均值' + crossing('trix', 'trix_signal'), side(row.trix - row.trix_signal))
    macd_side = 'bullish' if row.macd > row.macd_signal and row.macd > 0 else 'bearish' if row.macd < row.macd_signal and row.macd < 0 else 'mixed'
    add('macd', 'MACD(12,26,9)', '趋势/动量', ['macd', 'macd_signal', 'macd_hist'], 'DIF、DEA、柱值=2×(DIF−DEA)；比较零轴与快慢线' + crossing('macd', 'macd_signal'), macd_side)
    add('dmi', 'DMI / ADX14 / ADXR', '趋势', ['di_plus', 'di_minus', 'adx', 'adxr'], 'DI比较方向；ADX/ADXR仅描述强度' + crossing('di_plus', 'di_minus'), side(row.di_plus - row.di_minus))
    rsi_text = '超买区；不能单独据此卖出' if row.rsi14 >= 70 else '超卖区；不能单独据此买入' if row.rsi14 <= 30 else 'RSI14相对50中轴的位置'
    add('rsi', 'RSI(6/12/14/24)', '动量', ['rsi6', 'rsi12', 'rsi14', 'rsi24'], rsi_text, side(row.rsi14 - 50) if 30 < row.rsi14 < 70 else 'neutral')
    add('kdj', 'KDJ(9,3,3)', '动量', ['kdj_k', 'kdj_d', 'kdj_j'], 'K、D种子50；J可超出0–100；交叉需结合价格' + crossing('kdj_k', 'kdj_d'), side(row.kdj_k - row.kdj_d))
    add('stoch', '慢速随机指标(14,3,3)', '动量', ['stoch_k', 'stoch_d'], '20/80仅作超卖/超买观察' + crossing('stoch_k', 'stoch_d'), side(row.stoch_k - row.stoch_d))
    add('wr', 'Williams %R14', '动量', ['williams_r14'], '−80以下/−20以上为传统超卖/超买区；不能单独买卖')
    add('cci', 'CCI20', '动量', ['cci20'], '典型价偏离；±100只作观察阈值', side(row.cci20))
    add('roc', 'ROC12 / Momentum10', '动量', ['roc12', 'momentum10'], '12日百分比变化与10日价格变化；方向不一致时标为分歧', side(row.roc12) if side(row.roc12) == side(row.momentum10) else 'mixed')
    add('bias', 'BIAS(6/12/24)', '偏离', ['bias6', 'bias12', 'bias24'], '相对各周期MA的偏离百分比；没有通用买卖阈值')
    add('boll', '布林带(20,2)', '波动', ['sma20', 'boll_upper', 'boll_lower', 'boll_width_pct', 'boll_percent_b'], '总体标准差；带宽为百分比、%B用0–1表示；触轨不等于反转')
    add('atr', 'ATR14 / ATR%', '波动', ['atr', 'atr_pct'], 'Wilder波动；不表示涨跌方向')
    add('hv', '历史波动率20日', '波动', ['hv20_pct'], '日对数收益样本标准差，按252日年化，非隐含波动率')
    add('keltner', 'Keltner通道(EMA20,2ATR14)', '波动', ['keltner_upper', 'keltner_lower'], '明确采用EMA20±2ATR14版本；越界只作偏离观察')
    for period in (20, 55):
        add(f'donchian{period}', f'Donchian前{period}日通道', '结构', [f'donchian_high{period}', f'donchian_low{period}'], '严格排除当前K线；收盘越界才触发突破观察')
    add('volume', '成交量 / 日线相对量', '量能', ['Volume', 'volume_ma5', 'volume_ma20', 'relative_volume'], '量比为当日量/之前20日均量，与盘中量比口径不同')
    for key, name in [('obv', 'OBV'), ('adl', 'A/D累积派发线')]:
        change = row[key] - data[key].iloc[-6] if len(data) >= 6 else np.nan
        add(key, name, '量能', [key], f'从输入历史起点累计；近5日变化 {_fmt(change)}；不是实际资金净流入', side(change))
    add('cmf', 'CMF20', '量能', ['cmf20'], '收盘在振幅中的位置加权成交量；量价代理，不识别交易者', side(row.cmf20))
    add('mfi', 'MFI14', '量能/动量', ['mfi14'], '80/20为传统超买/超卖区；不代表机构流入或抄底')
    add('vwma', 'VWMA20', '量价', ['vwma20'], '20日收盘成交量加权均价；日K近似', side(row.Close - row.vwma20))
    anchored = zones.get('anchored_vwap')
    indicators.append({'id': 'avwap', 'name': '锚定VWAP', 'group': '量价',
                       'values': {'anchored_vwap': anchored['value'] if anchored else None},
                       'status': 'available' if anchored else 'unavailable', 'side': 'neutral',
                       'interpretation': f"HLC3成交量近似；锚点 {anchored['anchor_date']}，确认于 {anchored['confirmed_at']}" if anchored else '缺少已确认锚点或完整成交量'})
    patterns = _structural_patterns(data, zones) + _price_patterns(data)
    bullish = [x['name'] for x in indicators if x['side'] == 'bullish']
    bearish = [x['name'] for x in indicators if x['side'] == 'bearish']
    return {'version': OBSERVATION_VERSION, 'as_of': _date(data, -1), 'timeframe': 'daily',
            'validation_status': 'UNVALIDATED', 'indicators': indicators, 'patterns': patterns,
            'bullish_evidence': bullish, 'bearish_evidence': bearish,
            'conflicts': ['趋势/动量/量价存在方向分歧；同源指标相关，不按数量投票'] if bullish and bearish else [],
            'limitations': ['仅描述截至完整日K收盘的观察；已确认指规则满足，不代表盈利已验证',
                            '超买不等于应卖、超卖不等于应买；形态阈值为项目口径',
                            '成交量相关指标是量价代理；交易者身份及其买卖意图未知']}


def _fmt(value: Any) -> str:
    number = _number(value)
    return '不可计算' if number is None else f'{number:.2f}'


def format_observations(observations: dict) -> list[str]:
    if not observations:
        return []
    lines = ['', '### 技术信号观察（自主判断）',
             f"- 截至 {observations['as_of']} 完整日K；观察版本 {observations['version']}。",
             '- 偏多/偏空为观察线索；形态确认条件另列，偏空不等于开空仓。',
             '- 偏多线索（买入观察）：' + ('、'.join(observations['bullish_evidence']) or '未出现可计算的偏多读数'),
             '- 偏空线索（卖出/减仓观察）：' + ('、'.join(observations['bearish_evidence']) or '未出现可计算的偏空读数')]
    lines += ['- 分歧：' + x for x in observations['conflicts']]
    lines += ['', '#### 形态与价格行为（文字）',
              '状态：待确认 / 已确认 / 已失效；几何识别与交易有效性分开。']
    states = {'pending': '待确认', 'confirmed': '已确认', 'failed': '已失效'}
    sides = {'bullish': '偏多', 'bearish': '偏空', 'neutral': '中性', 'mixed': '分歧'}
    for item in observations['patterns']:
        lines.append(f"- {item['name']}｜{sides[item['side']]}｜{states[item['status']]}：{item['evidence']}；"
                     f"最早识别 {item['detected_at']}，确认/失效 {item['confirmed_at'] or '尚未发生'}；"
                     f"触发参考 {_fmt(item['trigger'])}，失效参考 {_fmt(item['invalidation'])}。")
    if not observations['patterns']:
        lines.append('- 未识别到符合当前定义及观察窗口的形态；不强行匹配。')
    lines += ['', '#### 技术指标全表', '', '| 类别 | 指标 | 数值 | 观察 |', '| --- | --- | --- | --- |']
    labels = {'macd': 'DIF', 'macd_signal': 'DEA', 'macd_hist': '柱值', 'ema50_slope': 'EMA50近5日变化',
              'kdj_k': 'K', 'kdj_d': 'D', 'kdj_j': 'J', 'stoch_k': '%K', 'stoch_d': '%D',
              'di_plus': '+DI', 'di_minus': '−DI', 'aroon_up': 'Aroon上行', 'aroon_down': 'Aroon下行',
              'trix_signal': 'TRIX均线', 'sma20': 'MA20', 'boll_upper': '上轨', 'boll_lower': '下轨',
              'boll_width_pct': '带宽%', 'boll_percent_b': '%B', 'atr_pct': 'ATR%',
              'keltner_upper': '上沿', 'keltner_lower': '下沿', 'Volume': '当日量',
              'volume_ma5': '5日均量', 'volume_ma20': '20日均量', 'relative_volume': '相对量(倍)',
              'donchian_high20': '前20日高', 'donchian_low20': '前20日低',
              'donchian_high55': '前55日高', 'donchian_low55': '前55日低'}
    for item in observations['indicators']:
        values = '；'.join(f"{labels.get(key, key.upper())}={_fmt(value)}" if len(item['values']) > 1 else _fmt(value)
                          for key, value in item['values'].items())
        lines.append(f"| {item['group']} | {item['name']} | {values} | {sides[item['side']]}；{item['interpretation']} |")
    lines += ['', *['- ' + x for x in observations['limitations']], '', '### v2条件计划参考']
    return lines
