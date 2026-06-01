#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from stock_analysis.advisor import build_advice
from stock_analysis.cache import load_wss_context
from stock_analysis.naked_k import analyze_naked_k
from stock_analysis.report import advice_to_json, render_text_report
from stock_analysis.technical import analyze_technical


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Wall Street Skill 股票综合分析")
    parser.add_argument("ticker", help="股票代码，如 NVDA、0700.HK")
    parser.add_argument("--cache-dir", default="data/cache/wss", help="WSS缓存目录")
    parser.add_argument("--horizons", default="short,medium,long", help="分析周期")
    parser.add_argument("--json", action="store_true", dest="as_json", help="输出JSON")
    parser.add_argument("--refresh-wss-cache", action="store_true", help="刷新WSS缓存")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.refresh_wss_cache:
        print("refresh_not_implemented: WSS认证刷新将在Milestone 2实现。", file=sys.stderr)
        return 2

    timeframes = ["daily", "weekly"]
    if "short" in args.horizons:
        timeframes.insert(0, "4h")

    ctx = load_wss_context(args.cache_dir)
    technical = analyze_technical(args.ticker, timeframes=timeframes)
    naked = analyze_naked_k(args.ticker)
    advice = build_advice(args.ticker, ctx, technical=technical, naked=naked)

    if args.as_json:
        print(advice_to_json(advice))
    else:
        print(render_text_report(advice))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
