#!/usr/bin/env python3
"""
westock-data wrapper for ma_analysis.py
将 yfinance 格式转换为 westock-data 格式
"""

import subprocess
import json
import os
from datetime import datetime, timedelta
import sys

from stock_analysis.data import normalize_provider_ticker

# 代码格式转换映射
TICKER_MAP = {
    '0700.HK': 'hk00700',
    '1810.HK': 'hk01810',
    '9992.HK': 'hk09992',
    '0981.HK': 'hk00981',  # 中芯国际
    '688256.SS': 'sh688256',  # 寒武纪
    '600703.SS': 'sh600703',  # 三安光电
    '001391.SZ': 'sz001391',  # 国货航
    'NVDA': 'usNVDA',
    'TSLA': 'usTSLA',
    'QQQ': 'usQQQ',
    'PDD': 'usPDD',
}

DEFAULT_WESTOCK_DATA_SCRIPT = '/root/.openclaw/workspace/skills/westock-data/scripts/index.js'

def convert_ticker(ticker):
    """转换 ticker 格式: 0700.HK -> hk00700"""
    if ticker in TICKER_MAP:
        return TICKER_MAP[ticker]

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
        
        return df
        
    except subprocess.CalledProcessError as e:
        print(f"Error fetching {ticker}: {e.stderr}", file=sys.stderr)
        return pd.DataFrame()
    except Exception as e:
        print(f"Error parsing {ticker}: {str(e)}", file=sys.stderr)
        return pd.DataFrame()

def fetch_yfinance(ticker, period='1y', start=None, end=None, interval='1d', progress=False):
    """Fallback to yfinance when westock-data is unavailable or returns no data."""
    import yfinance as _yf

    return _yf.download(
        ticker,
        period=period if start is None and end is None else None,
        start=start,
        end=end,
        interval=interval,
        progress=progress,
        auto_adjust=False,
    )

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
        return df.apply(pd.to_numeric, errors='coerce').dropna().sort_index()
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
            rows = stock_data.get(period) or stock_data.get(f'qfq{period}') or []
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
            return df.dropna().sort_index()
        except Exception as e:
            last_error = e

    if last_error:
        print(f"Error fetching Tencent kline {ticker}: {str(last_error)}", file=sys.stderr)
    return pd.DataFrame()

def download(ticker, period='1y', start=None, end=None, interval='1d', progress=False):
    """
    模拟 yfinance.download() 接口
    """
    # 计算需要的数据量
    if period == 'max':
        limit = 2000
    elif period.endswith('y'):
        years = int(period[:-1])
        limit = years * 250  # 每年约250个交易日
    elif period.endswith('mo'):
        months = int(period[:-2])
        limit = months * 21  # 每月约21个交易日
    elif period.endswith('d'):
        days = int(period[:-1])
        limit = days
    else:
        limit = 500
    
    # 转换 interval
    if interval == '1d':
        ws_period = 'day'
    elif interval == '1wk':
        ws_period = 'week'
    elif interval == '1mo':
        ws_period = 'month'
    elif interval == '1h':
        ws_period = 'day'  # westock 不支持小时线，用日线代替
        limit = min(limit, 500)
    else:
        ws_period = 'day'
    
    df = fetch_kline(ticker, ws_period, limit)
    ws_ticker = convert_ticker(ticker)
    if getattr(df, 'empty', True) and ws_ticker.startswith(('hk', 'sh', 'sz', 'bj')):
        df = fetch_tencent_kline(ticker, ws_period, limit)
    if getattr(df, 'empty', True):
        df = fetch_yahoo_chart(ticker, period=period, start=start, end=end, interval=interval)
    if getattr(df, 'empty', True):
        df = fetch_yfinance(ticker, period=period, start=start, end=end, interval=interval, progress=progress)
    
    # 如果指定了 start/end，过滤数据
    if not df.empty:
        if start:
            import pandas as pd
            df = df[df.index >= pd.to_datetime(start)]
        if end:
            import pandas as pd
            df = df[df.index <= pd.to_datetime(end)]
    
    return df

if __name__ == '__main__':
    # 测试
    if len(sys.argv) > 1:
        ticker = sys.argv[1]
        df = download(ticker, period='5d')
        print(df)
    else:
        print("Usage: python3 westock_wrapper.py <ticker>")
