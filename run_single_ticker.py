import sys
from pathlib import Path
from naked_k_analysis import run_analysis
import naked_k_news_llm
import naked_k_config

# Load news config
news_config = naked_k_news_llm.load_news_config(enabled=True)
news_config = naked_k_news_llm.resolve_news_model(news_config)

# Run analysis for single ticker
tickers = [("腾讯", "0700.HK")]
journal_path = Path("reports/naked_k_journal.jsonl")
audit_path = Path("reports/naked_k_audit.jsonl")
config = naked_k_config.TradingConfig()

try:
    report_text, reports = run_analysis(
        tickers,
        journal_path,
        config=config,
        audit_path=audit_path,
        news_config=news_config,
    )
    print("Analysis completed")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
