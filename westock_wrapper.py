#!/usr/bin/env python3
"""
westock-data wrapper for ma_analysis.py
将 yfinance 格式转换为 westock-data 格式
"""

import subprocess
import json
import pandas as pd
from datetime import datetime, timedelta
import sys

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

def convert_ticker(ticker):
    """转换 ticker 格式: 0700.HK -> hk00700"""
    if ticker in TICKER_MAP:
        return TICKER_MAP[ticker]
    
    # 自动转换规则
    if ticker.endswith('.HK'):
        code = ticker.replace('.HK', '')
        return f'hk{code.zfill(5)}'
    
    # 美股默认加 us 前缀
    if not ticker.startswith(('us', 'hk', 'sh', 'sz', 'bj')):
        return f'us{ticker}'
    
    return ticker

def fetch_kline(ticker, period='day', limit=500):
    """
    调用 westock-data 获取 K线数据
    返回 pandas DataFrame，列名与 yfinance 兼容
    """
    ws_ticker = convert_ticker(ticker)
    
    cmd = [
        'node',
        '/root/.openclaw/workspace/skills/westock-data/scripts/index.js',
        'kline',
        ws_ticker,
        period,
        str(limit)
    ]
    
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
    
    # 如果指定了 start/end，过滤数据
    if not df.empty:
        if start:
            df = df[df.index >= pd.to_datetime(start)]
        if end:
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
