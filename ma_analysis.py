#!/usr/bin/env python3
"""
均线密集/发散分析工具 v3
MA20/60/120 + EMA20/60/120 六线系统
支持: 4h / 日线 / 周线
信号:
  - 均线密集 + K线在上方 → 买入
  - 均线密集 + K线在下方 → 卖出
  - 回踩MA20不破 → 强烈加仓
  - 假突破MA20 → 卖出
  - 假跌破MA20 → 买入（跌破后快速拉回）
支撑/压力:
  - 下跌支撑 = 上一次均线密集处(密集时间越久支撑越强)
  - 上涨压力 = 前高 / 斐波那契扩展(1.618, 2.618, 3.618)
v3新增:
  - 均线密集台阶位(上方/下方)
  - 大周期斐波那契回撤(0.236/0.382/0.5/0.618/0.786)
  - 斐波那契与密集区重合检测
  - 前高斐波那契扩展(1.618/2.618/3.618)
"""

import sys
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

MA_COLS = ['MA20', 'MA60', 'MA120', 'EMA20', 'EMA60', 'EMA120']


def calc_ma(df):
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA60'] = df['Close'].rolling(60).mean()
    df['MA120'] = df['Close'].rolling(120).mean()
    df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['EMA60'] = df['Close'].ewm(span=60, adjust=False).mean()
    df['EMA120'] = df['Close'].ewm(span=120, adjust=False).mean()
    return df


def get_convergence(row):
    vals = [row[c] for c in MA_COLS]
    m = np.mean(vals)
    if m == 0:
        return 999.0
    return (np.std(vals) / m) * 100


def find_convergence_zones(df, threshold=3.0, min_bars=3):
    """找历史均线密集区, 返回[(start, end, duration, avg_price, strength)]"""
    zones = []
    in_zone = False
    zone_start = None
    zone_prices = []
    valid = df.dropna(subset=MA_COLS)

    for idx, row in valid.iterrows():
        cr = get_convergence(row)
        if cr < threshold:
            if not in_zone:
                in_zone = True
                zone_start = idx
                zone_prices = []
            zone_prices.append(row['Close'])
        else:
            if in_zone and len(zone_prices) >= min_bars:
                avg_p = np.mean(zone_prices)
                dur = len(zone_prices)
                strength = "极强" if dur >= 20 else ("强" if dur >= 10 else ("中等" if dur >= 5 else "弱"))
                zones.append((zone_start, idx, dur, avg_p, strength))
            in_zone = False

    if in_zone and len(zone_prices) >= min_bars:
        avg_p = np.mean(zone_prices)
        dur = len(zone_prices)
        strength = "极强" if dur >= 20 else ("强" if dur >= 10 else ("中等" if dur >= 5 else "弱"))
        zones.append((zone_start, valid.index[-1], dur, avg_p, strength))

    return zones


def find_supports(zones, close):
    """从密集区中找支撑位(低于当前价的密集区)"""
    supports = [(z[3], z[4], z[2], z[0], z[1]) for z in zones if z[3] < close]
    supports.sort(key=lambda x: x[0], reverse=True)  # 从近到远
    return supports


def find_resistances_from_zones(zones, close):
    """从密集区中找压力位(高于当前价的密集区)"""
    resistances = [(z[3], z[4], z[2], z[0], z[1]) for z in zones if z[3] > close]
    resistances.sort(key=lambda x: x[0])
    return resistances


def find_recent_high(df, lookback=120):
    """找前高"""
    recent = df.tail(lookback)
    high_val = recent['High'].max()
    high_idx = recent['High'].idxmax()
    return high_val, high_idx


def find_recent_low(df, lookback=120):
    """找前低"""
    recent = df.tail(lookback)
    low_val = recent['Low'].min()
    low_idx = recent['Low'].idxmin()
    return low_val, low_idx


def fib_extensions(low, high):
    """斐波那契扩展位 — 从最高点向上"""
    diff = high - low
    return {
        '1.618': high + diff * 0.618,
        '2.618': high + diff * 1.618,
        '3.618': high + diff * 2.618,
    }


def find_ath(ticker):
    """找历史最高点(ATH) — 用于创新高后的斐波那契扩展
    找ATH前最近一个大周期的起涨低点(而非全历史最低)
    策略: 从ATH往回找, 先找跌幅>15%的回调低点作为起涨点
    """
    df = yf.download(ticker, period='max', progress=False)
    if df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    ath = df['High'].max()
    ath_date = df['High'].idxmax()
    ath_pos = df.index.get_loc(ath_date)

    # 从ATH往回找最近的显著低点
    # 方法: 从ATH位置往回扫描，找到一个低点使得涨幅>15%
    before_ath = df.iloc[:ath_pos+1]
    if len(before_ath) < 10:
        return None

    # 从右往左滑动窗口找低点
    best_low = ath  # 初始化
    best_low_date = ath_date
    for i in range(len(before_ath)-1, -1, -1):
        cur_low = before_ath['Low'].iloc[i]
        if cur_low < best_low:
            best_low = cur_low
            best_low_date = before_ath.index[i]
        # 检查从此低点到ATH的涨幅
        gain = (ath - best_low) / best_low * 100
        if gain > 15:
            # 找到了显著的起涨低点，继续往回看看能不能找到更深的
            # 但不超过ATH之前250个交易日(约1年)
            lookback_limit = max(0, ath_pos - 250)
            remaining = before_ath.iloc[lookback_limit:i]
            if len(remaining) > 0:
                deeper_low = remaining['Low'].min()
                deeper_low_idx = remaining['Low'].idxmin()
                if deeper_low < best_low:
                    best_low = deeper_low
                    best_low_date = deeper_low_idx
            break

    if best_low >= ath:
        return None

    return (ath, ath_date, best_low, best_low_date)


def match_fib_to_step(step_price, fib_levels, tolerance_pct=2.0):
    """给台阶匹配最近的斐波那契值"""
    best = None
    best_diff = float('inf')
    for name, price in fib_levels.items():
        diff_pct = abs(step_price - price) / price * 100
        if diff_pct < tolerance_pct and diff_pct < best_diff:
            best = (name, price)
            best_diff = diff_pct
    return best


def fib_retracement(low, high):
    """斐波那契回撤位 — 从高点向下"""
    diff = high - low
    return {
        '0.236': high - diff * 0.236,
        '0.382': high - diff * 0.382,
        '0.500': high - diff * 0.500,
        '0.618': high - diff * 0.618,
        '0.786': high - diff * 0.786,
    }


def find_major_cycle(df, lookback=None):
    """找最近一个大周期: 低点起涨 → 最高点
    策略: 从最近的数据往回找，找到一个显著的波段(涨幅>15%)
    如果找不到大波段，退而求其次找最近120根K线内的高低点
    返回 (low_price, low_date, high_price, high_date)
    """
    data = df if lookback is None else df.tail(lookback)
    if len(data) < 10:
        return None

    # 方法1: 找最近的显著波段
    # 从右往左扫描，找局部高点和之前的局部低点
    highs = data['High'].values
    lows = data['Low'].values
    dates = data.index

    # 找最高点
    high_val = data['High'].max()
    high_pos = data['High'].values.argmax()
    high_idx = dates[high_pos]

    # 在最高点之前找最低点
    if high_pos < 3:
        # 高点太靠前，用全部数据找低点
        low_val = data['Low'].min()
        low_pos = data['Low'].values.argmin()
    else:
        before_data = data.iloc[:high_pos]
        low_val = before_data['Low'].min()
        low_pos = before_data['Low'].values.argmin()

    low_idx = dates[low_pos]

    # 确保低点在高点之前且有意义的涨幅(>10%)
    if low_pos >= high_pos:
        return None
    if low_val == 0:
        return None
    gain_pct = (high_val - low_val) / low_val * 100
    if gain_pct < 5:
        return None

    return (low_val, low_idx, high_val, high_idx)


def find_convergence_steps(zones, close):
    """均线密集台阶位 — 按价格排列上方和下方的密集区
    返回 (steps_above, steps_below)
    每个step: (avg_price, strength, duration, start, end, dist_pct)
    """
    steps_above = []
    steps_below = []
    for z in zones:
        start, end, dur, avg_p, strength = z
        dist_pct = ((avg_p - close) / close) * 100
        step = (avg_p, strength, dur, start, end, dist_pct)
        if avg_p > close:
            steps_above.append(step)
        else:
            steps_below.append(step)

    # 上方: 从近到远 (价格从低到高)
    steps_above.sort(key=lambda x: x[0])
    # 下方: 从近到远 (价格从高到低)
    steps_below.sort(key=lambda x: x[0], reverse=True)

    return steps_above, steps_below


def find_fib_zone_overlap(fib_levels, zones, tolerance_pct=2.0):
    """找斐波那契位与均线密集区的重合
    tolerance_pct: 价格偏差容忍度(%)
    返回 [(fib_name, fib_price, zone_price, zone_strength, zone_dur)]
    """
    overlaps = []
    for fib_name, fib_price in fib_levels.items():
        for z in zones:
            zone_price = z[3]  # avg_price
            zone_strength = z[4]
            zone_dur = z[2]
            diff_pct = abs(fib_price - zone_price) / fib_price * 100
            if diff_pct < tolerance_pct:
                overlaps.append((fib_name, fib_price, zone_price, zone_strength, zone_dur))
    return overlaps


def detect_pullback(df):
    """回踩MA20不破检测"""
    recent = df.dropna(subset=MA_COLS).tail(10)
    if len(recent) < 5:
        return False, "数据不足"

    close_vals = recent['Close'].values
    low_vals = recent['Low'].values
    ma20_vals = recent['MA20'].values
    ema20_vals = recent['EMA20'].values
    dates = recent.index

    was_above = False
    pullback_found = False
    bounce_confirmed = False
    pb_date = bounce_date = None

    for i in range(len(close_vals)):
        c, lo, m20, e20 = close_vals[i], low_vals[i], ma20_vals[i], ema20_vals[i]
        avg20 = (m20 + e20) / 2

        if c > m20 and c > e20:
            was_above = True

        if was_above and not pullback_found:
            touch = abs(lo - avg20) / avg20 * 100
            if touch < 1.5 and c >= m20 * 0.99:
                pullback_found = True
                pb_date = dates[i].strftime('%m-%d')

        if pullback_found and not bounce_confirmed:
            if c > m20 and c > e20:
                bounce_confirmed = True
                bounce_date = dates[i].strftime('%m-%d')

    if bounce_confirmed:
        return True, f"回踩确认! 回踩:{pb_date} → 站稳:{bounce_date}"
    elif pullback_found:
        return False, f"回踩中({pb_date})，等待站稳"
    elif was_above:
        return False, "曾站上MA20，尚未回踩"
    return False, "未站上MA20，回踩不成立"


def detect_fake_breakout(df):
    """假突破MA20检测"""
    recent = df.dropna(subset=MA_COLS).tail(15)
    if len(recent) < 5:
        return False, "数据不足"

    close_vals = recent['Close'].values
    ma20_vals = recent['MA20'].values
    ema20_vals = recent['EMA20'].values
    dates = recent.index

    above_phase = False
    above_start = None
    above_days = 0
    breakdown_found = False
    breakdown_date = None

    for i in range(len(close_vals)):
        c, m20, e20 = close_vals[i], ma20_vals[i], ema20_vals[i]
        if not above_phase:
            if c > m20 and c > e20:
                above_phase = True
                above_start = dates[i].strftime('%m-%d')
                above_days = 1
        else:
            if c > m20 and c > e20:
                above_days += 1
            elif c < m20 and c < e20:
                if above_days <= 5:
                    breakdown_found = True
                    breakdown_date = dates[i].strftime('%m-%d')
                above_phase = False
                above_days = 0

    latest_c = close_vals[-1]
    latest_m20 = ma20_vals[-1]
    latest_e20 = ema20_vals[-1]

    if breakdown_found:
        if latest_c < latest_m20 and latest_c < latest_e20:
            return True, f"假突破确认! 站上:{above_start}({above_days}天) → 跌破:{breakdown_date}"
        return False, f"曾假突破({above_start}→{breakdown_date})，已重新站回"
    elif above_phase:
        if latest_c < latest_m20:
            return True, f"刚跌破! 站上:{above_start}({above_days}天)"
        return False, f"站上MA20中(自{above_start}，已{above_days}天)"
    return False, "近期未站上MA20"


def detect_fake_breakdown(df):
    """假跌破MA20检测
    逻辑: K线在MA20下方横盘 → 进一步下跌 → 快速拉回站上MA20 → 假跌破买入信号
    - 在MA20下方至少2天
    - 期间创新低
    - 随后≤5天内拉回站上MA20和EMA20
    """
    recent = df.dropna(subset=MA_COLS).tail(15)
    if len(recent) < 5:
        return False, "数据不足"

    close_vals = recent['Close'].values
    low_vals = recent['Low'].values
    ma20_vals = recent['MA20'].values
    ema20_vals = recent['EMA20'].values
    dates = recent.index

    below_phase = False
    below_start = None
    below_days = 0
    lowest_idx = None
    lowest_price = float('inf')
    recovery_found = False
    recovery_date = None
    breakdown_date = None

    for i in range(len(close_vals)):
        c, lo, m20, e20 = close_vals[i], low_vals[i], ma20_vals[i], ema20_vals[i]

        if not below_phase:
            if c < m20 and c < e20:
                below_phase = True
                below_start = dates[i].strftime('%m-%d')
                below_days = 1
                lowest_price = lo
                lowest_idx = i
        else:
            if c < m20 and c < e20:
                below_days += 1
                if lo < lowest_price:
                    lowest_price = lo
                    lowest_idx = i
                    breakdown_date = dates[i].strftime('%m-%d')
            elif c > m20 and c > e20:
                days_since_low = i - lowest_idx
                if days_since_low <= 5 and below_days >= 2:
                    recovery_found = True
                    recovery_date = dates[i].strftime('%m-%d')
                below_phase = False
                below_days = 0
                lowest_price = float('inf')

    latest_c = close_vals[-1]
    latest_m20 = ma20_vals[-1]
    latest_e20 = ema20_vals[-1]

    if recovery_found:
        if latest_c > latest_m20 and latest_c > latest_e20:
            return True, f"假跌破确认! 跌破:{breakdown_date or below_start} → 拉回:{recovery_date}"
        return False, f"曾假跌破({breakdown_date or below_start}→{recovery_date})，但又跌回"
    elif below_phase:
        return False, f"在MA20下方(自{below_start}，已{below_days}天)，等待拉回"
    return False, "无假跌破"


def analyze_timeframe(df, ticker, tf_label, detailed=False):
    """分析单个时间级别。detailed=True时展开完整信息，False时精简"""
    df = calc_ma(df)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    valid = df.dropna(subset=MA_COLS)
    if len(valid) < 5:
        return {'signal': 'nodata', 'tf': tf_label}

    latest = valid.iloc[-1]
    close = latest['Close']
    ma_values = {c: latest[c] for c in MA_COLS}
    all_ma = list(ma_values.values())

    # 密集度
    cr = get_convergence(latest)
    if cr < 2.0:
        cr_label = "极度密集🔥"
        is_conv = True
    elif cr < 4.0:
        cr_label = "较为密集⚡"
        is_conv = True
    else:
        cr_label = f"未密集({cr:.1f}%)"
        is_conv = False

    # K线位置
    above_cnt = sum(1 for v in all_ma if close > v)
    below_cnt = 6 - above_cnt
    k_above = above_cnt > below_cnt if above_cnt != below_cnt else False

    # 信号判定
    if is_conv and k_above:
        signal = 'buy'
    elif is_conv and not k_above:
        signal = 'sell'
    else:
        signal = 'wait'

    # 排列
    short_avg = np.mean([ma_values['MA20'], ma_values['EMA20']])
    mid_avg = np.mean([ma_values['MA60'], ma_values['EMA60']])
    long_avg = np.mean([ma_values['MA120'], ma_values['EMA120']])
    if short_avg > mid_avg > long_avg:
        arr = "多头🟢"
    elif short_avg < mid_avg < long_avg:
        arr = "空头🔴"
    else:
        arr = "交叉🟡"

    # 支撑压力
    zones = find_convergence_zones(valid, threshold=3.0, min_bars=3)
    supports = find_supports(zones, close)
    zone_res = find_resistances_from_zones(zones, close)
    recent_high, high_date = find_recent_high(valid)
    recent_low, low_date = find_recent_low(valid)

    # v3新增: 均线密集台阶位
    steps_above, steps_below = find_convergence_steps(zones, close)

    # v3新增: 大周期斐波那契
    major_cycle = find_major_cycle(valid)  # 用全部数据找大周期
    fib_ret = None
    fib_ret_overlap = []
    if major_cycle:
        cycle_low, cycle_low_date, cycle_high, cycle_high_date = major_cycle
        fib_ret = fib_retracement(cycle_low, cycle_high)
        fib_ret_overlap = find_fib_zone_overlap(fib_ret, zones, tolerance_pct=1.5)

    result = {
        'signal': signal, 'tf': tf_label, 'close': close,
        'cr': cr, 'cr_label': cr_label, 'is_conv': is_conv,
        'k_above': k_above, 'above_cnt': above_cnt, 'arr': arr,
        'ma_values': ma_values, 'supports': supports, 'resistances': zone_res,
        'high': recent_high, 'high_date': high_date,
        'low': recent_low, 'low_date': low_date,
        'valid': valid,
        # v3新增
        'steps_above': steps_above,
        'steps_below': steps_below,
        'major_cycle': major_cycle,
        'fib_ret': fib_ret,
        'fib_ret_overlap': fib_ret_overlap,
    }

    # 回踩/假突破 (仅密集+买入时)
    if signal == 'buy':
        pb_sig, pb_det = detect_pullback(valid)
        fb_sig, fb_det = detect_fake_breakout(valid)
        result['pb_signal'] = pb_sig
        result['pb_detail'] = pb_det
        result['fb_signal'] = fb_sig
        result['fb_detail'] = fb_det

    # 假跌破检测 (密集+卖出时，或密集+观望时)
    # 假跌破确认 → 信号升级为买入
    if signal == 'sell' or (signal == 'watch' and is_conv):
        fbd_sig, fbd_det = detect_fake_breakdown(valid)
        result['fbd_signal'] = fbd_sig
        result['fbd_detail'] = fbd_det
        if fbd_sig:
            result['signal'] = 'buy'
            signal = 'buy'  # 假跌破确认，升级为买入

    return result


def print_detailed(ticker, results, ath_data=None):
    """有买入信号时的详细输出"""
    print(f"\n{'='*55}")
    print(f"  🟢 {ticker} — 有买入信号")
    print(f"{'='*55}")

    close = results[0]['close']

    for r in results:
        tf = r['tf']
        sig = r['signal']
        if sig == 'buy':
            sig_str = "🟢买入"
        elif sig == 'sell':
            sig_str = "🔴卖出"
        else:
            sig_str = "⚫观望"

        line = f"  [{tf}] {sig_str} | {r['cr_label']} | {r['arr']}"
        if sig == 'buy':
            if r.get('pb_signal'):
                line += " | ⚡回踩加仓"
            if r.get('fb_signal'):
                line += " | 🚨假突破!"
        if r.get('fbd_signal'):
            line += " | 🟢假跌破买入!"
        print(line)

    # 详细均线 (用第一个有买入信号的)
    buy_r = next((r for r in results if r['signal'] == 'buy'), results[0])
    print(f"\n📊 均线数值 [{buy_r['tf']}]")
    for c in MA_COLS:
        v = buy_r['ma_values'][c]
        d = ((close - v) / v) * 100
        arrow = "↑" if close > v else "↓"
        print(f"  {c.ljust(8)}: {v:.2f} ({arrow}{abs(d):.2f}%)")

    # 回踩/假突破/假跌破详情
    for r in results:
        if r['signal'] == 'buy':
            print(f"\n  [{r['tf']}] 💪回踩: {r.get('pb_detail', '-')}")
            print(f"  [{r['tf']}] 🚨假突破: {r.get('fb_detail', '-')}")
        if r.get('fbd_signal') is not None:
            print(f"  [{r['tf']}] 🟢假跌破: {r.get('fbd_detail', '-')}")

    # 支撑压力
    print(f"\n🔑 支撑压力位")
    _print_sp(results, close, ath_data)

    # 密集度趋势 (买入级别)
    print(f"\n📉 密集度趋势 [{buy_r['tf']}] (近10根)")
    recent = buy_r['valid'].tail(10)
    for idx, row in recent.iterrows():
        r_cr = get_convergence(row)
        r_above = sum(1 for c in MA_COLS if row['Close'] > row[c])
        bar = "█" * min(int(r_cr * 3), 20)
        icon = "▲" if r_above >= 4 else ("▼" if r_above <= 2 else "◆")
        print(f"  {idx.strftime('%m-%d')} | {r_cr:5.2f}% {bar} {icon}")


def print_compact(ticker, results, ath_data=None):
    """无买入信号时的精简输出"""
    close = results[0]['close'] if results else 0
    # 判断整体信号
    signals = [r['signal'] for r in results]
    if 'sell' in signals:
        overall = "🔴"
    else:
        overall = "⚫"

    tf_parts = []
    for r in results:
        tf = r['tf'][:1]  # 4/日/周 取首字
        if r['signal'] == 'sell':
            tf_parts.append(f"{tf}:卖")
        else:
            tf_parts.append(f"{tf}:望")

    tf_str = " ".join(tf_parts)

    # 最近支撑/压力 (取所有级别中最近的)
    all_sup = []
    all_res = []
    for r in results:
        all_sup.extend(r.get('supports', []))
        all_res.extend(r.get('resistances', []))

    sup_str = ""
    if all_sup:
        nearest_s = max(all_sup, key=lambda x: x[0])
        sup_str = f"S:{nearest_s[0]:.1f}({nearest_s[1]})"
    else:
        sup_str = f"前低:{results[0]['low']:.1f}"

    res_str = ""
    if all_res:
        nearest_r = min(all_res, key=lambda x: x[0])
        res_str = f"R:{nearest_r[0]:.1f}({nearest_r[1]})"
    else:
        res_str = f"前高:{results[0]['high']:.1f}"

    # 检查是否有假跌破信号
    has_fbd = any(r.get('fbd_signal') for r in results)
    fbd_tag = " | 🟢假跌破!" if has_fbd else ""

    print(f"  {overall} {ticker} {close:.2f} | {tf_str} | {sup_str} | {res_str}{fbd_tag}")

    # v3: 精简台阶位 + 斐波那契匹配
    step_r = next((r for r in results if r['tf'] == '日线'), results[0])
    steps_above = step_r.get('steps_above', [])
    steps_below = step_r.get('steps_below', [])
    # 获取fib回撤用于台阶匹配
    fib_r_c = next((r for r in results if r.get('fib_ret')), None)
    fib_for_match_c = fib_r_c['fib_ret'] if fib_r_c else {}

    if steps_above:
        for i, top in enumerate(steps_above[:3]):
            fib_match = match_fib_to_step(top[0], fib_for_match_c, tolerance_pct=2.5)
            fib_tag = f" ≈Fib{fib_match[0]}" if fib_match else ""
            print(f"    ▲T{i+1}: {top[0]:.2f}(+{top[5]:.1f}%, {top[1]}{top[2]}天){fib_tag}")
    if steps_below:
        for i, bot in enumerate(steps_below[:3]):
            fib_match = match_fib_to_step(bot[0], fib_for_match_c, tolerance_pct=2.5)
            fib_tag = f" ≈Fib{fib_match[0]}" if fib_match else ""
            print(f"    ▼T{i+1}: {bot[0]:.2f}({bot[5]:.1f}%, {bot[1]}{bot[2]}天){fib_tag}")

    # v3: 大周期斐波那契 (精简)
    fib_r = next((r for r in results if r.get('major_cycle')), None)
    if fib_r and fib_r.get('fib_ret'):
        mc = fib_r['major_cycle']
        print(f"    📐 周期:{mc[0]:.1f}→{mc[2]:.1f} | ", end="")
        fib_parts = []
        for name, price in fib_r['fib_ret'].items():
            dist = ((price - close) / close) * 100
            marker = "◀" if abs(dist) < 1.5 else ""
            fib_parts.append(f"{name}:{price:.1f}{marker}")
        print(" ".join(fib_parts))
        # 重合
        overlaps = fib_r.get('fib_ret_overlap', [])
        if overlaps:
            for fn, fp, zp, zs, zd in overlaps:
                print(f"    🎯 Fib{fn}({fp:.1f})≈密集({zp:.1f},{zs}{zd}天)")

    # v3: ATH斐波那契扩展 (创新高后的目标位)
    if ath_data and len(ath_data) == 4:
        ath_val, ath_date_c, ath_low, ath_low_date = ath_data
        fibs = fib_extensions(ath_low, ath_val)
        parts = [f"FE{k}:{v:.1f}({((v-close)/close)*100:+.0f}%)" for k, v in fibs.items()]
        print(f"    📐 ATH扩展({ath_val:.1f}): {' / '.join(parts)}")
    else:
        r0 = results[0]
        fibs = fib_extensions(r0['low'], r0['high'])
        print(f"    📐 扩展: ", end="")
        parts = [f"FE{k}:{v:.1f}" for k, v in fibs.items()]
        print(" / ".join(parts))


def _print_sp(results, close, ath_data=None):
    """打印支撑压力位 + 台阶位 + 斐波那契回撤 + 扩展"""
    # 原有支撑压力
    for r in results:
        tf = r['tf']
        if r['supports']:
            for i, (price, strength, dur, s_start, s_end) in enumerate(r['supports'][:2]):
                dist = ((close - price) / close) * 100
                print(f"  [{tf}] S{i+1}: {price:.2f} (距{dist:.1f}%, {strength}{dur}天)")
        if r['resistances']:
            for i, (price, strength, dur, r_start, r_end) in enumerate(r['resistances'][:2]):
                dist = ((price - close) / close) * 100
                print(f"  [{tf}] R{i+1}: {price:.2f} (距{dist:.1f}%, {strength}{dur}天)")

    # 前高前低
    r0 = results[0]
    print(f"  前高: {r0['high']:.2f} ({r0['high_date'].strftime('%Y-%m-%d')})")
    print(f"  前低: {r0['low']:.2f} ({r0['low_date'].strftime('%Y-%m-%d')})")

    # v3: 均线密集台阶位 (用日线或第一个有数据的级别)
    step_r = next((r for r in results if r['tf'] == '日线'), results[0])
    steps_above = step_r.get('steps_above', [])
    steps_below = step_r.get('steps_below', [])
    # 获取fib回撤用于台阶匹配
    fib_r = next((r for r in results if r.get('fib_ret')), None)
    fib_for_match = fib_r['fib_ret'] if fib_r else {}

    if steps_above or steps_below:
        print(f"\n🪜 均线密集台阶位 [{step_r['tf']}]")
        if steps_above:
            print(f"  ▲ 上方台阶 (压力):")
            for i, (price, strength, dur, start, end, dist) in enumerate(steps_above[:4]):
                fib_match = match_fib_to_step(price, fib_for_match, tolerance_pct=2.5)
                fib_tag = f" ≈Fib{fib_match[0]}" if fib_match else ""
                print(f"    T{i+1}↑ {price:.2f} (+{dist:.1f}%, {strength}{dur}天){fib_tag}")
        if steps_below:
            print(f"  ▼ 下方台阶 (支撑):")
            for i, (price, strength, dur, start, end, dist) in enumerate(steps_below[:4]):
                fib_match = match_fib_to_step(price, fib_for_match, tolerance_pct=2.5)
                fib_tag = f" ≈Fib{fib_match[0]}" if fib_match else ""
                print(f"    T{i+1}↓ {price:.2f} ({dist:.1f}%, {strength}{dur}天){fib_tag}")

    # v3: 大周期斐波那契回撤
    fib_r = next((r for r in results if r.get('major_cycle')), None)
    if fib_r and fib_r.get('major_cycle'):
        cycle_low, cycle_low_date, cycle_high, cycle_high_date = fib_r['major_cycle']
        print(f"\n📐 大周期斐波那契 [{fib_r['tf']}]")
        print(f"  周期: {cycle_low:.2f}({cycle_low_date.strftime('%m-%d')}) → {cycle_high:.2f}({cycle_high_date.strftime('%m-%d')})")
        fib_ret = fib_r['fib_ret']
        if fib_ret:
            print(f"  回撤位:")
            for name, price in fib_ret.items():
                dist = ((price - close) / close) * 100
                marker = " ◀ 当前" if abs(dist) < 1.5 else ""
                print(f"    {name}: {price:.2f} ({'+' if dist > 0 else ''}{dist:.1f}%){marker}")

        # 斐波那契与密集区重合
        overlaps = fib_r.get('fib_ret_overlap', [])
        if overlaps:
            print(f"  🎯 斐波那契×密集区 重合:")
            for fib_name, fib_price, zone_price, zone_strength, zone_dur in overlaps:
                print(f"    Fib {fib_name}({fib_price:.2f}) ≈ 密集区({zone_price:.2f}, {zone_strength}{zone_dur}天)")

    # v3: ATH斐波那契扩展 (创历史新高后的目标位)
    if ath_data and len(ath_data) == 4:
        ath_val, ath_date, ath_low, ath_low_date = ath_data
        fibs = fib_extensions(ath_low, ath_val)
        print(f"\n📐 ATH扩展 (ATH:{ath_val:.2f} {ath_date.strftime('%Y-%m-%d')}, 起涨:{ath_low:.2f})")
        for k, v in fibs.items():
            dist = ((v - close) / close) * 100
            print(f"    FE{k}: {v:.2f} ({'+' if dist > 0 else ''}{dist:.1f}%)")
    else:
        # fallback: 用当前周期前高前低
        fibs = fib_extensions(r0['low'], r0['high'])
        print(f"\n📐 前高扩展: ", end="")
        parts = [f"FE{k}:{v:.1f}" for k, v in fibs.items()]
        print(" / ".join(parts))


def resample_4h(df):
    """将日线近似转为4h (yfinance 4h数据有限，用1h聚合)"""
    # yfinance interval=1h 最多730天, 4h需要手动聚合
    return df  # 直接用1h下载后聚合


def analyze(ticker, timeframes=None):
    if timeframes is None:
        timeframes = ['daily']

    # 获取ATH数据 (用于斐波那契扩展)
    ath_data = find_ath(ticker)

    results = []
    for tf in timeframes:
        if tf == '4h':
            end = datetime.now() + timedelta(days=1)
            start = end - timedelta(days=121)
            df_1h = yf.download(ticker, start=start.strftime('%Y-%m-%d'),
                                end=end.strftime('%Y-%m-%d'),
                                interval='1h', progress=False)
            if df_1h.empty:
                continue
            if isinstance(df_1h.columns, pd.MultiIndex):
                df_1h.columns = df_1h.columns.get_level_values(0)
            df_4h = df_1h.resample('4h').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min',
                'Close': 'last', 'Volume': 'sum'
            }).dropna()
            r = analyze_timeframe(df_4h, ticker, "4小时")
            if r:
                results.append(r)

        elif tf == 'daily':
            end = datetime.now() + timedelta(days=1)
            start = end - timedelta(days=366)
            df_d = yf.download(ticker, start=start.strftime('%Y-%m-%d'),
                               end=end.strftime('%Y-%m-%d'), progress=False)
            if df_d.empty:
                continue
            if isinstance(df_d.columns, pd.MultiIndex):
                df_d.columns = df_d.columns.get_level_values(0)
            r = analyze_timeframe(df_d, ticker, "日线")
            if r:
                results.append(r)

        elif tf == 'weekly':
            end = datetime.now() + timedelta(days=1)
            start = end - timedelta(days=365*3+1)
            df_w = yf.download(ticker, start=start.strftime('%Y-%m-%d'),
                               end=end.strftime('%Y-%m-%d'),
                               interval='1wk', progress=False)
            if df_w.empty:
                continue
            if isinstance(df_w.columns, pd.MultiIndex):
                df_w.columns = df_w.columns.get_level_values(0)
            r = analyze_timeframe(df_w, ticker, "周线")
            if r:
                results.append(r)

    if not results:
        print(f"  ⚠️ {ticker}: 无数据")
        return

    # 判断是否有买入信号
    has_buy = any(r['signal'] == 'buy' for r in results)
    if has_buy:
        print_detailed(ticker, results, ath_data)
    else:
        print_compact(ticker, results, ath_data)


if __name__ == "__main__":
    # 用法: python3 ma_analysis.py [ticker] [4h,daily,weekly]
    # 无参数时跑全部7只持仓
    DEFAULT_TICKERS = ['0700.HK', '1810.HK', 'QQQ', 'NVDA', 'TSLA', 'PDD', '9992.HK']
    tfs_arg = sys.argv[2] if len(sys.argv) > 2 else "4h,daily,weekly"
    tfs = [t.strip() for t in tfs_arg.split(',')]

    if len(sys.argv) > 1:
        analyze(sys.argv[1], tfs)
    else:
        print(f"\n{'='*60}")
        print(f"  📊 持仓均线分析 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"{'='*60}")
        for t in DEFAULT_TICKERS:
            analyze(t, tfs)
        print(f"{'='*60}")
