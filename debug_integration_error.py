#!/usr/bin/env python3
"""
Debug script to reproduce and diagnose NewsIntegrationError.
Run the news analysis pipeline for a single ticker and capture detailed errors.
"""
import sys
import traceback
import pandas as pd
from datetime import datetime

# Import modules
import naked_k_news_llm
import naked_k_news_enhanced
import naked_k_synthesis
from naked_k_config import TradingConfig
from naked_k_planner import InstrumentReport

def debug_single_ticker(ticker, name, symbol):
    """Run news analysis for a single ticker with detailed error logging."""
    print(f"\n{'='*60}")
    print(f"Debugging: {name} ({symbol})")
    print(f"{'='*60}\n")

    try:
        # Step 1: Collect news
        print("Step 1: Collecting news...")
        NOW = pd.Timestamp.now(tz='Asia/Shanghai')
        collection = naked_k_news_enhanced.collect_news_enhanced(
            name, symbol, now=NOW, lookback_days=7, max_items=20
        )
        print(f"  ✅ Collected {len(collection['items'])} news items")

        # Step 2: Load news config
        print("\nStep 2: Loading news config...")
        news_config = naked_k_news_llm.load_news_config(enabled=True)
        news_config = naked_k_news_llm.resolve_news_model(news_config)
        print(f"  ✅ Using model: {news_config.model}")

        # Step 3: Round one assessment
        print("\nStep 3: Running round-one assessment...")
        round1_result = naked_k_news_llm.assess_news_round1(
            name=name,
            ticker=symbol,
            as_of=NOW.isoformat(),
            items=collection['items'],
            config=news_config,
        )
        print(f"  ✅ Round-one status: {round1_result.get('status')}")
        if round1_result.get('status') == 'quarantined':
            print(f"  ⚠️  Quarantine reason: {round1_result.get('quarantine_reason')}")
            return

        # Step 4: Create mock report and technical snapshot
        print("\nStep 4: Creating mock technical data...")
        report = InstrumentReport(
            ticker=symbol,
            name=name,
            action="观望",
            signal_state="watching",
        )
        report.combined_conclusion = None

        # Mock technical snapshot
        technical_snapshot = {
            "action": "观望",
            "summary": "技术面测试",
            "risk_plan": {"max_loss": 1000},
        }

        # Step 5: Round two deliberation
        print("\nStep 5: Running round-two deliberation...")
        deliberation_result = naked_k_news_llm.deliberate_round2(
            technical_snapshot=technical_snapshot,
            items=collection['items'],
            round1=round1_result,
            risk_context={
                "technical_risk_plan": {"max_loss": 1000},
                "risk_limits": {"risk_per_trade_pct": 1.0},
                "portfolio_limits": {"max_portfolio_risk_pct": 10.0},
            },
            config=news_config,
        )
        print(f"  ✅ Round-two status: {deliberation_result.get('status')}")

        if deliberation_result.get('status') != 'ok':
            print(f"  ⚠️  Fallback reason: {deliberation_result.get('fallback_reason')}")
            return

        # Step 6: Apply deliberation (synthesis)
        print("\nStep 6: Applying deliberation (synthesis)...")
        deliberation = deliberation_result['deliberation']

        # Mock daily data
        daily = pd.DataFrame({
            'close': [100, 101, 102],
            'high': [101, 102, 103],
            'low': [99, 100, 101],
        }, index=pd.date_range('2026-07-29', periods=3, freq='D'))

        try:
            config = TradingConfig()
            combined = naked_k_synthesis.apply_deliberation(
                report,
                daily,
                deliberation,
                intraday=None,
                config=config,
            )
            print(f"  ✅ Synthesis status: {combined.get('status')}")
            print(f"  ✅ Final action: {combined.get('final_action')}")

        except Exception as exc:
            print(f"\n{'!'*60}")
            print(f"❌ NewsIntegrationError caught!")
            print(f"{'!'*60}")
            print(f"Exception type: {type(exc).__name__}")
            print(f"Exception message: {exc}")
            print(f"\nFull traceback:")
            traceback.print_exc()
            print(f"{'!'*60}\n")

            # Print deliberation data for inspection
            print("Deliberation data:")
            print(f"  model_action: {deliberation.get('model_action')}")
            print(f"  decision_reasons: {deliberation.get('decision_reasons')}")
            print(f"  evidence_claims: {len(deliberation.get('evidence_claims', []))} claims")

    except Exception as exc:
        print(f"\n❌ Error in pipeline: {type(exc).__name__}: {exc}")
        traceback.print_exc()

if __name__ == "__main__":
    # Test with tickers that failed in previous runs
    tickers = [
        ("腾讯", "0700.HK"),
        ("小米", "1810.HK"),
        ("PDD", "PDD"),
    ]

    for name, symbol in tickers:
        debug_single_ticker(name, name, symbol)
        print("\n" + "="*60 + "\n")
