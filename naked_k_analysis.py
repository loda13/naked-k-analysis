#!/usr/bin/env python3
"""
裸K (Price Action) 分析工具
纯K线分析，不用任何指标
分析维度:
1. K线形态识别 (锤子线、吞没、十字星、Pin Bar等)
2. 支撑/阻力位 (前高前低、多次测试)
3. 价格结构 (趋势判断: HH/HL = 上升, LH/LL = 下降)
4. 关键位反应
"""

import sys
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def fetch_data(ticker, period="1y", interval="1d"):
    """获取K线数据"""
    t = yf.Ticker(ticker)
    df = t.history(period=period, interval=interval)
    if df.empty:
        return None
    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def identify_candle_patterns(df):
    """识别K线形态, 返回最近20根K线的形态列表"""
    patterns = []
    for i in range(max(1, len(df) - 20), len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        o, h, l, c = row['Open'], row['High'], row['Low'], row['Close']
        po, ph, pl, pc = prev['Open'], prev['High'], prev['Low'], prev['Close']
        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        total_range = h - l
        date = df.index[i]

        if total_range == 0:
            continue

        body_ratio = body / total_range

        # 十字星 Doji
        if body_ratio < 0.1:
            patterns.append((date, '十字星 Doji', '犹豫信号，可能反转'))
            continue

        # 锤子线 Hammer (下跌中出现)
        if lower_wick >= body * 2 and upper_wick < body * 0.5 and c > o:
            patterns.append((date, '🔨 锤子线 Hammer', '潜在底部反转'))
            continue

        # 上吊线 Hanging Man (上涨中出现)
        if lower_wick >= body * 2 and upper_wick < body * 0.5 and c < o:
            patterns.append((date, '☠️ 上吊线 Hanging Man', '潜在顶部反转'))
            continue

        # 射击之星 Shooting Star
        if upper_wick >= body * 2 and lower_wick < body * 0.5 and c < o:
            patterns.append((date, '💫 射击之星 Shooting Star', '顶部反转信号'))
            continue

        # 倒锤子 Inverted Hammer
        if upper_wick >= body * 2 and lower_wick < body * 0.5 and c > o:
            patterns.append((date, '🔄 倒锤子 Inverted Hammer', '底部可能反转'))
            continue

        # Pin Bar (长影线)
        if lower_wick >= total_range * 0.6:
            patterns.append((date, '📌 看涨Pin Bar', '下方有强支撑'))
            continue
        if upper_wick >= total_range * 0.6:
            patterns.append((date, '📌 看跌Pin Bar', '上方有强压力'))
            continue

        # 看涨吞没 Bullish Engulfing
        if c > o and pc < po and c > po and o < pc and body > abs(pc - po):
            patterns.append((date, '🟢 看涨吞没', '强烈看多信号'))
            continue

        # 看跌吞没 Bearish Engulfing
        if c < o and pc > po and c < po and o > pc and body > abs(pc - po):
            patterns.append((date, '🔴 看跌吞没', '强烈看空信号'))
            continue

        # 大阳线
        if c > o and body_ratio > 0.7 and body / o * 100 > 2:
            patterns.append((date, '🟢 大阳线', '多头强势'))
            continue

        # 大阴线
        if c < o and body_ratio > 0.7 and body / o * 100 > 2:
            patterns.append((date, '🔴 大阴线', '空头强势'))
            continue

    return patterns


def find_swing_points(df, window=5):
    """找摆动高低点 (Swing High / Swing Low)"""
    highs = []
    lows = []
    for i in range(window, len(df) - window):
        # Swing High
        if df['High'].iloc[i] == df['High'].iloc[i - window:i + window + 1].max():
            highs.append((df.index[i], df['High'].iloc[i]))
        # Swing Low
        if df['Low'].iloc[i] == df['Low'].iloc[i - window:i + window + 1].min():
            lows.append((df.index[i], df['Low'].iloc[i]))
    return highs, lows


def analyze_structure(highs, lows):
    """分析价格结构: HH/HL=上升趋势, LH/LL=下降趋势"""
    if len(highs) < 2 or len(lows) < 2:
        return "数据不足", []

    # 取最近的摆动点
    recent_highs = highs[-4:]
    recent_lows = lows[-4:]

    details = []

    # 判断高点趋势
    hh_count = 0
    lh_count = 0
    for i in range(1, len(recent_highs)):
        if recent_highs[i][1] > recent_highs[i - 1][1]:
            hh_count += 1
            details.append(f"更高高点 HH: {recent_highs[i][1]:.2f}")
        else:
            lh_count += 1
            details.append(f"更低高点 LH: {recent_highs[i][1]:.2f}")

    # 判断低点趋势
    hl_count = 0
    ll_count = 0
    for i in range(1, len(recent_lows)):
        if recent_lows[i][1] > recent_lows[i - 1][1]:
            hl_count += 1
            details.append(f"更高低点 HL: {recent_lows[i][1]:.2f}")
        else:
            ll_count += 1
            details.append(f"更低低点 LL: {recent_lows[i][1]:.2f}")

    # 综合判断
    if hh_count >= lh_count and hl_count >= ll_count and (hh_count + hl_count) > 0:
        trend = "📈 上升趋势 (HH+HL)"
    elif lh_count >= hh_count and ll_count >= hl_count and (lh_count + ll_count) > 0:
        trend = "📉 下降趋势 (LH+LL)"
    else:
        trend = "↔️ 震荡/转折"

    return trend, details


def find_support_resistance(df, highs, lows, price, n_levels=3):
    """找支撑阻力位"""
    # 收集所有关键价位
    all_levels = []
    for d, p in highs:
        all_levels.append(('阻力(前高)', p, d))
    for d, p in lows:
        all_levels.append(('支撑(前低)', p, d))

    # 聚合相近的价位 (±1.5%)
    merged = []
    used = set()
    sorted_levels = sorted(all_levels, key=lambda x: x[1])
    for i, (typ, p, d) in enumerate(sorted_levels):
        if i in used:
            continue
        cluster = [(typ, p, d)]
        for j in range(i + 1, len(sorted_levels)):
            if j in used:
                continue
            if abs(sorted_levels[j][1] - p) / p < 0.015:
                cluster.append(sorted_levels[j])
                used.add(j)
        avg_price = np.mean([x[1] for x in cluster])
        touches = len(cluster)
        merged.append({
            'price': avg_price,
            'touches': touches,
            'type': '支撑' if avg_price < price else '阻力',
            'strength': '强' if touches >= 3 else '中' if touches >= 2 else '弱'
        })

    # 按距离当前价排序, 取最近的
    supports = sorted([m for m in merged if m['type'] == '支撑'],
                      key=lambda x: abs(x['price'] - price))[:n_levels]
    resistances = sorted([m for m in merged if m['type'] == '阻力'],
                         key=lambda x: abs(x['price'] - price))[:n_levels]

    return supports, resistances


def analyze_key_level_reaction(df, supports, resistances):
    """分析价格在关键位的反应"""
    reactions = []
    recent = df.tail(10)

    for s in supports:
        for i in range(len(recent)):
            row = recent.iloc[i]
            if row['Low'] <= s['price'] * 1.005 and row['Close'] > s['price']:
                reactions.append(f"✅ 触及支撑{s['price']:.2f}后反弹(触碰{s['touches']}次,{s['strength']})")
                break
            if row['Close'] < s['price'] * 0.99:
                reactions.append(f"❌ 跌破支撑{s['price']:.2f}(触碰{s['touches']}次)")
                break

    for r in resistances:
        for i in range(len(recent)):
            row = recent.iloc[i]
            if row['High'] >= r['price'] * 0.995 and row['Close'] < r['price']:
                reactions.append(f"🚫 受阻于阻力{r['price']:.2f}(触碰{r['touches']}次,{r['strength']})")
                break
            if row['Close'] > r['price'] * 1.01:
                reactions.append(f"🚀 突破阻力{r['price']:.2f}(触碰{r['touches']}次)")
                break

    return reactions


def recent_momentum(df, n=5):
    """最近N根K线的动量分析"""
    recent = df.tail(n)
    up = 0
    down = 0
    total_body = 0
    avg_vol_20 = df['Volume'].tail(20).mean() if len(df) >= 20 else df['Volume'].mean()

    for i in range(len(recent)):
        row = recent.iloc[i]
        if row['Close'] > row['Open']:
            up += 1
        elif row['Close'] < row['Open']:
            down += 1
        total_body += row['Close'] - row['Open']

    last = df.iloc[-1]
    last_vol = last['Volume']
    vol_ratio = last_vol / avg_vol_20 if avg_vol_20 > 0 else 1

    return {
        'up': up,
        'down': down,
        'doji': n - up - down,
        'net_body': total_body,
        'vol_ratio': vol_ratio,
        'vol_signal': '放量' if vol_ratio > 1.5 else '缩量' if vol_ratio < 0.7 else '正常'
    }


def generate_signal(trend, patterns, supports, resistances, momentum, price):
    """综合裸K信号"""
    score = 0
    reasons = []

    # 趋势 (+/-2)
    if '上升' in trend:
        score += 2
        reasons.append('上升趋势')
    elif '下降' in trend:
        score -= 2
        reasons.append('下降趋势')

    # 最近K线形态 (最近5根)
    recent_patterns = patterns[-5:] if patterns else []
    for _, name, _ in recent_patterns:
        if '看涨' in name or '锤子' in name or '大阳' in name or '倒锤子' in name:
            score += 1
            reasons.append(name.split(' ')[0] + name.split(' ')[1] if ' ' in name else name)
        elif '看跌' in name or '射击' in name or '大阴' in name or '上吊' in name:
            score -= 1
            reasons.append(name.split(' ')[0] + name.split(' ')[1] if ' ' in name else name)

    # 动量
    if momentum['up'] >= 4:
        score += 1
        reasons.append(f"近5根{momentum['up']}阳")
    elif momentum['down'] >= 4:
        score -= 1
        reasons.append(f"近5根{momentum['down']}阴")

    # 成交量
    if momentum['vol_signal'] == '放量' and momentum['net_body'] > 0:
        score += 1
        reasons.append('放量上涨')
    elif momentum['vol_signal'] == '放量' and momentum['net_body'] < 0:
        score -= 1
        reasons.append('放量下跌')

    # 支撑阻力位置
    if supports:
        nearest_sup = supports[0]['price']
        sup_dist = (price - nearest_sup) / price * 100
        if sup_dist < 2:
            score += 1
            reasons.append(f'接近支撑({sup_dist:.1f}%)')

    if resistances:
        nearest_res = resistances[0]['price']
        res_dist = (nearest_res - price) / price * 100
        if res_dist < 2:
            score -= 0.5
            reasons.append(f'接近阻力({res_dist:.1f}%)')

    # 信号
    if score >= 3:
        signal = '🟢 看多'
    elif score >= 1:
        signal = '🟡 偏多'
    elif score <= -3:
        signal = '🔴 看空'
    elif score <= -1:
        signal = '🟠 偏空'
    else:
        signal = '⚪ 中性'

    return signal, score, reasons


def analyze_one(ticker, name=None):
    """分析一只股票"""
    display = name or ticker

    # 日线
    df = fetch_data(ticker, period="1y", interval="1d")
    if df is None or len(df) < 30:
        return f"\n{'='*30}\n{display} — 数据不足\n"

    price = df['Close'].iloc[-1]
    prev_close = df['Close'].iloc[-2]
    change = (price - prev_close) / prev_close * 100
    date = df.index[-1].strftime('%Y-%m-%d')

    # K线形态
    patterns = identify_candle_patterns(df)

    # 摆动高低点
    highs, lows = find_swing_points(df, window=5)

    # 价格结构
    trend, structure_details = analyze_structure(highs, lows)

    # 支撑阻力
    supports, resistances = find_support_resistance(df, highs, lows, price)

    # 关键位反应
    reactions = analyze_key_level_reaction(df, supports, resistances)

    # 动量
    momentum = recent_momentum(df)

    # 综合信号
    signal, score, reasons = generate_signal(trend, patterns, supports, resistances, momentum, price)

    # 输出
    lines = []
    lines.append(f"\n{'='*30}")
    lines.append(f"📊 {display} | {price:.2f} ({change:+.2f}%)")
    lines.append(f"日期: {date}")
    lines.append(f"{'='*30}")

    # 信号
    lines.append(f"\n🎯 裸K信号: {signal} (评分: {score:+.1f})")
    lines.append(f"依据: {', '.join(reasons)}")

    # 价格结构
    lines.append(f"\n📐 价格结构: {trend}")
    for d in structure_details[-4:]:
        lines.append(f"  · {d}")

    # 支撑阻力
    lines.append(f"\n🧱 支撑位:")
    for s in supports:
        dist = (price - s['price']) / price * 100
        lines.append(f"  · {s['price']:.2f} (距离{dist:.1f}%, {s['strength']}, 触碰{s['touches']}次)")
    if not supports:
        lines.append("  · 无明显支撑")

    lines.append(f"🧱 阻力位:")
    for r in resistances:
        dist = (r['price'] - price) / price * 100
        lines.append(f"  · {r['price']:.2f} (距离{dist:.1f}%, {r['strength']}, 触碰{r['touches']}次)")
    if not resistances:
        lines.append("  · 无明显阻力")

    # 关键位反应
    if reactions:
        lines.append(f"\n⚡ 关键位反应:")
        for r in reactions:
            lines.append(f"  · {r}")

    # K线形态 (最近5个)
    recent_p = patterns[-5:] if patterns else []
    if recent_p:
        lines.append(f"\n🕯️ 近期K线形态:")
        for d, name, desc in recent_p:
            d_str = d.strftime('%m-%d') if hasattr(d, 'strftime') else str(d)[:5]
            lines.append(f"  · {d_str} {name} — {desc}")
    else:
        lines.append(f"\n🕯️ 近期无显著K线形态")

    # 动量
    lines.append(f"\n💨 近5日动量: {momentum['up']}阳 {momentum['down']}阴 | 量能: {momentum['vol_signal']}(×{momentum['vol_ratio']:.1f})")

    return '\n'.join(lines)


def main():
    tickers = [
        ('0700.HK', '腾讯'),
        ('1810.HK', '小米'),
        ('NVDA', 'NVDA'),
        ('TSLA', 'TSLA'),
        ('QQQ', 'QQQ'),
        ('9992.HK', '泡泡玛特'),
        ('PDD', 'PDD'),
    ]

    if len(sys.argv) > 1:
        # 支持命令行指定单个ticker
        t = sys.argv[1]
        name = sys.argv[2] if len(sys.argv) > 2 else t
        tickers = [(t, name)]

    print("🔮 裸K (Price Action) 分析报告")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("纯K线分析 · 无指标 · 看价格本身")

    import time
    for ticker, name in tickers:
        try:
            result = analyze_one(ticker, name)
            print(result)
        except Exception as e:
            print(f"\n{'='*30}")
            print(f"❌ {name} ({ticker}) 分析失败: {e}")
        time.sleep(2)

    print(f"\n{'='*30}")
    print("📝 说明: 裸K分析纯主观，仅供参考")
    print("评分: ≥3看多 | 1~2偏多 | 0中性 | -1~-2偏空 | ≤-3看空")


if __name__ == '__main__':
    main()
