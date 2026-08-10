#!/usr/bin/env python3
"""One-off live diagnostic: what adjustment convention does each price source return?

Named run_* so `unittest discover` never picks it up. This hits the live network
and is NOT part of the test gate.

Usage: python run_adjustment_probe.py [TICKER ...]
"""

from __future__ import annotations

import json
import sys

import pandas as pd
import requests

import westock_wrapper as ww


def tencent_raw(ticker: str, adjust: str, limit: int = 400) -> pd.DataFrame:
    """Fetch Tencent kline with an explicit adjustment mode ('', 'qfq', 'hfq')."""
    ws = ww.convert_ticker(ticker)
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {"param": f"{ws},day,,,{limit},{adjust}"}
    r = requests.get(url, params=params, timeout=15,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    payload = json.loads(r.text)
    data = (payload.get("data") or {}).get(ws) or {}
    rows = data.get("day") or data.get(f"{adjust}day") or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([r[:6] for r in rows],
                      columns=["date", "open", "close", "high", "low", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "close", "high", "low"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.set_index("date")[["open", "high", "low", "close"]].sort_index()


def yahoo_both(ticker: str) -> pd.DataFrame:
    """Yahoo chart JSON: quote OHLC alongside adjclose, so we can see the gap."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    r = requests.get(url, params={"interval": "1d", "range": "2y"}, timeout=15,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    res = ((r.json().get("chart") or {}).get("result") or [None])[0]
    if not res:
        return pd.DataFrame()
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    adj = ((res.get("indicators") or {}).get("adjclose") or [{}])[0]
    df = pd.DataFrame({
        "close": q.get("close") or [],
        "adjclose": adj.get("adjclose") or [q.get("close")],
    }, index=pd.to_datetime(res.get("timestamp") or [], unit="s").normalize())
    return df.apply(pd.to_numeric, errors="coerce").dropna().sort_index()


# Mirror the production routing guard exactly rather than re-declaring it, so the
# probe cannot drift from the code whose numbers it is generating.
TENCENT_MARKETS = ww.TENCENT_MARKETS

# Divergence between bases only appears across an ex-date, so a comparison drawn
# from a couple of bars proves nothing either way.
MIN_COMPARABLE_BARS = 30


def probe(ticker: str) -> None:
    print(f"\n{'=' * 72}\n{ticker}\n{'=' * 72}")

    frames = {}
    # Mirror the production guard in download(): only these markets ever reach
    # Tencent. Without this the probe queried usPDD, got a 1-row stub back, and
    # then reported "identical=True" off that single bar — a comparison that looks
    # like agreement but is really an absence of data.
    if ww.convert_ticker(ticker).startswith(TENCENT_MARKETS):
        for label, adjust in (("tencent_raw", ""), ("tencent_qfq", "qfq")):
            try:
                frames[label] = tencent_raw(ticker, adjust)
                print(f"  {label:14s} rows={len(frames[label])}")
            except Exception as exc:
                print(f"  {label:14s} FAILED {type(exc).__name__}: {exc}")
    else:
        print(f"  {'tencent':14s} skipped (production never routes "
              f"{ww.convert_ticker(ticker)} to Tencent)")

    try:
        y = yahoo_both(ticker)
        frames["yahoo_close"] = y[["close"]]
        frames["yahoo_adjclose"] = y[["adjclose"]].rename(columns={"adjclose": "close"})
        print(f"  {'yahoo':14s} rows={len(y)}")
    except Exception as exc:
        print(f"  {'yahoo':14s} FAILED {type(exc).__name__}: {exc}")

    # Does westock resolve at all in this environment?
    ws_df = ww.fetch_kline(ticker, "day", 400)
    print(f"  {'westock':14s} rows={len(ws_df)}"
          f"{' (script unavailable here)' if ws_df.empty else ''}")
    if not ws_df.empty:
        frames["westock"] = ws_df.rename(columns=str.lower)[["open", "high", "low", "close"]]

    # Compare every source against Tencent qfq (the current HK/A-share primary).
    base = frames.get("tencent_qfq")
    if base is None or base.empty:
        print("  no tencent_qfq baseline; skipping comparison")
        return
    if len(base) < MIN_COMPARABLE_BARS:
        # A handful of bars cannot show ex-date divergence, so "identical" would
        # be meaningless rather than reassuring.
        print(f"  tencent_qfq returned only {len(base)} bars "
              f"(<{MIN_COMPARABLE_BARS}); too few to compare, skipping")
        return

    print(f"\n  Close vs tencent_qfq on shared dates:")
    print(f"  {'source':16s} {'n':>5s} {'identical':>10s} "
          f"{'max_diff%':>10s} {'ratio_drift':>12s}")
    for label, df in frames.items():
        if label == "tencent_qfq" or df.empty:
            continue
        joined = base[["close"]].join(df[["close"]], how="inner",
                                     lsuffix="_qfq", rsuffix="_other").dropna()
        if joined.empty:
            print(f"  {label:16s} {'0':>5s} {'-':>10s} {'-':>10s} {'-':>12s}")
            continue
        ratio = joined["close_other"] / joined["close_qfq"]
        pct = (ratio - 1).abs() * 100
        identical = bool((pct < 0.01).all())
        # A constant ratio means a pure scale difference; a drifting ratio means
        # the two sources disagree about corporate actions over time.
        drift = ratio.max() - ratio.min()
        print(f"  {label:16s} {len(joined):>5d} {str(identical):>10s} "
              f"{pct.max():>10.3f} {drift:>12.5f}")

    # Show the oldest and newest shared bar so a scale offset is visible.
    y_close = frames.get("yahoo_close")
    if y_close is not None and not y_close.empty:
        j = base[["close"]].join(y_close[["close"]], how="inner",
                                 lsuffix="_qfq", rsuffix="_yahoo").dropna()
        if not j.empty:
            print("\n  sample (oldest / newest shared bar):")
            for when in (j.index[0], j.index[-1]):
                row = j.loc[when]
                print(f"    {when.date()}  qfq={row['close_qfq']:>10.3f}  "
                      f"yahoo={row['close_yahoo']:>10.3f}  "
                      f"ratio={row['close_yahoo'] / row['close_qfq']:.5f}")


if __name__ == "__main__":
    tickers = sys.argv[1:] or ["0700.HK", "1810.HK", "PDD"]
    for t in tickers:
        try:
            probe(t)
        except Exception as exc:
            print(f"{t}: probe failed {type(exc).__name__}: {exc}")
