#!/usr/bin/env python3
"""
Market data wrapper for naked K analysis.
返回与 yfinance.download() 兼容的 OHLCV DataFrame。
"""

import subprocess
import json
import os
from datetime import datetime
import sys

DEFAULT_WESTOCK_DATA_SCRIPT = '/root/.openclaw/workspace/skills/westock-data/scripts/index.js'
MIN_INTRADAY_ROWS = 120

# Tencent serves rows for limit<=2000 and an empty payload for limit>=2001
# (binary-searched live on sh600519 month). Asking for more loses the source.
TENCENT_MAX_ROWS = 2000

# Approximate bars per (year, month) for each interval. Kept as an explicit pair
# rather than deriving months from years: the daily path's ~21 bars/month is the
# long-standing figure and dividing 250/12 would quietly shave rows off every
# `18mo` daily window. Weekly and monthly are the entries that were wrong — they
# were previously counted in trading days.
_BARS_PER_PERIOD = {
    '1h': (250 * 6, 21 * 6),
    '1d': (250, 21),
    '1wk': (52, 5),
    '1mo': (12, 1),
}

# Corporate-action adjustment conventions, as (split_adjusted, dividend_adjusted).
# A naked-K engine reads candle shape directly, so a source that leaves ex-rights
# gaps in place manufactures engulfing bars and BOS breaks that never happened.
# Every fetcher must label its frame so a fallback switch is visible downstream.
ADJUSTMENT_PROPERTIES = {
    'raw': (False, False),
    'split_only': (True, False),
    'qfq': (True, True),   # 前复权: history restated onto the latest price scale
    'hfq': (True, True),   # 后复权: history kept, latest price scaled up
}
ADJUSTMENT_UNKNOWN = 'unknown'

_ADJUSTMENT_LABELS = {
    'raw': '未复权（除权跳空保留在K线里）',
    'split_only': '仅拆股复权（分红除权跳空保留）',
    'qfq': '前复权（按最新价格轴还原历史）',
    'hfq': '后复权（保留历史价格轴，抬升最新价）',
}
_ADJUSTMENT_UNKNOWN_LABEL = '未知复权口径'


def describe_adjustment(adjustment):
    """Return a report-ready Chinese description of an adjustment label."""
    return _ADJUSTMENT_LABELS.get(adjustment, _ADJUSTMENT_UNKNOWN_LABEL)


def adjustments_comparable(left, right):
    """Whether two frames share one price basis and may be read together.

    Deliberately stricter than comparing (split, dividend) properties: qfq and
    hfq both adjust for everything yet sit on opposite price scales, so mixing
    them would keep candle shapes while moving every trigger and stop level.
    ``unknown`` never matches, including itself — two unlabelled sources are not
    evidence of agreement.
    """
    if left == ADJUSTMENT_UNKNOWN or right == ADJUSTMENT_UNKNOWN:
        return False
    if left not in ADJUSTMENT_PROPERTIES or right not in ADJUSTMENT_PROPERTIES:
        return False
    return left == right


def _tag_adjustment(df, adjustment):
    """Record the adjustment convention on a frame, tolerating non-frames."""
    if hasattr(df, 'attrs'):
        df.attrs['adjustment'] = adjustment
    return df


def normalize_provider_ticker(ticker):
    """Normalize common Yahoo-style tickers to westock/Tencent symbols."""
    symbol = ticker.strip().upper()
    if symbol.endswith(".HK"):
        return f"hk{symbol[:-3].zfill(5)}"
    if symbol.endswith(".SS"):
        return f"sh{symbol[:-3]}"
    if symbol.endswith(".SZ"):
        return f"sz{symbol[:-3]}"
    if symbol.endswith(".BJ"):
        return f"bj{symbol[:-3]}"
    if symbol.endswith((".KS", ".KQ")):
        return f"kr{symbol[:-3].zfill(6)}"
    return f"us{symbol}"


def convert_ticker(ticker):
    """转换 ticker 格式: 0700.HK -> hk00700"""
    return normalize_provider_ticker(ticker)

def build_westock_command(ticker, period='day', limit=500):
    """Build the westock-data CLI command.

    WESTOCK_DATA_SCRIPT lets this repo run outside the original OpenClaw path.
    """
    ws_ticker = convert_ticker(ticker)
    script = os.environ.get('WESTOCK_DATA_SCRIPT', DEFAULT_WESTOCK_DATA_SCRIPT)
    return [
        'node',
        script,
        'kline',
        ws_ticker,
        period,
        str(limit)
    ]

def fetch_kline(ticker, period='day', limit=500):
    """
    调用 westock-data 获取 K线数据
    返回 pandas DataFrame，列名与 yfinance 兼容
    """
    import pandas as pd

    cmd = build_westock_command(ticker, period, limit)
    if 'WESTOCK_DATA_SCRIPT' not in os.environ and not os.path.exists(cmd[1]):
        return pd.DataFrame()
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout.strip()
        
        if not output or 'date' not in output:
            return pd.DataFrame()
        
        # 解析 Markdown 表格
        lines = output.strip().split('\n')
        if len(lines) < 3:
            return pd.DataFrame()
        
        # 跳过表头和分隔符
        data_lines = lines[2:]
        
        rows = []
        for line in data_lines:
            parts = [p.strip() for p in line.split('|')[1:-1]]  # 去掉首尾空格
            if len(parts) >= 7:
                rows.append(parts)
        
        if not rows:
            return pd.DataFrame()
        
        # 构建 DataFrame
        df = pd.DataFrame(rows, columns=['date', 'open', 'last', 'high', 'low', 'volume', 'amount', 'exchange'])
        
        # 转换数据类型
        df['date'] = pd.to_datetime(df['date'])
        df['Open'] = pd.to_numeric(df['open'], errors='coerce')
        df['Close'] = pd.to_numeric(df['last'], errors='coerce')
        df['High'] = pd.to_numeric(df['high'], errors='coerce')
        df['Low'] = pd.to_numeric(df['low'], errors='coerce')
        df['Volume'] = pd.to_numeric(df['volume'], errors='coerce')
        
        # 设置索引
        df.set_index('date', inplace=True)
        
        # 只保留需要的列
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
        
        # ⚠️ westock 返回倒序（最新在前），需要反转为正序（最新在后）
        df = df.sort_index()

        # The westock-data CLI documents no adjustment mode and exposes no flag
        # to request one, so its basis cannot be asserted from here. Left
        # unknown rather than guessed — a wrong label is worse than no label.
        return _tag_adjustment(df, ADJUSTMENT_UNKNOWN)
        
    except subprocess.CalledProcessError as e:
        print(f"Error fetching {ticker}: {e.stderr}", file=sys.stderr)
        return pd.DataFrame()
    except Exception as e:
        print(f"Error parsing {ticker}: {str(e)}", file=sys.stderr)
        return pd.DataFrame()

def fetch_yfinance(ticker, period='1y', start=None, end=None, interval='1d', progress=False):
    """Fallback to yfinance when westock-data is unavailable or returns no data."""
    import yfinance as _yf

    frame = _yf.download(
        ticker,
        period=period if start is None and end is None else None,
        start=start,
        end=end,
        interval=interval,
        progress=progress,
        auto_adjust=False,
    )
    # auto_adjust=False keeps Yahoo's own OHLC: restated for splits, but with
    # dividend ex-dates left as real gaps. Not the same basis as Tencent's qfq.
    return _tag_adjustment(frame, 'split_only')

def fetch_yahoo_chart(ticker, period='1y', start=None, end=None, interval='1d'):
    """Fetch OHLCV data from Yahoo's chart JSON endpoint without yfinance cookies."""
    import pandas as pd
    import requests

    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}'
    params = {'interval': interval}
    if start or end:
        start_ts = int(pd.to_datetime(start or '1970-01-01').timestamp())
        end_ts = int(pd.to_datetime(end or datetime.now()).timestamp())
        params.update({'period1': start_ts, 'period2': end_ts})
    else:
        params['range'] = period

    try:
        response = requests.get(url, params=params, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()
        payload = response.json()
        result = ((payload.get('chart') or {}).get('result') or [None])[0]
        if not result:
            return pd.DataFrame()

        timestamps = result.get('timestamp') or []
        quote = (((result.get('indicators') or {}).get('quote') or [{}])[0])
        rows = {
            'Open': quote.get('open') or [],
            'High': quote.get('high') or [],
            'Low': quote.get('low') or [],
            'Close': quote.get('close') or [],
            'Volume': quote.get('volume') or [],
        }
        if not timestamps or any(len(values) != len(timestamps) for values in rows.values()):
            return pd.DataFrame()

        df = pd.DataFrame(rows, index=pd.to_datetime(timestamps, unit='s'))
        df.index.name = 'date'
        # The chart endpoint's `quote` block is Yahoo's split-adjusted OHLC. Its
        # separate `adjclose` series is the dividend-adjusted one and is not read
        # here, so this frame is split_only — same basis as fetch_yfinance.
        cleaned = df.apply(pd.to_numeric, errors='coerce').dropna().sort_index()
        return _tag_adjustment(cleaned, 'split_only')
    except Exception as e:
        print(f"Error fetching Yahoo chart {ticker}: {str(e)}", file=sys.stderr)
        return pd.DataFrame()

def fetch_tencent_kline(ticker, period='day', limit=500):
    """Fetch OHLCV data from Tencent's appstock kline endpoint."""
    import pandas as pd
    import requests

    ws_ticker = convert_ticker(ticker)
    if not ws_ticker.startswith(('hk', 'sh', 'sz', 'bj')):
        return pd.DataFrame()
    urls = [
        'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
        'https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get',
    ]
    params = {'param': f'{ws_ticker},{period},,,{limit},qfq'}

    last_error = None
    for url in urls:
        try:
            response = requests.get(url, params=params, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            response.raise_for_status()
            payload = json.loads(response.text)
            if payload.get('code') != 0:
                continue

            stock_data = (payload.get('data') or {}).get(ws_ticker) or {}
            # Which key answers decides the adjustment basis, so read them in a
            # fixed order and remember which one won. Verified live: A-shares
            # answer a qfq request under `qfq<period>` only (sh688256 day=1009.450
            # vs qfqday=676.477), while HK answers under `<period>` only and
            # returns byte-identical rows for ''/qfq/hfq — it ignores the mode.
            # No symbol returns both keys, so precedence is defensive, not a fix.
            adjusted_rows = stock_data.get(f'qfq{period}')
            if adjusted_rows:
                rows, adjustment = adjusted_rows, 'qfq'
            else:
                # HK's plain `<period>` series tracks Yahoo's un-adjusted close,
                # not its adjclose: across 489 bars spanning two 0700.HK dividends
                # (2025-05-16 HK$4.5, 2026-05-15 HK$5.3) it matched close to a
                # 0.0027% mean while adjclose diverged 1.33% on 430 of them. So it
                # is dividend-raw, same basis as the Yahoo fetchers.
                rows, adjustment = stock_data.get(period) or [], 'split_only'
            if not rows:
                continue

            df = pd.DataFrame(rows)
            df = df.iloc[:, :6]
            df.columns = ['date', 'open', 'close', 'high', 'low', 'volume']
            df['date'] = pd.to_datetime(df['date'])
            df['Open'] = pd.to_numeric(df['open'], errors='coerce')
            df['High'] = pd.to_numeric(df['high'], errors='coerce')
            df['Low'] = pd.to_numeric(df['low'], errors='coerce')
            df['Close'] = pd.to_numeric(df['close'], errors='coerce')
            df['Volume'] = pd.to_numeric(df['volume'], errors='coerce')
            df.set_index('date', inplace=True)
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
            return _tag_adjustment(df.dropna().sort_index(), adjustment)
        except Exception as e:
            last_error = e

    if last_error:
        print(f"Error fetching Tencent kline {ticker}: {str(last_error)}", file=sys.stderr)
    return pd.DataFrame()

def _annotate_download(df, source, ticker, period, interval):
    if not hasattr(df, 'attrs'):
        return df
    try:
        rows = len(df)
    except TypeError:
        rows = 0
    latest = ""
    try:
        if rows:
            latest_value = df.index[-1]
            latest = latest_value.strftime('%Y-%m-%d') if hasattr(latest_value, 'strftime') else str(latest_value)
    except Exception:
        latest = ""
    df.attrs.update(
        {
            'source': source,
            'ticker': ticker,
            'period': period,
            'interval': interval,
            'rows': rows,
            'latest': latest,
            # Read from the frame the winning fetcher already tagged. Defaulting
            # here rather than inheriting keeps a silent source from picking up
            # whatever label a previous frame happened to carry.
            'adjustment': df.attrs.get('adjustment', ADJUSTMENT_UNKNOWN),
        }
    )
    return df

def download(ticker, period='1y', start=None, end=None, interval='1d', progress=False):
    """
    模拟 yfinance.download() 接口
    """
    # 计算需要的数据量: bars-per-year depends on the interval, not just the period.
    # Counting every interval in trading days made a 10y monthly request ask for
    # 2500 bars, which exceeds TENCENT_MAX_ROWS and returned nothing, dropping the
    # request to Yahoo and mixing adjustment bases inside one ticker's run.
    per_year, per_month = _BARS_PER_PERIOD.get(interval, _BARS_PER_PERIOD['1d'])
    if period == 'max':
        limit = TENCENT_MAX_ROWS
    elif period.endswith('y'):
        limit = int(period[:-1]) * per_year
    elif period.endswith('mo'):
        limit = max(1, int(period[:-2]) * per_month)
    elif period.endswith('d'):
        days = int(period[:-1])
        limit = days * 6 if interval == '1h' else days
    else:
        limit = 500

    # Live boundary, binary-searched: <=2000 returns rows, >=2001 returns an empty
    # payload. Clamping keeps the primary source instead of silently falling back.
    limit = min(limit, TENCENT_MAX_ROWS)

    # 转换 interval
    if interval == '1d':
        ws_period = 'day'
    elif interval == '1wk':
        ws_period = 'week'
    elif interval == '1mo':
        ws_period = 'month'
    elif interval == '1h':
        ws_period = 'm60'
    else:
        ws_period = 'day'
    
    def _has_enough_rows(frame):
        if getattr(frame, 'empty', True):
            return False
        if interval == '1h':
            try:
                return len(frame) >= MIN_INTRADAY_ROWS
            except TypeError:
                return True
        return True

    source = 'yfinance'
    df = fetch_kline(ticker, ws_period, limit)
    if not _has_enough_rows(df):
        df = type(df)() if hasattr(df, 'empty') else df
    elif not getattr(df, 'empty', True):
        source = 'westock'
    ws_ticker = convert_ticker(ticker)
    if getattr(df, 'empty', True) and ws_ticker.startswith(('hk', 'sh', 'sz', 'bj')):
        df = fetch_tencent_kline(ticker, ws_period, limit)
        if not _has_enough_rows(df):
            df = type(df)() if hasattr(df, 'empty') else df
        elif not getattr(df, 'empty', True):
            source = 'tencent'
    if getattr(df, 'empty', True):
        df = fetch_yahoo_chart(ticker, period=period, start=start, end=end, interval=interval)
        if not getattr(df, 'empty', True):
            source = 'yahoo_chart'
    if getattr(df, 'empty', True):
        df = fetch_yfinance(ticker, period=period, start=start, end=end, interval=interval, progress=progress)
        source = 'yfinance'
    
    # 如果指定了 start/end，过滤数据
    if not df.empty:
        if start:
            import pandas as pd
            df = df[df.index >= pd.to_datetime(start)]
        if end:
            import pandas as pd
            df = df[df.index <= pd.to_datetime(end)]
    
    return _annotate_download(df, source, ticker, period, interval)

if __name__ == '__main__':
    # 测试
    if len(sys.argv) > 1:
        ticker = sys.argv[1]
        df = download(ticker, period='5d')
        print(df)
    else:
        print("Usage: python3 westock_wrapper.py <ticker>")
