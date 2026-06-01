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
import westock_wrapper as yf
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
    # VWAP (Volume Weighted Average Price) - 累积型，对日线无意义，保留作为对比参考
    df['VWAP'] = (df['Close'] * df['Volume']).cumsum() / df['Volume'].cumsum()
    # MACD
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD_DIF'] = ema12 - ema26
    df['MACD_DEA'] = df['MACD_DIF'].ewm(span=9, adjust=False).mean()
    df['MACD_HIST'] = 2 * (df['MACD_DIF'] - df['MACD_DEA'])
    # RSI (14)
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))
    # 布林带 (20, 2)
    df['BOLL_MID'] = df['Close'].rolling(20).mean()
    boll_std = df['Close'].rolling(20).std()
    df['BOLL_UP'] = df['BOLL_MID'] + 2 * boll_std
    df['BOLL_DN'] = df['BOLL_MID'] - 2 * boll_std
    return df


def calc_anchored_vwap(df, anchor_idx):
    """计算从 anchor_idx 开始的 Anchored VWAP
    返回 (vwap_at_latest, vwap_series) 或 (None, None)
    """
    if anchor_idx is None:
        return None, None
    try:
        sliced = df.loc[anchor_idx:].copy()
    except Exception:
        return None, None
    if sliced.empty or 'Volume' not in sliced.columns:
        return None, None
    pv = (sliced['Close'] * sliced['Volume']).cumsum()
    vv = sliced['Volume'].cumsum()
    avwap = pv / vv.replace(0, np.nan)
    if avwap.empty or pd.isna(avwap.iloc[-1]):
        return None, None
    return float(avwap.iloc[-1]), avwap



def _detect_macd_divergence_swing(df, window=5):
    """基于 swing high/low 检测 MACD 背离
    顶背离: 最近两个 swing high 价格升高，但 MACD 柱降低
    底背离: 最近两个 swing low 价格降低，但 MACD 柱升高
    """
    if len(df) < window * 2 + 5:
        return None
    recent = df.tail(60)  # 取近60根找 swing
    if 'MACD_HIST' not in recent.columns:
        return None
    
    # 找 swing high
    swing_highs = []
    for i in range(window, len(recent) - window):
        if recent['High'].iloc[i] == recent['High'].iloc[i - window:i + window + 1].max():
            swing_highs.append((i, recent['High'].iloc[i], recent['MACD_HIST'].iloc[i]))
    
    # 找 swing low
    swing_lows = []
    for i in range(window, len(recent) - window):
        if recent['Low'].iloc[i] == recent['Low'].iloc[i - window:i + window + 1].min():
            swing_lows.append((i, recent['Low'].iloc[i], recent['MACD_HIST'].iloc[i]))
    
    # 顶背离: 最近两个 swing high
    if len(swing_highs) >= 2:
        sh1 = swing_highs[-2]
        sh2 = swing_highs[-1]
        if sh2[1] > sh1[1] and sh2[2] < sh1[2]:  # 价格高了，MACD柱低了
            return '🔴顶背离'
    
    # 底背离: 最近两个 swing low
    if len(swing_lows) >= 2:
        sl1 = swing_lows[-2]
        sl2 = swing_lows[-1]
        if sl2[1] < sl1[1] and sl2[2] > sl1[2]:  # 价格低了，MACD柱高了
            return '🟢底背离'
    
    return None


def detect_macd_signal(df):
    """检测MACD信号: 金叉/死叉 + 零轴上下 + 背离"""
    recent = df.dropna(subset=['MACD_DIF', 'MACD_DEA']).tail(20)
    if len(recent) < 5:
        return {}
    
    latest = recent.iloc[-1]
    prev = recent.iloc[-2]
    dif = latest['MACD_DIF']
    dea = latest['MACD_DEA']
    hist = latest['MACD_HIST']
    prev_dif = prev['MACD_DIF']
    prev_dea = prev['MACD_DEA']
    
    # 金叉/死叉
    cross = None
    if prev_dif <= prev_dea and dif > dea:
        cross = '金叉' if dif > 0 else '水下金叉'
    elif prev_dif >= prev_dea and dif < dea:
        cross = '死叉' if dif < 0 else '水上死叉'
    
    # 零轴位置
    zone = '零轴上' if dif > 0 else '零轴下'
    
    # 柱状图方向
    hist_dir = '红柱' if hist > 0 else '绿柱'
    hist_trend = '放大' if abs(hist) > abs(prev['MACD_HIST']) else '缩小'
    
    # 背离检测 - 基于 swing high/low 的 MACD 柱对比
    divergence = None
    try:
        divergence = _detect_macd_divergence_swing(df, window=5)
    except Exception:
        divergence = None
    
    return {
        'dif': dif, 'dea': dea, 'hist': hist,
        'cross': cross, 'zone': zone,
        'hist_dir': hist_dir, 'hist_trend': hist_trend,
        'divergence': divergence,
    }


def detect_volume_price(df):
    """量价关系检测"""
    recent = df.tail(20)
    if len(recent) < 5:
        return {}
    
    latest = recent.iloc[-1]
    prev = recent.iloc[-2]
    avg_vol = recent['Volume'].mean()  # VOLMA20
    
    # 量能倍数
    vol_ratio = latest['Volume'] / avg_vol if avg_vol > 0 else 1.0
    
    # 量价背离
    vp_divergence = None
    prices = recent['Close'].values
    vols = recent['Volume'].values
    
    # 价涨量缩 (涨势疑似衰竭)
    if prices[-1] > prices[-3] and vols[-1] < vols[-3] * 0.7:
        vp_divergence = 'ℹ️价涨量缩'
    # 价跌量增 (恐慌抛售)
    elif prices[-1] < prices[-3] and vols[-1] > vols[-3] * 1.5:
        vp_divergence = '⚠️价跌量增'
    # 缩量下跌 (空头衰竭)
    elif prices[-1] < prices[-3] and vols[-1] < vols[-3] * 0.5:
        vp_divergence = '🟢缩量下跌'
    
    return {
        'vol_ratio': vol_ratio,
        'vp_divergence': vp_divergence,
    }


def detect_engulfing(df):
    """穿头破脚检测 (吸收形态)"""
    if len(df) < 2:
        return None
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    o, c = latest['Open'], latest['Close']
    po, pc = prev['Open'], prev['Close']
    body = abs(c - o)
    prev_body = abs(pc - po)
    
    # 看涨吸收 (Bullish Engulfing)
    if c > o and pc < po and c > po and o < pc and body > prev_body:
        return '🟢看涨吸收'
    
    # 看跌吸收 (Bearish Engulfing)
    if c < o and pc > po and c < po and o > pc and body > prev_body:
        return '🔴看跌吸收'
    
    return None



def detect_pin_bar(df, body_ratio=0.3, tail_ratio=2.0):
    """Pin Bar 检测 (街哥 EP.33/37/50)
    看跌Pin: 长上影线, 小实体在底部 → 上方压力大
    看涨Pin: 长下影线, 小实体在顶部 → 下方支撑强
    """
    if len(df) < 2:
        return None
    latest = df.iloc[-1]
    o, c, h, l = latest['Open'], latest['Close'], latest['High'], latest['Low']
    body = abs(c - o)
    range_hl = h - l
    if range_hl == 0 or body > range_hl * 0.5:
        return None

    upper_shadow = h - max(o, c)
    lower_shadow = min(o, c) - l

    if upper_shadow > body * tail_ratio and upper_shadow > lower_shadow * 1.5:
        return '📌看跌Pin'

    if lower_shadow > body * tail_ratio and lower_shadow > upper_shadow * 1.5:
        return '📌看涨Pin'

    return None


def detect_doji(df, body_ratio=0.1):
    """十字星检测 (街哥 EP.50)"""
    if len(df) < 2:
        return None
    latest = df.iloc[-1]
    o, c, h, l = latest['Open'], latest['Close'], latest['High'], latest['Low']
    body = abs(c - o)
    range_hl = h - l
    if range_hl == 0:
        return None

    if body < range_hl * body_ratio:
        upper = h - max(o, c)
        lower = min(o, c) - l
        if upper > lower * 2:
            return '⚡墓碑十字(偏空)'
        elif lower > upper * 2:
            return '⚡蜻蜓十字(偏多)'
        else:
            return '⚡十字星'
    return None


def detect_hammer_shooting_star(df):
    """锤子线/射击之星 (街哥 EP.33)"""
    if len(df) < 2:
        return None
    latest = df.iloc[-1]
    o, c, h, l = latest['Open'], latest['Close'], latest['High'], latest['Low']
    body = abs(c - o)
    range_hl = h - l
    if range_hl == 0:
        return None

    upper = h - max(o, c)
    lower = min(o, c) - l

    if lower > body * 2 and upper < body * 0.5 and c > o:
        return '🟢锤子线'

    if upper > body * 2 and lower < body * 0.5 and c < o:
        return '🔴射击之星'

    return None


def detect_morning_evening_star(df):
    """早晨星/黄昏星 (三K线反转)"""
    if len(df) < 3:
        return None
    c3, c2, c1 = df.iloc[-3], df.iloc[-2], df.iloc[-1]

    if (c3['Close'] > c3['Open'] and
        abs(c2['Close'] - c2['Open']) < (c2['High'] - c2['Low']) * 0.3 and
        c1['Close'] < c1['Open'] and
        c1['Close'] < c3['Open']):
        return '🔴黄昏星'

    if (c3['Close'] < c3['Open'] and
        abs(c2['Close'] - c2['Open']) < (c2['High'] - c2['Low']) * 0.3 and
        c1['Close'] > c1['Open'] and
        c1['Close'] > c3['Open']):
        return '🟢早晨星'

    return None


def detect_volume_profile(df, lookback=60, bins=20):
    """筹码分布分析 (街哥 EP.13/19)
    基于成交量分布找出筹码密集区和真空区
    """
    recent = df.tail(lookback)
    if len(recent) < 10:
        return {}

    prices = recent['Close'].values
    volumes = recent['Volume'].values

    price_min, price_max = prices.min(), prices.max()
    if price_max == price_min:
        return {}

    bin_edges = np.linspace(price_min, price_max, bins + 1)
    vol_profile = np.zeros(bins)

    for i in range(len(prices)):
        for j in range(bins):
            if bin_edges[j] <= prices[i] <= bin_edges[j + 1]:
                vol_profile[j] += volumes[i]
                break

    avg_vol = vol_profile.mean()
    concentration_bins = np.where(vol_profile > avg_vol * 1.5)[0]

    zones = []
    if len(concentration_bins) > 0:
        groups = []
        current_group = [concentration_bins[0]]
        for b in concentration_bins[1:]:
            if b == current_group[-1] + 1:
                current_group.append(b)
            else:
                groups.append(current_group)
                current_group = [b]
        groups.append(current_group)

        for g in groups:
            zone_price = np.mean([bin_edges[g[0]], bin_edges[g[-1] + 1]])
            zone_vol = vol_profile[g].sum()
            strength = "极强" if zone_vol > avg_vol * 3 else ("强" if zone_vol > avg_vol * 2 else "中等")
            dist_pct = ((zone_price - prices[-1]) / prices[-1]) * 100
            zones.append({
                'price': round(zone_price, 2),
                'volume': round(zone_vol),
                'strength': strength,
                'dist_pct': round(dist_pct, 1),
                'direction': '上方' if zone_price > prices[-1] else '下方',
            })

    total_vol = vol_profile.sum()
    if total_vol > 0:
        avg_holding = np.sum(
            [(bin_edges[i] + bin_edges[i+1]) / 2 * vol_profile[i] for i in range(bins)]
        ) / total_vol
    else:
        avg_holding = prices[-1]

    current_price = prices[-1]
    profit_pct = ((current_price - avg_holding) / avg_holding) * 100

    return {
        'concentration_zones': zones,
        'avg_holding_price': round(avg_holding, 2),
        'profit_pct': round(profit_pct, 1),
        'market_sentiment': '获利盘' if profit_pct > 0 else '套牢盘',
    }


def detect_kline_patterns(df):
    """综合K线形态检测 (街哥核心理念)"""
    results = []

    eng = detect_engulfing(df)
    if eng:
        results.append(eng)

    pin = detect_pin_bar(df)
    if pin:
        results.append(pin)

    doj = detect_doji(df)
    if doj:
        results.append(doj)

    hs = detect_hammer_shooting_star(df)
    if hs:
        results.append(hs)

    mes = detect_morning_evening_star(df)
    if mes:
        results.append(mes)

    return results


def detect_rsi_signal(df):
    """RSI 超买超卖检测"""
    recent = df.dropna(subset=['RSI']).tail(5)
    if len(recent) < 3:
        return {}
    
    latest = recent.iloc[-1]
    rsi = latest['RSI']
    
    signal = None
    if rsi >= 70:
        signal = '⚠️超买'
    elif rsi <= 30:
        signal = '🟢超卖'
    elif rsi >= 50:
        signal = '偏强'
    else:
        signal = '偏弱'
    
    return {'rsi': rsi, 'signal': signal}


def detect_boll_signal(df):
    """布林带突破检测"""
    recent = df.dropna(subset=['BOLL_UP', 'BOLL_DN']).tail(5)
    if len(recent) < 3:
        return {}
    
    latest = recent.iloc[-1]
    prev = recent.iloc[-2]
    close = latest['Close']
    boll_up = latest['BOLL_UP']
    boll_mid = latest['BOLL_MID']
    boll_dn = latest['BOLL_DN']
    
    signal = None
    # 突破上轨
    if prev['Close'] <= prev['BOLL_UP'] and close > boll_up:
        signal = '🔴突破上轨'
    # 跌破下轨
    elif prev['Close'] >= prev['BOLL_DN'] and close < boll_dn:
        signal = '🟢跌破下轨'
    # 中轨附近
    elif abs(close - boll_mid) / boll_mid < 0.01:
        signal = '中轨附近'
    # 上轨附近
    elif close > boll_mid and (boll_up - close) / (boll_up - boll_mid) < 0.3:
        signal = '接近上轨'
    # 下轨附近
    elif close < boll_mid and (close - boll_dn) / (boll_mid - boll_dn) < 0.3:
        signal = '接近下轨'
    
    return {
        'boll_up': boll_up,
        'boll_mid': boll_mid,
        'boll_dn': boll_dn,
        'signal': signal,
    }


def detect_vegas_tunnel(df):
    """维加斯通道 (街哥 EP.46)
    EMA144 / EMA169 = 通道; EMA12 = 过滤线
    - 价格在通道上方 + EMA12 > 通道 → 多头趋势
    - 价格在通道下方 + EMA12 < 通道 → 空头趋势
    - 价格穿越通道 → 趋势变化
    """
    if len(df) < 170:
        return {}
    e12 = df['Close'].ewm(span=12, adjust=False).mean()
    e144 = df['Close'].ewm(span=144, adjust=False).mean()
    e169 = df['Close'].ewm(span=169, adjust=False).mean()
    close = float(df['Close'].iloc[-1])
    v12 = float(e12.iloc[-1])
    v144 = float(e144.iloc[-1])
    v169 = float(e169.iloc[-1])
    tunnel_top = max(v144, v169)
    tunnel_bot = min(v144, v169)
    width_pct = (tunnel_top - tunnel_bot) / tunnel_bot * 100 if tunnel_bot else 0

    if close > tunnel_top and v12 > tunnel_top:
        position = '🟢通道上方'
        trend = '多头趋势'
    elif close < tunnel_bot and v12 < tunnel_bot:
        position = '🔴通道下方'
        trend = '空头趋势'
    elif tunnel_bot <= close <= tunnel_top:
        position = '⚡通道内'
        trend = '震荡/转折'
    elif close > tunnel_top and v12 < tunnel_top:
        position = '⚠️价上EMA12下'
        trend = '上方背离/警惕回落'
    elif close < tunnel_bot and v12 > tunnel_bot:
        position = '⚠️价下EMA12上'
        trend = '下方背离/警惕反弹'
    else:
        position = '边界附近'
        trend = '不明'

    # 趋势变化检测: 最近5根K线是否首次穿越
    cross = None
    if len(df) >= 5:
        prev_close = float(df['Close'].iloc[-2])
        prev_top = float(max(e144.iloc[-2], e169.iloc[-2]))
        prev_bot = float(min(e144.iloc[-2], e169.iloc[-2]))
        if prev_close <= prev_top and close > tunnel_top:
            cross = '🟢上破通道'
        elif prev_close >= prev_bot and close < tunnel_bot:
            cross = '🔴下破通道'

    return {
        'ema12': v12,
        'ema144': v144,
        'ema169': v169,
        'tunnel_top': tunnel_top,
        'tunnel_bot': tunnel_bot,
        'width_pct': round(width_pct, 2),
        'position': position,
        'trend': trend,
        'cross': cross,
        'dist_to_top_pct': round((close - tunnel_top) / tunnel_top * 100, 2),
        'dist_to_bot_pct': round((close - tunnel_bot) / tunnel_bot * 100, 2),
    }


def detect_open_price_system(df, tf_label='日线'):
    """周/月/年线开盘价系统 (街哥 EP.24/25/50「刻舟求剑」)
    用日线数据反推: 本周一开盘价 / 本月首日开盘价 / 本年首日开盘价
    价格在开盘价上方/下方 = 该周期多/空
    仅在日线数据上有意义, 周线/4h 数据返回空
    """
    if tf_label != '日线' or len(df) < 5:
        return {}
    if not isinstance(df.index, pd.DatetimeIndex):
        return {}
    latest_date = df.index[-1]
    close = float(df['Close'].iloc[-1])

    # 本周开盘价 (周一)
    week_start = latest_date - pd.Timedelta(days=latest_date.weekday())
    week_data = df[df.index >= week_start]
    week_open = float(week_data['Open'].iloc[0]) if len(week_data) else None

    # 本月开盘价
    month_start = latest_date.replace(day=1)
    month_data = df[df.index >= month_start]
    month_open = float(month_data['Open'].iloc[0]) if len(month_data) else None

    # 本年开盘价
    year_start = latest_date.replace(month=1, day=1)
    year_data = df[df.index >= year_start]
    year_open = float(year_data['Open'].iloc[0]) if len(year_data) else None

    def _judge(open_p):
        if open_p is None:
            return None, None
        diff_pct = (close - open_p) / open_p * 100
        if abs(diff_pct) < 0.5:
            sig = '⚡持平'
        elif close > open_p:
            sig = '🟢上方(多)'
        else:
            sig = '🔴下方(空)'
        return open_p, (diff_pct, sig)

    return {
        'week_open': week_open,
        'week': _judge(week_open)[1],
        'month_open': month_open,
        'month': _judge(month_open)[1],
        'year_open': year_open,
        'year': _judge(year_open)[1],
    }


def detect_ichimoku(df):
    """一目均衡表 (9/26/52/26 经典参数)
    Tenkan(转换线)=9周期(H+L)/2, Kijun(基准线)=26周期
    Senkou A=(Tenkan+Kijun)/2 前移26, Senkou B=52周期(H+L)/2 前移26
    Chikou=Close 后移26
    """
    if len(df) < 60:
        return {}
    high9 = df['High'].rolling(9).max()
    low9 = df['Low'].rolling(9).min()
    tenkan = (high9 + low9) / 2
    high26 = df['High'].rolling(26).max()
    low26 = df['Low'].rolling(26).min()
    kijun = (high26 + low26) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    high52 = df['High'].rolling(52).max()
    low52 = df['Low'].rolling(52).min()
    senkou_b = ((high52 + low52) / 2).shift(26)

    close = float(df['Close'].iloc[-1])
    t = tenkan.iloc[-1]
    k = kijun.iloc[-1]
    sa = senkou_a.iloc[-1]
    sb = senkou_b.iloc[-1]
    if pd.isna(t) or pd.isna(k) or pd.isna(sa) or pd.isna(sb):
        return {}
    cloud_top = max(sa, sb)
    cloud_bot = min(sa, sb)

    if close > cloud_top:
        cloud_pos = '🟢云上(多头)'
    elif close < cloud_bot:
        cloud_pos = '🔴云下(空头)'
    else:
        cloud_pos = '⚡云中(震荡)'

    if t > k:
        tk_cross = '🟢转换>基准'
    elif t < k:
        tk_cross = '🔴转换<基准'
    else:
        tk_cross = '持平'

    cloud_color = '🟢绿云' if sa > sb else '🔴红云'

    return {
        'tenkan': float(t),
        'kijun': float(k),
        'senkou_a': float(sa),
        'senkou_b': float(sb),
        'cloud_top': float(cloud_top),
        'cloud_bot': float(cloud_bot),
        'cloud_pos': cloud_pos,
        'tk_cross': tk_cross,
        'cloud_color': cloud_color,
    }


def detect_obv(df, lookback=30):
    """OBV 能量潮 + 背离检测
    OBV[i] = OBV[i-1] + (Volume[i] if Close[i]>Close[i-1] else -Volume[i] if Close[i]<Close[i-1] else 0)
    顶背离: 价格新高但 OBV 没新高 → 资金不跟
    底背离: 价格新低但 OBV 没新低 → 资金未离场
    """
    if len(df) < lookback + 5 or 'Volume' not in df.columns:
        return {}
    close_diff = df['Close'].diff()
    direction = np.where(close_diff > 0, 1, np.where(close_diff < 0, -1, 0))
    obv = (direction * df['Volume']).cumsum()
    recent_obv = obv.tail(lookback)
    recent_close = df['Close'].tail(lookback)

    # 简单趋势比对
    obv_change = (recent_obv.iloc[-1] - recent_obv.iloc[0])
    price_change_pct = (recent_close.iloc[-1] - recent_close.iloc[0]) / recent_close.iloc[0] * 100

    # 背离: 价格创新高 vs OBV 是否创新高
    divergence = None
    n = lookback
    if len(df) >= n:
        price_window = df['Close'].tail(n)
        obv_window = obv.tail(n)
        # 顶背离: 价格新高 + OBV 不创新高
        if price_window.iloc[-1] >= price_window.max() * 0.995:
            obv_max_idx = obv_window.idxmax()
            if obv_max_idx != obv_window.index[-1]:
                divergence = '🔴OBV顶背离'
        # 底背离: 价格新低 + OBV 不创新低
        elif price_window.iloc[-1] <= price_window.min() * 1.005:
            obv_min_idx = obv_window.idxmin()
            if obv_min_idx != obv_window.index[-1]:
                divergence = '🟢OBV底背离'

    if obv_change > 0 and price_change_pct > 0:
        trend = '量价齐升'
    elif obv_change < 0 and price_change_pct < 0:
        trend = '量价齐跌'
    elif obv_change > 0 and price_change_pct < 0:
        trend = '⚠️OBV上涨/价跌(资金抄底?)'
    elif obv_change < 0 and price_change_pct > 0:
        trend = '⚠️OBV下跌/价涨(资金离场?)'
    else:
        trend = '量价中性'

    return {
        'obv_latest': float(obv.iloc[-1]),
        'obv_change_pct': round(float(obv_change / abs(recent_obv.iloc[0])) * 100, 1) if recent_obv.iloc[0] else None,
        'price_change_pct': round(price_change_pct, 1),
        'trend': trend,
        'divergence': divergence,
    }


def detect_fixed_range_vp(df, lookback=60, bins=24, va_pct=0.70):
    """固定区间成交量分布 (Fixed Range Volume Profile)
    POC = 成交最大的价格区间 (Point of Control)
    VAH/VAL = 70% 成交量构成的价格区间上下沿 (Value Area High/Low)
    """
    recent = df.tail(lookback)
    if len(recent) < 10 or 'Volume' not in recent.columns:
        return {}
    prices = recent['Close'].values
    volumes = recent['Volume'].values
    p_min, p_max = prices.min(), prices.max()
    if p_max == p_min:
        return {}

    edges = np.linspace(p_min, p_max, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    vp = np.zeros(bins)
    for i in range(len(prices)):
        for j in range(bins):
            if edges[j] <= prices[i] <= edges[j + 1]:
                vp[j] += volumes[i]
                break

    total = vp.sum()
    if total == 0:
        return {}

    poc_idx = int(np.argmax(vp))
    poc = float(centers[poc_idx])

    # Value Area: 从 POC 向两侧扩展, 直到累积成交量 >= va_pct
    target = total * va_pct
    cumulated = vp[poc_idx]
    lo, hi = poc_idx, poc_idx
    while cumulated < target and (lo > 0 or hi < bins - 1):
        left_v = vp[lo - 1] if lo > 0 else -1
        right_v = vp[hi + 1] if hi < bins - 1 else -1
        if left_v >= right_v:
            if lo > 0:
                lo -= 1
                cumulated += vp[lo]
            else:
                hi += 1
                cumulated += vp[hi]
        else:
            if hi < bins - 1:
                hi += 1
                cumulated += vp[hi]
            else:
                lo -= 1
                cumulated += vp[lo]

    val = float(centers[lo])
    vah = float(centers[hi])
    close = float(prices[-1])

    if close > vah:
        position = '🔴价值区上方'
    elif close < val:
        position = '🟢价值区下方'
    else:
        position = '⚡价值区内'

    return {
        'poc': round(poc, 2),
        'vah': round(vah, 2),
        'val': round(val, 2),
        'position': position,
        'lookback': lookback,
        'poc_dist_pct': round((close - poc) / poc * 100, 2),
    }


def detect_inside_bar(df):
    """双孕线/inside bar/harami (街哥 EP.33)
    定义: 当前K线被上一根K线完全包含 (high<prev_high AND low>prev_low)
    意义: 多空僵持 → 突破方向决定后续
    """
    if len(df) < 3:
        return None
    last = df.iloc[-1]
    prev = df.iloc[-2]
    if last['High'] < prev['High'] and last['Low'] > prev['Low']:
        # 颜色判断
        prev_bull = prev['Close'] > prev['Open']
        last_bull = last['Close'] > last['Open']
        if prev_bull and not last_bull:
            return '🟡孕线(阳孕阴)'
        elif not prev_bull and last_bull:
            return '🟡孕线(阴孕阳)'
        else:
            return '🟡双孕线'
    return None


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

    # VWAP 分析 (累积型，参考用)
    vwap = latest['VWAP'] if 'VWAP' in latest else None
    vwap_position = None
    vwap_dist = None
    if vwap and not pd.isna(vwap):
        vwap_dist = (close - vwap) / vwap * 100
        if close > vwap:
            vwap_position = "上方" if vwap_dist > 1 else "接近"
        else:
            vwap_position = "下方" if vwap_dist < -1 else "接近"
    
    # Anchored VWAP - 锚定 swing low / swing high
    avwap_low_val, avwap_low_series = calc_anchored_vwap(valid, low_date)
    avwap_high_val, avwap_high_series = calc_anchored_vwap(valid, high_date)
    avwap_info = {
        'low': avwap_low_val,
        'low_anchor': low_date,
        'low_dist_pct': (close - avwap_low_val) / avwap_low_val * 100 if avwap_low_val else None,
        'low_pos': ('上方' if avwap_low_val and close > avwap_low_val else '下方') if avwap_low_val else None,
        'high': avwap_high_val,
        'high_anchor': high_date,
        'high_dist_pct': (close - avwap_high_val) / avwap_high_val * 100 if avwap_high_val else None,
        'high_pos': ('上方' if avwap_high_val and close > avwap_high_val else '下方') if avwap_high_val else None,
    }
    
    # MACD 分析
    macd_info = detect_macd_signal(valid)
    
    # 量价关系
    vp_info = detect_volume_price(valid)
    
    # K线形态 (穿头破脚 + Pin Bar + 十字星 + 锤子线 + 早晨/黄昏星)
    kline_patterns = detect_kline_patterns(valid)
    engulfing = kline_patterns[0] if kline_patterns else None
    
    # 筹码分布 (街哥 EP.13/19)
    vol_profile = detect_volume_profile(valid)

    # RSI
    rsi_info = detect_rsi_signal(valid)
    
    # 布林带
    boll_info = detect_boll_signal(valid)

    # 维加斯通道 (街哥 EP.46) - 需要足够数据算 EMA169
    vegas_info = detect_vegas_tunnel(valid)
    # 周/月/年线开盘价系统 (街哥 EP.24/25/50) - 仅日线有意义
    open_sys_info = detect_open_price_system(valid, tf_label)
    # 一目均衡表
    ichimoku_info = detect_ichimoku(valid)
    # OBV 能量潮
    obv_info = detect_obv(valid)
    # 固定区间成交量分布 POC/VAH/VAL
    frvp_info = detect_fixed_range_vp(valid)
    # 双孕线 inside bar (街哥 EP.33)
    inside_bar = detect_inside_bar(valid)

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
        # VWAP
        'vwap': vwap,
        'vwap_position': vwap_position,
        'vwap_dist': vwap_dist,
        # Anchored VWAP
        'avwap': avwap_info,
        # MACD
        'macd': macd_info,
        # 量价
        'vp': vp_info,
        # K线形态
        'kline_patterns': kline_patterns,
        'engulfing': engulfing,
        # 筹码分布
        'vol_profile': vol_profile,
        # RSI
        'rsi': rsi_info,
        # 布林带
        'boll': boll_info,
        # 维加斯通道
        'vegas': vegas_info,
        # 开盘价系统
        'open_sys': open_sys_info,
        # 一目均衡表
        'ichimoku': ichimoku_info,
        # OBV
        'obv': obv_info,
        # 固定区间成交量分布
        'frvp': frvp_info,
        # 双孕线
        'inside_bar': inside_bar,
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
    if signal == 'sell' or (signal == 'wait' and is_conv):
        fbd_sig, fbd_det = detect_fake_breakdown(valid)
        result['fbd_signal'] = fbd_sig
        result['fbd_detail'] = fbd_det
        if fbd_sig:
            result['signal'] = 'buy'
            signal = 'buy'  # 假跌破确认，升级为买入

    # 加权评分 (汇总多因子)
    result['weighted_score'] = compute_weighted_score(result)

    return result


def compute_weighted_score(r):
    """加权汇总打分：
    - MACD 背离 = ±2 分
    - 六线密集 + 回踩确认 = +2 分
    - 回踩中 = +1 分
    - 假突破 = -2；假跌破 = +2
    - RSI 超买/超卖 = ±1
    - 量比>1.5 且价涨 = +1；量比>1.5 且价跌 = -1
    - Anchored VWAP 偏离（距离 swing low AVWAP）= ±0.5
    - 看涨吞没 = +1；看跌吞没 = -1
    - 布林突破上轨 = +0.5；跌破下轨 = -0.5
    返回 (total_score, reasons)
    """
    score = 0.0
    reasons = []

    # MACD 背离
    macd = r.get('macd') or {}
    if macd.get('divergence'):
        if '底背离' in macd['divergence']:
            score += 2
            reasons.append('MACD底背离+2')
        elif '顶背离' in macd['divergence']:
            score -= 2
            reasons.append('MACD顶背离-2')
    # MACD 金叉/死叉
    if macd.get('cross'):
        if '金叉' in macd['cross']:
            score += 1
            reasons.append(f"MACD{macd['cross']}+1")
        elif '死叉' in macd['cross']:
            score -= 1
            reasons.append(f"MACD{macd['cross']}-1")

    # 密集 + 回踩
    if r.get('is_conv') and r.get('k_above'):
        if r.get('pb_signal'):
            score += 2
            reasons.append('密集+回踩确认+2')
        else:
            score += 1
            reasons.append('密集上方+1')
    elif r.get('is_conv') and not r.get('k_above'):
        score -= 1
        reasons.append('密集下方-1')

    # 假突破/假跌破
    if r.get('fb_signal'):
        score -= 2
        reasons.append('假突破-2')
    if r.get('fbd_signal'):
        score += 2
        reasons.append('假跌破+2')

    # RSI
    rsi = r.get('rsi') or {}
    rsi_sig = rsi.get('signal', '')
    if '超卖' in rsi_sig:
        score += 1
        reasons.append('RSI超卖+1')
    elif '超买' in rsi_sig:
        score -= 1
        reasons.append('RSI超买-1')

    # 量价
    vp = r.get('vp') or {}
    vol_ratio = vp.get('vol_ratio', 1.0)
    if vol_ratio > 1.5:
        # 需要配合价格方向
        if r.get('k_above'):
            score += 1
            reasons.append(f'放量上涨(×{vol_ratio:.1f})+1')
        else:
            score -= 1
            reasons.append(f'放量下跌(×{vol_ratio:.1f})-1')

    # Anchored VWAP
    avwap = r.get('avwap') or {}
    if avwap.get('low_dist_pct') is not None:
        ld = avwap['low_dist_pct']
        if ld > 5:
            score += 0.5
            reasons.append(f'价高于AVWAP_LOW {ld:.1f}%+0.5')
        elif ld < -5:
            score -= 0.5
            reasons.append(f'价低于AVWAP_LOW {ld:.1f}%-0.5')

    # K线形态综合评分
    patterns = r.get('kline_patterns') or []
    for p in patterns:
        if any(k in p for k in ['看涨吞没', '看涨Pin', '锤子线', '早晨星', '蜻蜓十字']):
            score += 1
            reasons.append(f'{p}+1')
        elif any(k in p for k in ['看跌吞没', '看跌Pin', '射击之星', '黄昏星', '墓碑十字']):
            score -= 1
            reasons.append(f'{p}-1')
        elif '十字星' in p or '标准十字' in p:
            reasons.append(f'{p}(犹豫)')

    # 筹码分布
    vprof = r.get('vol_profile') or {}
    if vprof.get('concentration_zones'):
        for z in vprof['concentration_zones']:
            if z['direction'] == '下方' and z['strength'] in ['极强', '强']:
                score += 0.5
                reasons.append(f"筹码支撑{z['price']}(强)+0.5")
            elif z['direction'] == '上方' and z['strength'] in ['极强', '强']:
                score -= 0.5
                reasons.append(f"筹码压力{z['price']}(强)-0.5")
    if vprof.get('profit_pct') is not None:
        pp = vprof['profit_pct']
        if pp > 10:
            score -= 0.5
            reasons.append(f'获利盘{pp:.0f}%+抛压-0.5')
        elif pp < -10:
            score += 0.5
            reasons.append(f'套牢盘{abs(pp):.0f}%+反弹+0.5')

    # 布林带
    boll = r.get('boll') or {}
    bs = boll.get('signal')
    if bs == '🔴突破上轨':
        score += 0.5
        reasons.append('突破上轨+0.5')
    elif bs == '🟢跌破下轨':
        score -= 0.5
        reasons.append('跌破下轨-0.5')

    return {'score': round(score, 2), 'reasons': reasons}



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
    
    # VWAP
    if buy_r.get('vwap') and not pd.isna(buy_r['vwap']):
        vwap_val = buy_r['vwap']
        vwap_pos = buy_r['vwap_position']
        vwap_dist = buy_r['vwap_dist']
        print(f"  VWAP    : {vwap_val:.2f} (价格在{vwap_pos}, {vwap_dist:+.2f}%)")
    
    # Anchored VWAP
    avwap = buy_r.get('avwap') or {}
    if avwap.get('low') is not None:
        anchor_date = avwap['low_anchor'].strftime('%m-%d') if hasattr(avwap['low_anchor'], 'strftime') else str(avwap['low_anchor'])[:10]
        print(f"  AVWAP_LOW : {avwap['low']:.2f} (锚{anchor_date}swing low, 价在{avwap['low_pos']}, {avwap['low_dist_pct']:+.2f}%)")
    if avwap.get('high') is not None:
        anchor_date = avwap['high_anchor'].strftime('%m-%d') if hasattr(avwap['high_anchor'], 'strftime') else str(avwap['high_anchor'])[:10]
        print(f"  AVWAP_HIGH: {avwap['high']:.2f} (锚{anchor_date}swing high, 价在{avwap['high_pos']}, {avwap['high_dist_pct']:+.2f}%)")
    
    # 加权评分
    ws = buy_r.get('weighted_score') or {}
    if ws and ws.get('reasons'):
        print(f"\n🎯 加权评分 [{buy_r['tf']}]: {ws.get('score', 0):+.1f}")
        print(f"  因子: {' / '.join(ws['reasons'])}")
    
    # MACD
    macd = buy_r.get('macd', {})
    if macd:
        print(f"\n📊 MACD [{buy_r['tf']}]")
        print(f"  DIF: {macd.get('dif', 0):.2f} | DEA: {macd.get('dea', 0):.2f} | 柱: {macd.get('hist', 0):.2f}")
        parts = []
        if macd.get('cross'):
            parts.append(macd['cross'])
        parts.append(macd.get('zone', ''))
        parts.append(f"{macd.get('hist_dir', '')}{macd.get('hist_trend', '')}")
        if macd.get('divergence'):
            parts.append(macd['divergence'])
        print(f"  {' | '.join(parts)}")
    
    # 量价关系
    vp = buy_r.get('vp', {})
    if vp:
        print(f"\n📊 量价关系 [{buy_r['tf']}]")
        vol_ratio = vp.get('vol_ratio', 1.0)
        print(f"  量能: ×{vol_ratio:.1f}")
        if vp.get('vp_divergence'):
            print(f"  {vp['vp_divergence']}")
    
    # K线形态
    patterns = buy_r.get('kline_patterns') or []
    if patterns:
        print(f"\n🎆 K线形态: {' / '.join(patterns)}")

    # 筹码分布
    vprof = buy_r.get('vol_profile') or {}
    if vprof:
        print(f"\n📊 筹码分布 [{buy_r['tf']}]")
        print(f"  平均持仓成本: {vprof.get('avg_holding_price', 'N/A')} | {'获利盘' if vprof.get('profit_pct', 0) > 0 else '套牢盘'} {abs(vprof.get('profit_pct', 0)):.1f}%")
        zones = vprof.get('concentration_zones', [])
        if zones:
            print(f"  筹码密集区:")
            for z in zones[:4]:
                print(f"    {z['price']} ({z['strength']}, {z['direction']}, 距{abs(z['dist_pct'])}%)")
    
    # RSI
    rsi = buy_r.get('rsi', {})
    if rsi:
        print(f"\n📊 RSI [{buy_r['tf']}]")
        rsi_val = rsi.get('rsi', 50)
        rsi_sig = rsi.get('signal', '')
        print(f"  RSI: {rsi_val:.1f} ({rsi_sig})")
    
    # 布林带
    boll = buy_r.get('boll', {})
    if boll and boll.get('signal'):
        print(f"\n📊 布林带 [{buy_r['tf']}]")
        print(f"  上轨: {boll['boll_up']:.2f}")
        print(f"  中轨: {boll['boll_mid']:.2f}")
        print(f"  下轨: {boll['boll_dn']:.2f}")
        print(f"  信号: {boll['signal']}")

    # 维加斯通道 (街哥 EP.46)
    vegas = buy_r.get('vegas', {})
    if vegas:
        print(f"\n🛣️ 维加斯通道 [{buy_r['tf']}]")
        print(f"  通道: EMA144 {vegas['ema144']:.2f} / EMA169 {vegas['ema169']:.2f} (宽{vegas['width_pct']}%)")
        print(f"  EMA12: {vegas['ema12']:.2f} | {vegas['position']} | {vegas['trend']}")
        if vegas.get('cross'):
            print(f"  ⚡ {vegas['cross']}")

    # 开盘价系统 (街哥 EP.24/25/50 刻舟求剑)
    osys = buy_r.get('open_sys', {})
    if osys and osys.get('week_open'):
        print(f"\n📍 开盘价系统 [{buy_r['tf']}] (刻舟求剑)")
        if osys.get('week_open') and osys.get('week'):
            print(f"  周开: {osys['week_open']:.2f} ({osys['week'][1]}, {osys['week'][0]:+.1f}%)")
        if osys.get('month_open') and osys.get('month'):
            print(f"  月开: {osys['month_open']:.2f} ({osys['month'][1]}, {osys['month'][0]:+.1f}%)")
        if osys.get('year_open') and osys.get('year'):
            print(f"  年开: {osys['year_open']:.2f} ({osys['year'][1]}, {osys['year'][0]:+.1f}%)")

    # 一目均衡表
    ichi = buy_r.get('ichimoku', {})
    if ichi:
        print(f"\n☁️ 一目均衡表 [{buy_r['tf']}]")
        print(f"  转换线: {ichi['tenkan']:.2f} | 基准线: {ichi['kijun']:.2f} | {ichi['tk_cross']}")
        print(f"  云层: {ichi['cloud_bot']:.2f} ~ {ichi['cloud_top']:.2f} ({ichi['cloud_color']})")
        print(f"  位置: {ichi['cloud_pos']}")

    # OBV 能量潮
    obv = buy_r.get('obv', {})
    if obv:
        print(f"\n📊 OBV能量潮 [{buy_r['tf']}]")
        print(f"  {obv['trend']} (近30根 OBV{obv.get('obv_change_pct', 0):+.0f}% / 价{obv.get('price_change_pct', 0):+.1f}%)")
        if obv.get('divergence'):
            print(f"  {obv['divergence']}")

    # 固定区间成交量分布 POC/VAH/VAL
    frvp = buy_r.get('frvp', {})
    if frvp:
        print(f"\n📊 成交量分布 [{buy_r['tf']}] (近{frvp.get('lookback', 60)}根)")
        print(f"  POC: {frvp['poc']} (距{frvp['poc_dist_pct']:+.1f}%) | VAH: {frvp['vah']} | VAL: {frvp['val']}")
        print(f"  位置: {frvp['position']}")

    # 双孕线
    ibar = buy_r.get('inside_bar')
    if ibar:
        print(f"\n🟡 形态: {ibar} (突破方向决定后续)")

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

    # K线形态标签
    kline_tag = ''
    main_patterns = (results[0].get('kline_patterns') or [])[:2]
    if main_patterns:
        kline_tag = f" | {' / '.join(main_patterns)}"

    # 筹码标签
    vp_tag_extra = ''
    main_vp = results[0].get('vol_profile') or {}
    if main_vp and main_vp.get('concentration_zones'):
        top_zones = main_vp['concentration_zones'][:2]
        zone_strs = [f"筹码{z['direction']}{z['price']}" for z in top_zones]
        vp_tag_extra = f" | {' / '.join(zone_strs)}"

    # 检查是否有假跌破信号
    has_fbd = any(r.get('fbd_signal') for r in results)
    fbd_tag = " | 🟢假跌破!" if has_fbd else ""
    
    # VWAP 位置
    vwap_tag = ""
    if results and results[0].get('vwap') and not pd.isna(results[0]['vwap']):
        vwap_pos = results[0]['vwap_position']
        if vwap_pos == "上方":
            vwap_tag = " | VWAP↑"
        elif vwap_pos == "下方":
            vwap_tag = " | VWAP↓"
    
    # RSI 标签
    rsi_tag = ""
    rsi_info = results[0].get('rsi', {}) if results else {}
    if rsi_info:
        rsi_val = rsi_info.get('rsi', 50)
        rsi_sig = rsi_info.get('signal', '')
        if '超买' in rsi_sig or '超卖' in rsi_sig:
            rsi_tag = f" | RSI{rsi_val:.0f}{rsi_sig}"

    # 维加斯通道标签 (取日线)
    vegas_tag = ""
    main_for_tags = next((r for r in results if r['tf'] == '日线'), results[0]) if results else {}
    vegas_i = main_for_tags.get('vegas', {}) if main_for_tags else {}
    if vegas_i and vegas_i.get('position'):
        vegas_tag = f" | 维加斯{vegas_i['position']}"
        if vegas_i.get('cross'):
            vegas_tag += vegas_i['cross']
    # 一目云位置
    ichi_tag = ""
    ichi_i = main_for_tags.get('ichimoku', {}) if main_for_tags else {}
    if ichi_i and ichi_i.get('cloud_pos'):
        ichi_tag = f" | 云{ichi_i['cloud_pos'][1:3]}"
    # OBV 背离标签
    obv_tag = ""
    obv_i = main_for_tags.get('obv', {}) if main_for_tags else {}
    if obv_i and obv_i.get('divergence'):
        obv_tag = f" | {obv_i['divergence']}"
    # 双孕线标签
    ibar_tag = ""
    ibar_i = main_for_tags.get('inside_bar') if main_for_tags else None
    if ibar_i:
        ibar_tag = f" | {ibar_i}"

    print(f"  {overall} {ticker} {close:.2f} | {tf_str} | {sup_str} | {res_str}{fbd_tag}{vwap_tag}{rsi_tag}{vegas_tag}{ichi_tag}{obv_tag}{ibar_tag}{kline_tag}{vp_tag_extra}")

    # 开盘价系统 + POC (精简一行)
    osys_c = main_for_tags.get('open_sys', {}) if main_for_tags else {}
    frvp_c = main_for_tags.get('frvp', {}) if main_for_tags else {}
    osys_parts = []
    if osys_c and osys_c.get('week') and osys_c.get('week_open'):
        osys_parts.append(f"周开{osys_c['week_open']:.1f}{osys_c['week'][1][:3]}")
    if osys_c and osys_c.get('year') and osys_c.get('year_open'):
        osys_parts.append(f"年开{osys_c['year_open']:.1f}{osys_c['year'][1][:3]}")
    if frvp_c and frvp_c.get('poc'):
        osys_parts.append(f"POC{frvp_c['poc']}({frvp_c['poc_dist_pct']:+.0f}%)")
    if osys_parts:
        print(f"    📍 {' | '.join(osys_parts)}")
    
    # 加权评分（取主周期）
    main_r = next((r for r in results if r['tf'] == '日线'), results[0])
    ws = main_r.get('weighted_score') or {}
    if ws and ws.get('score', 0) != 0:
        sym = '🟢' if ws['score'] > 0 else '🔴'
        print(f"    {sym} 评分:{ws['score']:+.1f} | {' / '.join(ws['reasons'][:4])}")
    # AVWAP 精简展示
    avw = main_r.get('avwap') or {}
    if avw.get('low') is not None or avw.get('high') is not None:
        parts = []
        if avw.get('low') is not None:
            parts.append(f"AVWAP_L:{avw['low']:.1f}({avw['low_dist_pct']:+.1f}%)")
        if avw.get('high') is not None:
            parts.append(f"AVWAP_H:{avw['high']:.1f}({avw['high_dist_pct']:+.1f}%)")
        print(f"    ⚓ {' | '.join(parts)}")

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


def analyze(ticker, timeframes=None, output_json=False, force_detailed=False):
    if timeframes is None:
        timeframes = ['daily']

    # 获取ATH数据 (用于斐波那契扩展)
    try:
        ath_data = find_ath(ticker)
    except Exception:
        ath_data = None

    results = []
    for tf in timeframes:
        if tf == '4h':
            # westock 不支持小时线，用日线代替，需要足够数据算MA120
            df_d = yf.download(ticker, period='300d', progress=False)
            if df_d.empty:
                continue
            if isinstance(df_d.columns, pd.MultiIndex):
                df_d.columns = df_d.columns.get_level_values(0)
            r = analyze_timeframe(df_d, ticker, "4小时")
            if r:
                results.append(r)

        elif tf == 'daily':
            df_d = yf.download(ticker, period='2y', progress=False)
            if df_d.empty:
                continue
            if isinstance(df_d.columns, pd.MultiIndex):
                df_d.columns = df_d.columns.get_level_values(0)
            r = analyze_timeframe(df_d, ticker, "日线")
            if r:
                results.append(r)

        elif tf == 'weekly':
            df_w = yf.download(ticker, period='3y', interval='1wk', progress=False)
            if df_w.empty:
                continue
            if isinstance(df_w.columns, pd.MultiIndex):
                df_w.columns = df_w.columns.get_level_values(0)
            r = analyze_timeframe(df_w, ticker, "周线")
            if r:
                results.append(r)

    if not results:
        if output_json:
            import json
            print(json.dumps({'ticker': ticker, 'error': 'no_data'}, ensure_ascii=False))
        else:
            print(f"  ⚠️ {ticker}: 无数据")
        return

    # JSON 输出
    if output_json:
        import json
        out = {
            'ticker': ticker,
            'timestamp': datetime.now().isoformat(),
            'timeframes': [],
        }
        for r in results:
            tf_out = {
                'tf': r['tf'],
                'close': float(r['close']),
                'signal': r['signal'],
                'convergence_pct': round(float(r.get('cr', 0)), 2),
                'is_convergent': bool(r.get('is_conv')),
                'k_above_ma': bool(r.get('k_above')),
                'arrangement': r.get('arr'),
                'weighted_score': r.get('weighted_score'),
                'macd': {k: (v if not isinstance(v, float) else round(v, 4)) for k, v in (r.get('macd') or {}).items() if k != 'hist_trend'},
                'rsi': (round(float((r.get('rsi') or {}).get('rsi', 0)), 2) if r.get('rsi') else None),
                'rsi_signal': (r.get('rsi') or {}).get('signal'),
                'vp': r.get('vp'),
                'engulfing': r.get('engulfing'),
                'boll_signal': (r.get('boll') or {}).get('signal'),
                'avwap_low': (r.get('avwap') or {}).get('low'),
                'avwap_high': (r.get('avwap') or {}).get('high'),
                'pb_signal': r.get('pb_signal'),
                'fb_signal': r.get('fb_signal'),
                'fbd_signal': r.get('fbd_signal'),
                'supports': [{'price': round(s[0], 2), 'strength': s[1], 'dur': s[2]} for s in (r.get('supports') or [])[:3]],
                'resistances': [{'price': round(s[0], 2), 'strength': s[1], 'dur': s[2]} for s in (r.get('resistances') or [])[:3]],
                'vegas': r.get('vegas'),
                'open_sys': r.get('open_sys'),
                'ichimoku': r.get('ichimoku'),
                'obv': r.get('obv'),
                'frvp': r.get('frvp'),
                'inside_bar': r.get('inside_bar'),
            }
            out['timeframes'].append(tf_out)
        out['resonance'] = compute_resonance(results)
        print(json.dumps(out, ensure_ascii=False, default=str))
        return

    # 多周期共振汇总
    if len(results) >= 2 and any(r['tf'] == '周线' for r in results) and any(r['tf'] == '日线' for r in results):
        print_resonance_summary(ticker, results)

    # 判断是否有买入信号
    has_buy = any(r['signal'] == 'buy' for r in results)
    if has_buy or force_detailed:
        print_detailed(ticker, results, ath_data)
    else:
        print_compact(ticker, results, ath_data)


def compute_resonance(results):
    """多周期共振返回 dict: {direction, weekly_signal, daily_signal, action}"""
    wk = next((r for r in results if r['tf'] == '周线'), None)
    dy = next((r for r in results if r['tf'] == '日线'), None)
    if not (wk and dy):
        return None
    # 周线定方向
    if wk['signal'] == 'buy' or (wk.get('k_above') and wk.get('weighted_score', {}).get('score', 0) > 0):
        wk_dir = 'bullish'
    elif wk['signal'] == 'sell' or wk.get('weighted_score', {}).get('score', 0) < -1:
        wk_dir = 'bearish'
    else:
        wk_dir = 'neutral'
    # 日线定买点
    if dy['signal'] == 'buy':
        dy_act = 'buy'
    elif dy['signal'] == 'sell':
        dy_act = 'sell'
    else:
        dy_act = 'wait'
    # 共振判断
    if wk_dir == 'bullish' and dy_act == 'buy':
        action = '周线多头+日线买点→共振买入⭐'
    elif wk_dir == 'bullish' and dy_act == 'wait':
        action = '周线多头→等日线买点'
    elif wk_dir == 'bearish' and dy_act == 'sell':
        action = '周线空头+日线卖点→共振卖出⚠️'
    elif wk_dir == 'bearish' and dy_act == 'buy':
        action = '周线空头但日线反弹→折衷，谨慎小仓'
    else:
        action = '无明显共振，观望'
    return {
        'weekly_direction': wk_dir,
        'daily_action': dy_act,
        'weekly_score': wk.get('weighted_score', {}).get('score', 0),
        'daily_score': dy.get('weighted_score', {}).get('score', 0),
        'action': action,
    }


def print_resonance_summary(ticker, results):
    """打印多周期共振汇总"""
    rez = compute_resonance(results)
    if not rez:
        return
    print(f"\n🔀 [{ticker}] 周线定方向 / 日线定买点")
    print(f"  周线方向: {rez['weekly_direction']} (评分 {rez['weekly_score']:+.1f})")
    print(f"  日线动作: {rez['daily_action']} (评分 {rez['daily_score']:+.1f})")
    print(f"  → {rez['action']}")


if __name__ == "__main__":
    # 兼容保留原有 positional 用法:
    #   python3 ma_analysis.py [ticker] [4h,daily,weekly]
    # 新增:
    #   python3 ma_analysis.py NVDA -m d+w        # 多周期共振
    #   python3 ma_analysis.py NVDA --json         # JSON 输出
    import argparse
    import json as _json

    DEFAULT_TICKERS = ['0700.HK', '1810.HK', 'QQQ', 'NVDA', 'TSLA']

    # 先试 argparse，如果用户传的是旧风格 (positional tf) 则 fallback
    parser = argparse.ArgumentParser(description='均线密集/发散分析 v3.1')
    parser.add_argument('ticker', nargs='?', help='股票代码 (如 NVDA)')
    parser.add_argument('tf_pos', nargs='?', help='(旧) 逗号分隔的时间周期，如 daily 或 4h,daily,weekly')
    parser.add_argument('-m', '--mode', help='时间周期组合: d / w / d+w / 4h+d+w')
    parser.add_argument('--json', dest='as_json', action='store_true', help='以JSON格式输出')
    parser.add_argument('--detailed', action='store_true', help='强制详细输出（不管有没有买入信号）')
    args = parser.parse_args()

    tf_map = {'d': 'daily', 'w': 'weekly', '4h': '4h', 'daily': 'daily', 'weekly': 'weekly'}

    def _parse_tf(spec):
        if spec is None:
            return None
        # 支持 "d+w" 和 "daily,weekly"
        if '+' in spec:
            parts = spec.split('+')
        else:
            parts = spec.split(',')
        out = []
        for p in parts:
            p = p.strip()
            if p in tf_map:
                out.append(tf_map[p])
        return out or None

    tfs = _parse_tf(args.mode) or _parse_tf(args.tf_pos) or ['4h', 'daily', 'weekly']

    if args.ticker:
        analyze(args.ticker, tfs, output_json=args.as_json, force_detailed=args.detailed)
    else:
        if args.as_json:
            out = {'timestamp': datetime.now().isoformat(), 'tickers': []}
            for t in DEFAULT_TICKERS:
                # 内部调用，不把每支都单独打印，改为收集
                try:
                    # 同样逻辑，但收集返回
                    # 简化: 直接再调用 analyze + json，分行输出
                    analyze(t, tfs, output_json=True)
                except Exception as e:
                    print(_json.dumps({'ticker': t, 'error': str(e)}, ensure_ascii=False))
        else:
            print(f"\n{'='*60}")
            print(f"  📊 持仓均线分析 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            print(f"{'='*60}")
            for t in DEFAULT_TICKERS:
                analyze(t, tfs, force_detailed=args.detailed)
            print(f"{'='*60}")
