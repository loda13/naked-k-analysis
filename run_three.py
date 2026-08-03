#!/usr/bin/env python3
"""Ad-hoc runner: 腾讯 / 小米 / 泡泡玛特 with news + LLM layers."""
from __future__ import annotations

import sys
from pathlib import Path

import naked_k_analysis
import naked_k_config
import naked_k_llm
import naked_k_news_llm

TICKERS = [
    ("腾讯", "0700.HK"),
    ("小米", "1810.HK"),
    ("泡泡玛特", "9992.HK"),
]


def main() -> int:
    tag = sys.argv[1] if len(sys.argv) > 1 else "three"
    config = naked_k_config.load_trading_config(None)
    llm_config = naked_k_llm.load_llm_config(enabled=True)
    news_config = naked_k_news_llm.load_news_config(enabled=True)
    if news_config.model:
        naked_k_news_llm.validate_news_config(news_config)
    else:
        news_config = naked_k_news_llm.resolve_news_model(news_config)

    report_text, _ = naked_k_analysis.run_analysis(
        TICKERS,
        Path(f"reports/three_{tag}_journal.jsonl"),
        config=config,
        audit_path=Path(f"reports/three_{tag}_audit.jsonl"),
        llm_config=llm_config,
        news_config=news_config,
        news_lookback_days=7,
        news_max_items=12,
    )
    out = Path(f"reports/three_{tag}.md")
    out.write_text(report_text, encoding="utf-8")
    print(f"WROTE {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
