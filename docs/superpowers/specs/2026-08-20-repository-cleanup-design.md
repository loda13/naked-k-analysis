# Repository Cleanup Design

**Date:** 2026-08-20  
**Status:** Approved for planning

## Goal

Turn the repository into a focused command-line tool: users must name every
ticker explicitly, tracked files describe or implement current behavior, and
runtime output stays outside the maintained project tree.

## Constraints

- Keep the naked-K, news, backtest, and current Smart Money behavior intact.
- Do not touch `.worktrees/smart-money-dual-evidence`; it contains unfinished,
  uncommitted work.
- Preserve `.env` as local configuration.
- Keep `company_names.json`; it is optional news alias/provider metadata, not a
  ticker allowlist.
- Do not add dependencies, a watchlist system, a ticker registry, or a new
  package layout.

## Command-Line Interface

`naked_k_analysis.py` accepts one or more required positional ticker symbols:

```bash
python naked_k_analysis.py 0700.HK
python naked_k_analysis.py 0700.HK TSLA --news
```

`DEFAULT_TICKERS` is removed. Each CLI symbol becomes `(ticker, ticker)` when
passed to the existing `run_analysis()` API. With no ticker, `argparse` exits
with status 2 before configuration loading, network access, or output writes.
The programmatic `run_analysis()` interface and report schemas do not change.

## Tracked File Cleanup

Delete ad-hoc runners that the unified CLI replaces:

- `debug_integration_error.py`
- `run_adjustment_probe.py`
- `run_single_ticker.py`
- `run_three.py`

Delete the two production-unreachable, explicitly deprecated flow modules and
their module-specific tests:

- `naked_k_flow_eastmoney.py`
- `naked_k_trade_flow_evidence.py`
- `tests/test_naked_k_flow_eastmoney.py`
- `tests/test_naked_k_trade_flow_evidence.py`

Keep the current dual-evidence contracts, fusion, and price-evidence modules.
They are experimental and imperfect, but removing them would conflict with the
unfinished Smart Money worktree and would exceed this cleanup's safe scope.

Use `naked_k_portfolio.classify_market()` as the single market classifier;
remove the divergent implementation in `naked_k_analysis.py`. Keep the existing
technical module boundaries: patterns, structure, zones, trade rules, planner,
CLI, backtest, and external news providers remain separate.

## Documentation Cleanup

Keep the maintained top-level documentation:

- `README.md`
- `CHANGELOG.md` (new consolidated release history)
- `AGENTS.md`, `LICENSE`

Remove the root-level `FINNHUB_*`, `NEWS_*`, `OPTIMIZATION_COMPLETE.md`,
`RELEASE_NOTES*`, and `RELEASE_v*` implementation/status documents after their
still-current setup and limitation details are folded into `README.md` and
`CHANGELOG.md`.

Under `docs/superpowers/`, keep the current Smart Money user guide, Smart Money
specs, and the two 2026-08-18 qualification plans. Remove completed hotfix,
delivery, completion, status, work-summary, old news, and old repository-focus
documents. Git history remains the archive for deleted project-status reports.

Update every retained command example so it supplies at least one ticker. Do
not describe any ticker as enabled, allowed, preferred, or default.

## Runtime Cleanup

Delete ignored generated state after implementation and verification:

- `reports/` in full, including historical journal and audit files
- `naked_k_reports/`
- `.pytest_cache/`
- root and test `__pycache__/`
- `.code-review-graph/`
- `.superpowers/`
- `.omc/` after the OMC-guided task is complete

Do not delete `.worktrees/` or `.env`. Existing `.gitignore` rules
already cover runtime output; no new broad ignore rule is needed.

The ignored `.omc/project-memory.json` contained a plaintext Finnhub credential.
Deleting the file removes the local copy but does not revoke the credential;
the user must rotate `FINNHUB_API_KEY` separately.

## Verification

Use test-first changes for the CLI boundary:

1. Prove a missing ticker exits 2 without calling `run_analysis()`.
2. Prove multiple ticker arguments reach `run_analysis()` in input order.
3. Update existing CLI tests to pass an explicit neutral test symbol.
4. Run focused CLI tests, then `python -m unittest discover -v`.
5. Search retained source and documentation for `DEFAULT_TICKERS`, removed
   filenames, default-stock wording, and broken Markdown links.
6. Independently review the final diff and rerun the full suite before claiming
   completion.

Runtime directories are removed only after the last test/review command that
may recreate them.
