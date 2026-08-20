# Repository Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every CLI run require explicit ticker input, remove proven dead or generated files, and leave one accurate maintained documentation set.

**Architecture:** Keep `naked_k_analysis.run_analysis()` and the existing analysis modules intact. Make the CLI a thin explicit-input boundary, reuse the canonical market classifier, delete only production-unreachable code, then consolidate documentation and remove ignored runtime state after all verification.

**Tech Stack:** Python 3, standard-library `argparse` and `unittest`, Git, `rg`.

## Global Constraints

- Keep the naked-K, news, backtest, and current Smart Money behavior intact.
- Do not touch `.worktrees/smart-money-dual-evidence`; it contains unfinished, uncommitted work.
- Preserve `.env` and `.claude/settings.local.json` as local configuration.
- Keep `company_names.json`; it is optional news alias/provider metadata, not a ticker allowlist.
- Do not add dependencies, a watchlist system, a ticker registry, or a new package layout.
- Keep `naked_k_analysis.run_analysis()` and all report schemas unchanged.
- Use `apply_patch` for tracked file edits and deletions.

---

### Task 1: Require explicit ticker arguments

**Files:**
- Modify: `tests/test_naked_k_analysis.py:1-280`
- Modify: `naked_k_analysis.py:60-75`
- Modify: `naked_k_analysis.py:1494-1555`

**Interfaces:**
- Consumes: existing `run_analysis(tickers, journal_path, **kwargs)` where `tickers` is a list of `(name, ticker)` tuples.
- Produces: CLI positional `args.tickers: list[str]`; `main()` passes `[(ticker, ticker), ...]` to `run_analysis()`.

- [ ] **Step 1: Add failing CLI boundary tests**

Change the contextlib import to:

```python
from contextlib import redirect_stderr, redirect_stdout
```

Give `_invoke_main()` a test-only ticker parameter and use it when constructing
`sys.argv` with this exact diff:

```diff
 def _invoke_main(
     self,
     argv,
     *,
+    tickers=("TEST",),
     news_config=None,
     load_news_error=None,
     resolve_error=None,
     run_result=("report", []),
     run_side_effect=None,
 ):
     output = io.StringIO()
     active_news_config = news_config or self._news_config()
     with (
-        patch.object(sys, "argv", ["naked_k_analysis.py", *argv]),
+        patch.object(sys, "argv", ["naked_k_analysis.py", *tickers, *argv]),
```

Add these tests immediately after `_invoke_main()`:

```python
def test_main_requires_ticker_before_any_side_effect(self):
    with (
        patch.object(sys, "argv", ["naked_k_analysis.py"]),
        patch.object(
            naked_k_analysis.naked_k_config,
            "load_trading_config",
            return_value=naked_k_config.TradingConfig(),
        ) as load_config,
        patch.object(
            naked_k_analysis.naked_k_llm,
            "load_llm_config",
            return_value=naked_k_llm.LLMConfig(),
        ) as load_llm,
        patch.object(naked_k_news_llm, "load_news_config") as load_news,
        patch.object(
            naked_k_analysis,
            "run_analysis",
            return_value=("report", []),
        ) as run,
        patch.object(Path, "write_text") as write_report,
        redirect_stdout(io.StringIO()),
        redirect_stderr(io.StringIO()) as error,
    ):
        with self.assertRaises(SystemExit) as raised:
            naked_k_analysis.main()

    self.assertEqual(raised.exception.code, 2)
    self.assertIn("TICKER", error.getvalue())
    load_config.assert_not_called()
    load_llm.assert_not_called()
    load_news.assert_not_called()
    run.assert_not_called()
    write_report.assert_not_called()

def test_main_passes_multiple_tickers_unchanged(self):
    with TemporaryDirectory() as tmpdir:
        exit_code, _, run, _ = self._invoke_main(
            [
                "--report-path",
                str(Path(tmpdir) / "report.md"),
                "--journal-path",
                str(Path(tmpdir) / "journal.jsonl"),
                "--audit-path",
                str(Path(tmpdir) / "audit.jsonl"),
            ],
            tickers=("0700.HK", "nvda"),
        )

    self.assertEqual(exit_code, 0)
    self.assertEqual(
        run.call_args.args[0],
        [("0700.HK", "0700.HK"), ("nvda", "nvda")],
    )
```

Update the two direct `parse_args()` tests so their patched argv starts with an
explicit neutral symbol and assert the parsed value:

```python
with patch.object(sys, "argv", ["naked_k_analysis.py", "TEST"]):
    args = naked_k_analysis.parse_args()
self.assertEqual(args.tickers, ["TEST"])
```

For the explicit news-options parse test, insert `"TEST"` immediately after
`"naked_k_analysis.py"` and add the same `args.tickers` assertion.

- [ ] **Step 2: Run the new tests and confirm RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_naked_k_analysis.NakedKAnalysisTests.test_main_requires_ticker_before_any_side_effect \
  tests.test_naked_k_analysis.NakedKAnalysisTests.test_main_passes_multiple_tickers_unchanged \
  -v
```

Expected: the missing-ticker test fails because the current CLI continues into
configuration, and the multiple-ticker test exits 2 because positionals are not
accepted.

- [ ] **Step 3: Implement the minimum CLI change**

Delete the complete `DEFAULT_TICKERS` constant. Change the parser header to:

```python
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成指定标的的裸K收盘报告")
    parser.add_argument(
        "tickers",
        nargs="+",
        metavar="TICKER",
        help="股票代码，可指定多个",
    )
```

Keep every existing optional argument unchanged. Change the first argument to
`run_analysis()` in `main()` to:

```python
report_text, reports = run_analysis(
    [(ticker, ticker) for ticker in args.tickers],
    journal_path,
    config=config,
    audit_path=audit_path,
    llm_config=llm_config,
    news_config=news_config,
    news_lookback_days=args.news_lookback_days,
    news_max_items=args.news_max_items,
    news_bootstrap_error=news_bootstrap_error,
)
```

Do not add name lookup, validation, case conversion, a `--ticker` alias, or a
watchlist abstraction.

- [ ] **Step 4: Verify GREEN and CLI help**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_naked_k_analysis.NakedKAnalysisTests.test_main_requires_ticker_before_any_side_effect \
  tests.test_naked_k_analysis.NakedKAnalysisTests.test_main_passes_multiple_tickers_unchanged \
  -v
PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_naked_k_analysis -v
python naked_k_analysis.py --help
```

Expected: both focused tests and the complete module pass; help contains
`TICKER [TICKER ...]`.

- [ ] **Step 5: Commit the CLI boundary**

```bash
git add naked_k_analysis.py tests/test_naked_k_analysis.py
git commit -m "refactor(cli): require explicit ticker input" \
  -m "Constraint: Keep run_analysis and report schemas unchanged
Rejected: Add a watchlist or ticker registry | unnecessary configuration
Confidence: high
Scope-risk: narrow"
```

---

### Task 2: Reuse one market classifier

**Files:**
- Modify: `tests/test_naked_k_analysis.py:20-40`
- Modify: `naked_k_analysis.py:75-95`
- Modify: `naked_k_trade.py:150-165`
- Keep: `naked_k_portfolio.py:8-18`

**Interfaces:**
- Consumes: `naked_k_portfolio.classify_market(ticker: str) -> str`.
- Produces: `naked_k_analysis.classify_market` and `naked_k_trade.classify_market` as aliases to that exact function object.

- [ ] **Step 1: Add the failing identity and market-table test**

Add to `NakedKAnalysisTests`:

```python
def test_market_classification_reuses_the_canonical_function(self):
    self.assertIs(naked_k_analysis.classify_market, classify_market)
    self.assertIs(naked_k_trade.classify_market, classify_market)
    cases = {
        "0700.HK": "hk",
        "600519.SS": "cn",
        "000001.SZ": "cn",
        "430139.BJ": "cn",
        "000660.KS": "kr",
        "035720.KQ": "kr",
        "BTC-USD": "crypto",
        "NVDA": "us",
    }
    for ticker, expected in cases.items():
        with self.subTest(ticker=ticker):
            self.assertEqual(naked_k_analysis.classify_market(ticker), expected)
```

- [ ] **Step 2: Run the test and confirm RED**

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_naked_k_analysis.NakedKAnalysisTests.test_market_classification_reuses_the_canonical_function \
  -v
```

Expected: FAIL because analysis owns a divergent function and trade owns a
wrapper rather than the canonical function object.

- [ ] **Step 3: Replace both duplicate functions with aliases**

In `naked_k_analysis.py`, delete its `classify_market()` function and keep the
public name with:

```python
classify_market = naked_k_portfolio.classify_market
```

In `naked_k_trade.py`, delete its delegating `classify_market()` wrapper and use:

```python
classify_market = naked_k_portfolio.classify_market
```

Do not change `naked_k_portfolio.classify_market()`.

- [ ] **Step 4: Verify the classifier and its callers**

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_naked_k_portfolio \
  tests.test_naked_k_analysis.NakedKAnalysisTests.test_market_classification_reuses_the_canonical_function \
  -v
PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_naked_k_analysis -v
```

Expected: all tests pass, including `.BJ`, Korean, crypto, and timezone cases.

- [ ] **Step 5: Commit the classifier consolidation**

```bash
git add naked_k_analysis.py naked_k_trade.py tests/test_naked_k_analysis.py
git commit -m "refactor: reuse canonical market classification" \
  -m "Constraint: Keep one rule table without adding an import cycle
Rejected: Add a shared utility module | portfolio already owns the complete rule
Confidence: high
Scope-risk: narrow"
```

---

### Task 3: Remove dead flow modules and ad-hoc runners

**Files:**
- Delete: `debug_integration_error.py`
- Delete: `run_adjustment_probe.py`
- Delete: `run_single_ticker.py`
- Delete: `run_three.py`
- Delete: `naked_k_flow_eastmoney.py`
- Delete: `naked_k_trade_flow_evidence.py`
- Delete: `tests/test_naked_k_flow_eastmoney.py`
- Delete: `tests/test_naked_k_trade_flow_evidence.py`
- Keep: `naked_k_smart_money_contracts.py`
- Keep: `naked_k_smart_money_fusion.py`
- Keep: `naked_k_price_evidence.py`

**Interfaces:**
- Consumes: the explicit-ticker CLI from Task 1, which replaces the runner scripts.
- Produces: no new API; removes only production-unreachable modules and manual wrappers.

- [ ] **Step 1: Prove the deprecated modules still pass their isolated baseline**

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_naked_k_flow_eastmoney \
  tests.test_naked_k_trade_flow_evidence \
  -v
```

Expected: OK. This records that deletion is intentional dead-code removal, not
a response to failing tests.

- [ ] **Step 2: Verify there are no production imports**

```bash
rg -n '^(from|import) naked_k_(flow_eastmoney|trade_flow_evidence)' \
  --glob '*.py' \
  --glob '!tests/test_naked_k_flow_eastmoney.py' \
  --glob '!tests/test_naked_k_trade_flow_evidence.py' \
  .
```

Expected: only `naked_k_trade_flow_evidence.py` importing the deprecated
provider; no retained production caller.

- [ ] **Step 3: Delete the eight tracked files with `apply_patch`**

Apply one patch containing these exact directives:

```text
*** Delete File: debug_integration_error.py
*** Delete File: run_adjustment_probe.py
*** Delete File: run_single_ticker.py
*** Delete File: run_three.py
*** Delete File: naked_k_flow_eastmoney.py
*** Delete File: naked_k_trade_flow_evidence.py
*** Delete File: tests/test_naked_k_flow_eastmoney.py
*** Delete File: tests/test_naked_k_trade_flow_evidence.py
```

- [ ] **Step 4: Verify absence and retained Smart Money behavior**

```bash
test ! -e debug_integration_error.py
test ! -e run_adjustment_probe.py
test ! -e run_single_ticker.py
test ! -e run_three.py
test ! -e naked_k_flow_eastmoney.py
test ! -e naked_k_trade_flow_evidence.py
test ! -e tests/test_naked_k_flow_eastmoney.py
test ! -e tests/test_naked_k_trade_flow_evidence.py
! rg -n '^(from|import) naked_k_(flow_eastmoney|trade_flow_evidence)' --glob '*.py' .
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_naked_k_smart_money_contracts \
  tests.test_naked_k_smart_money_fusion \
  tests.test_naked_k_price_evidence \
  tests.test_dual_evidence_integration \
  -v
```

Expected: all absence/import gates succeed and retained dual-evidence tests pass.

- [ ] **Step 5: Commit dead-code deletion**

```bash
git add -u \
  debug_integration_error.py run_adjustment_probe.py run_single_ticker.py run_three.py \
  naked_k_flow_eastmoney.py naked_k_trade_flow_evidence.py \
  tests/test_naked_k_flow_eastmoney.py tests/test_naked_k_trade_flow_evidence.py
git commit -m "refactor: remove deprecated flow and ad-hoc runners" \
  -m "Constraint: Preserve contracts, fusion, price evidence, and unfinished worktree
Rejected: Remove all dual-evidence code | conflicts with active unfinished work
Confidence: high
Scope-risk: moderate"
```

---

### Task 4: Consolidate maintained documentation

**Files:**
- Create: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Replace: `docs/superpowers/smart-money-user-guide.md`
- Modify: `docs/superpowers/specs/2026-08-17-smart-money-dual-evidence-design.md`
- Modify: `docs/superpowers/plans/2026-08-18-smart-money-dual-evidence-phase-0-3.md`
- Delete: the 36 obsolete documents listed in Step 6.

**Interfaces:**
- Consumes: Task 1 CLI syntax and Task 3 deletion list.
- Produces: one user entry point (`README.md`), one release history (`CHANGELOG.md`), synchronized developer instructions, and current Smart Money guidance.

- [ ] **Step 1: Create the consolidated changelog**

Create `CHANGELOG.md` with exactly this content:

```markdown
# Changelog

This file keeps a concise history of user-visible changes. Git history and tags
remain the detailed implementation archive.

## Unreleased

- Require one or more explicit ticker arguments for every CLI run.
- Remove ad-hoc ticker runners and deprecated, production-unreachable trade-flow modules.
- Consolidate project documentation and keep generated reports outside the maintained tree.

## v3.5.1 — 2026-08-19

- Fixed timezone-aware versus timezone-naive comparisons in recent-signal windows.
- Hardened intraday proxy collection and its public entry-point coverage.
- Removed unused intraday-flow payload fields while preserving report keys.

## v3.4.1 — 2026-08-17

- Added deterministic OHLCV volume/price proxy signals and signal-freshness handling.
- Corrected zero-position and avoid-action exposure semantics.
- These rules are uncalibrated proxy evidence; they do not identify institutions or provide probabilities.

## v3.3.1 — 2026-08-04

- Extended SEC material-event collection to both 8-K and 6-K filings.
- Preserved distinct same-day filings by accession-aware titles.
- Kept provider failures nonfatal to the technical report.

## v3.2.0 — 2026-07-21

- Added optional Finnhub news and company alias/provider metadata.
- Added multi-source news relevance scoring and provider-specific fallbacks.

## v3.1.0

- Added Korean market normalization and session timezone handling.
- Hardened the two-pass news evidence boundary and deterministic fallback.

## v3.0.0

- Split the professional naked-K workflow into focused planning, structure,
  trade, risk, portfolio, audit, backtest, and optional LLM/news modules.

## v2.0.0

- Removed the former multi-indicator advisor and focused the repository on
  candlesticks, OHLCV price structure, triggers, invalidation, targets, and journaling.
```

Do not add a `v3.5.0` release heading: the repository has no `v3.5.0` tag and
its old status document contains contradicted completion claims.

- [ ] **Step 2: Update the user-facing README**

Replace the quick-start block with:

````markdown
## 快速开始

```bash
pip install -r requirements.txt
python naked_k_analysis.py 0700.HK
python naked_k_analysis.py 0700.HK TSLA --news
python naked_k_analysis.py QQQ --json
python -m unittest discover -v
```

每次运行必须显式给出一个或多个 ticker。项目不维护默认股票池或股票白名单；
`company_names.json` 只为部分标的补充新闻别名和 provider 映射。

**输出**：`reports/naked_k_latest.md`、`reports/naked_k_journal.jsonl`、
`reports/naked_k_audit.jsonl`。
````

Because the outer plan is Markdown, preserve the inner fenced block exactly in
the file. Replace the version-specific “v3.5.1 改进” list with one line:

```markdown
版本变化见 [CHANGELOG.md](CHANGELOG.md)。
```

Change `配置见 config.json` to:

```markdown
配置格式见 `config.example.json`；复制为自己的 JSON 文件后通过 `--config-path` 指定。
```

Change the data-source line to the actual fallback order:

```markdown
**数据**

westock-data CLI → 腾讯K线 → Yahoo chart JSON → yfinance 自动降级，支持港股/A股/北交所/美股/韩股。
```

Remove the fixed test-count claim. Keep the existing disclaimer and license.

- [ ] **Step 3: Synchronize developer command and architecture docs**

In `AGENTS.md`, replace its command block with:

```bash
python naked_k_analysis.py 0700.HK
python naked_k_analysis.py 0700.HK --json
```

Add this sentence under `Main Entry`:

```markdown
- Requires one or more positional ticker symbols; there is no default pool or allowlist.
```

In `CLAUDE.md`, replace the four run commands with:

```bash
python naked_k_analysis.py 0700.HK          # explicit ticker; multiple tickers are accepted
python naked_k_analysis.py 0700.HK --json   # also emit JSON payload
python naked_k_analysis.py 0700.HK --llm    # optional OpenAI-compatible commentary
python naked_k_analysis.py 0700.HK --news   # optional two-pass news deliberation
```

Apply these exact prose replacements in `CLAUDE.md`:

- `naked_k_analysis.py is the CLI orchestrator (~1200 lines).` →
  `naked_k_analysis.py is the CLI orchestrator.`
- Replace the `naked_k_smart_money.py` description with:

```markdown
- `naked_k_smart_money.py` — deterministic OHLCV volume/price proxy rules for accumulation-like behavior and buying/selling exhaustion. Outputs are uncalibrated advisory evidence, not institutional identity or probability.
```

- Replace the Finnhub `zero-config fallback` wording with
  `optional API-key integration with a no-key fallback`.
- Delete the line linking the removed 2026-07-20 news design; keep the safety
  rules immediately below it.
- Replace `Default ticker pool: ...` with:

```markdown
The CLI has no ticker allowlist or default pool; every run supplies its symbols explicitly.
```

- Delete the manual `run_*.py` naming rule and the sentence claiming
  `AGENTS.md` is stale.

- [ ] **Step 4: Replace the stale Smart Money guide**

Replace `docs/superpowers/smart-money-user-guide.md` with exactly:

````markdown
# OHLCV 量价代理证据使用指南

## 使用

量价代理证据默认参与技术报告，但每次运行仍需显式提供 ticker：

```bash
python naked_k_analysis.py 0700.HK
python naked_k_analysis.py 0700.HK --config-path config.example.json
```

报告中的 `smart_money_signals` 来自 OHLCV 规则，例如放量窄幅、买卖衰竭和多周期价格区域。它们只能描述价格与成交量行为，不能识别机构、受益所有人或“主力”身份，也不是经过校准的概率。

## 解读边界

- `signals`：保留检测到的规则信号；每条信号的 `stale` 标记表示是否超过当前方向判断的时效窗口。
- `signal_count_3m` / `signal_dates_3m`：近三个月的规则命中记录，不是交易绩效。
- `overall_assessment` / `direction`：只由仍在时效窗口内的规则信号决定。
- 单条信号中的 `confidence` 是未校准的规则强度，不是胜率或概率。
- 缺失的逐笔、持仓或资金流数据表示不可用，不等于零。
- 量价证据不得单独改变触发、止损、仓位或组合暴露。

## 配置

当前 main 对用户稳定承诺的开关只有 `enabled`。禁用：

```json
{
  "smart_money": {
    "enabled": false
  }
}
```

`price_action`、`trade_flow` 和 `short_selling` 阈值属于仍在实验的 dual-evidence 工作；当前 main 的旧 OHLCV 汇总路径不会完整应用这些嵌套阈值，也不应被描述成已获得独立机构资金证据。配置结构见 `config.example.json`，但不要把实验字段写成稳定生效的用户接口。

## 输出检查顺序

1. 先看 `action` 与 `risk_plan.status`。
2. 再看 `suggested_gross_pct` 与 `effective_account_risk_pct`。
3. 最后把量价代理作为辅助解释。

`flat`、零 gross 或尚未触发的计划不是当前持仓；条件计划应表述为“突破后才执行”。
````

- [ ] **Step 5: Repair references in retained Smart Money design and plan**

Make these exact reference changes:

- In `docs/superpowers/specs/2026-08-17-smart-money-dual-evidence-design.md`,
  change `CLAUDE.md、README.md、RELEASE_NOTES*` to
  `CLAUDE.md、README.md、CHANGELOG.md`, and change `默认标的回归` to
  `显式 ticker CLI 回归`. Keep its Eastmoney provider filename as a
  future-design reference.
- In `docs/superpowers/plans/2026-08-18-smart-money-dual-evidence-phase-0-3.md`:
  - change `Non-HK default tickers` to `Requested non-HK tickers`;
  - replace the three Task 11 `RELEASE_NOTES*` file-list rows with
    `- Modify: CHANGELOG.md`;
  - replace the three release-note entries in `CURRENT_DOCS` with
    `"CHANGELOG.md"`;
  - replace the three release-note paths in the Task 11 `git add` command with
    `CHANGELOG.md`;
  - replace the three release-note paths in the final probability-claim `rg`
    command with `CHANGELOG.md`.
  Keep the provider/test filenames because this retained plan describes the
  separate unfinished worktree.

- [ ] **Step 6: Delete the obsolete documentation with `apply_patch`**

Delete these 17 root files:

```text
FINNHUB_FINAL_REPORT.md
FINNHUB_INTEGRATION_SUMMARY.md
FINNHUB_QUICKSTART.md
FINNHUB_SETUP.md
NEWS_ENHANCEMENT_PLAN.md
NEWS_IMPROVEMENT_SUMMARY.md
NEWS_INTEGRATION_ANALYSIS.md
NEWS_OPTIMIZATION_SUMMARY.md
NEWS_SOURCES_PROPOSAL.md
OPTIMIZATION_COMPLETE.md
RELEASE_NOTES.md
RELEASE_NOTES_v3.2.0.md
RELEASE_NOTES_v3.3.1.md
RELEASE_NOTES_v3.4.0.md
RELEASE_NOTES_v3.4.1.md
RELEASE_v3.5.0.md
RELEASE_v3.5.1.md
```

Delete these 14 status/delivery files:

```text
docs/superpowers/2026-08-17-smart-money-final-validation.md
docs/superpowers/2026-08-17-smart-money-hotfix-1.md
docs/superpowers/2026-08-17-smart-money-hotfix-2.md
docs/superpowers/2026-08-17-smart-money-hotfix-3.md
docs/superpowers/2026-08-17-smart-money-hotfix-4-final.md
docs/superpowers/2026-08-17-smart-money-hotfix-5-final.md
docs/superpowers/2026-08-17-smart-money-implementation-summary.md
docs/superpowers/2026-08-17-smart-money-integration-complete.md
docs/superpowers/2026-08-17-smart-money-round-6-final-report.md
docs/superpowers/PROJECT-DELIVERY-REPORT.md
docs/superpowers/completion-report.md
docs/superpowers/final-status.md
docs/superpowers/integration-plan.md
docs/superpowers/work-summary-2026-08-20.md
```

Delete these four superseded plans and one old spec:

```text
docs/superpowers/plans/2026-06-29-intraday-naked-k.md
docs/superpowers/plans/2026-07-06-naked-k-repo-focus.md
docs/superpowers/plans/2026-07-20-news-two-pass-deliberation.md
docs/superpowers/plans/2026-07-31-akshare-news-source.md
docs/superpowers/specs/2026-07-20-news-two-pass-deliberation-design.md
```

- [ ] **Step 7: Verify documentation consistency and links**

Run:

```bash
rg -n --pcre2 'python(?:3)? naked_k_analysis\.py(?:\s*(?:#.*)?$|\s+--)' \
  --glob '!docs/superpowers/plans/2026-08-20-repository-cleanup.md' \
  README.md AGENTS.md CLAUDE.md docs/superpowers
rg -n 'DEFAULT_TICKERS|default ticker pool|默认(股票|标的)|固定标的' \
  --glob '!.worktrees/**' \
  --glob '!docs/superpowers/specs/2026-08-20-repository-cleanup-design.md' \
  --glob '!docs/superpowers/plans/2026-08-20-repository-cleanup.md' \
  .
rg -n '\b(debug_integration_error|run_adjustment_probe|run_single_ticker|run_three|naked_k_flow_eastmoney|naked_k_trade_flow_evidence)\b' \
  --glob '*.py' --glob '*.md' \
  --glob '!.worktrees/**' \
  --glob '!docs/superpowers/specs/2026-08-20-repository-cleanup-design.md' \
  --glob '!docs/superpowers/plans/2026-08-20-repository-cleanup.md' \
  --glob '!docs/superpowers/specs/2026-08-17-smart-money-dual-evidence-design.md' \
  --glob '!docs/superpowers/plans/2026-08-18-smart-money-dual-evidence-phase-0-3.md'
rg -n 'FINNHUB_(FINAL_REPORT|INTEGRATION_SUMMARY|QUICKSTART|SETUP)\.md|NEWS_(ENHANCEMENT_PLAN|IMPROVEMENT_SUMMARY|INTEGRATION_ANALYSIS|OPTIMIZATION_SUMMARY|SOURCES_PROPOSAL)\.md|OPTIMIZATION_COMPLETE\.md|RELEASE_NOTES(_v[^` ]+)?\.md|RELEASE_v[^` ]+\.md' \
  --glob '*.md' \
  --glob '!.worktrees/**' \
  --glob '!docs/superpowers/specs/2026-08-20-repository-cleanup-design.md' \
  --glob '!docs/superpowers/plans/2026-08-20-repository-cleanup.md' \
  .
```

Expected: all four commands produce no output. The two excluded Smart Money
documents intentionally describe future worktree files.

Run the standard-library local-link checker:

```bash
python -c 'from pathlib import Path; import re,subprocess,sys; bad=[]; skip=Path("docs/superpowers/plans/2026-08-20-repository-cleanup.md"); files=[Path(p) for p in subprocess.check_output(["git","ls-files","*.md"], text=True).splitlines() if Path(p).is_file() and Path(p) != skip]; [(bad.append(f"{f}: {target}") if not (f.parent / target.split("#",1)[0]).exists() else None) for f in files for raw in re.findall(r"\[[^]]*\]\(([^)]+)\)", f.read_text(encoding="utf-8")) for target in [raw.strip().strip("<>").split(maxsplit=1)[0]] if target and not target.startswith("#") and not re.match(r"^(?:https?|mailto):", target)]; print(*bad, sep="\n"); sys.exit(bool(bad))'
```

Expected: no output and exit 0.

- [ ] **Step 8: Commit documentation consolidation**

Stage explicit maintained files plus tracked deletions; do not use `git add -A`:

```bash
git add CHANGELOG.md README.md AGENTS.md CLAUDE.md \
  docs/superpowers/smart-money-user-guide.md \
  docs/superpowers/specs/2026-08-17-smart-money-dual-evidence-design.md \
  docs/superpowers/plans/2026-08-18-smart-money-dual-evidence-phase-0-3.md
git add -u -- \
  FINNHUB_FINAL_REPORT.md FINNHUB_INTEGRATION_SUMMARY.md FINNHUB_QUICKSTART.md FINNHUB_SETUP.md \
  NEWS_ENHANCEMENT_PLAN.md NEWS_IMPROVEMENT_SUMMARY.md NEWS_INTEGRATION_ANALYSIS.md \
  NEWS_OPTIMIZATION_SUMMARY.md NEWS_SOURCES_PROPOSAL.md OPTIMIZATION_COMPLETE.md \
  RELEASE_NOTES.md RELEASE_NOTES_v3.2.0.md RELEASE_NOTES_v3.3.1.md \
  RELEASE_NOTES_v3.4.0.md RELEASE_NOTES_v3.4.1.md RELEASE_v3.5.0.md RELEASE_v3.5.1.md \
  docs/superpowers/2026-08-17-smart-money-final-validation.md \
  docs/superpowers/2026-08-17-smart-money-hotfix-1.md \
  docs/superpowers/2026-08-17-smart-money-hotfix-2.md \
  docs/superpowers/2026-08-17-smart-money-hotfix-3.md \
  docs/superpowers/2026-08-17-smart-money-hotfix-4-final.md \
  docs/superpowers/2026-08-17-smart-money-hotfix-5-final.md \
  docs/superpowers/2026-08-17-smart-money-implementation-summary.md \
  docs/superpowers/2026-08-17-smart-money-integration-complete.md \
  docs/superpowers/2026-08-17-smart-money-round-6-final-report.md \
  docs/superpowers/PROJECT-DELIVERY-REPORT.md docs/superpowers/completion-report.md \
  docs/superpowers/final-status.md docs/superpowers/integration-plan.md \
  docs/superpowers/work-summary-2026-08-20.md \
  docs/superpowers/plans/2026-06-29-intraday-naked-k.md \
  docs/superpowers/plans/2026-07-06-naked-k-repo-focus.md \
  docs/superpowers/plans/2026-07-20-news-two-pass-deliberation.md \
  docs/superpowers/plans/2026-07-31-akshare-news-source.md \
  docs/superpowers/specs/2026-07-20-news-two-pass-deliberation-design.md
git commit -m "docs: consolidate current project guidance" \
  -m "Constraint: Keep current Smart Money specs and plans
Rejected: Preserve completion reports | Git history already archives them
Confidence: high
Scope-risk: moderate"
```

---

### Task 5: Full verification and runtime-state removal

**Files:**
- Verify: all retained tracked Python and Markdown files.
- Delete ignored runtime: `reports/`, `naked_k_reports/`, `.pytest_cache/`, `__pycache__/`, `tests/__pycache__/`, `.code-review-graph/`, `.superpowers/`, then `.omc/` as the last OMC action.
- Preserve: `.worktrees/`, `.env`, `.claude/`.

**Interfaces:**
- Consumes: Tasks 1-4 completed and committed.
- Produces: a clean tracked tree and no approved runtime artifacts in the main checkout.

- [ ] **Step 1: Run the complete automated gate**

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -v
git diff --check 10d6267..HEAD
git diff --check
git status --short --branch
```

Expected: full suite `OK`, no diff-check errors, and only intentional plan
tracking or verifier changes appear in status.

- [ ] **Step 2: Obtain an independent review**

Give a fresh verifier/code-reviewer this exact scope:

```text
Review HEAD against 10d6267 and the approved repository-cleanup spec. Check CLI no-ticker side effects, ticker ordering, classifier identity, deleted-module reachability, retained dual-evidence behavior, documentation truth, broken links, ignored runtime boundaries, and untouched .worktrees/.env/.claude. Report findings by severity and do not self-approve implementation changes.
```

Expected: no critical or important findings. If findings exist, fix them with
tests, rerun the focused and full gates, and commit only the remediation files.

- [ ] **Step 3: Inspect exact runtime targets before deletion**

```bash
du -sh -- reports naked_k_reports .pytest_cache __pycache__ tests/__pycache__ \
  .code-review-graph .superpowers .omc 2>/dev/null || true
git status --short --ignored
git -C .worktrees/smart-money-dual-evidence status --short
```

Expected: targets are ignored generated state; the separate worktree still
shows its pre-existing unfinished changes and is not included in deletion.

- [ ] **Step 4: Delete only the approved explicit runtime paths**

```bash
rm -rf -- \
  ./reports \
  ./naked_k_reports \
  ./.pytest_cache \
  ./__pycache__ \
  ./tests/__pycache__ \
  ./.code-review-graph \
  ./.superpowers
```

Do not use `find`, a glob, an environment variable, `~`, or a recursive parent
path. The user separately rotates `FINNHUB_API_KEY`; local file deletion cannot
revoke an exposed credential.

- [ ] **Step 5: Verify final filesystem and Git state**

```bash
test ! -e reports
test ! -e naked_k_reports
test ! -e .pytest_cache
test ! -e __pycache__
test ! -e tests/__pycache__
test ! -e .code-review-graph
test ! -e .superpowers
test -e .omc
test -e .worktrees/smart-money-dual-evidence
test -e .env
test -e .claude/settings.local.json
git status --short --branch
git log -5 --oneline --decorate
```

Expected: all non-OMC runtime paths are absent, preserved paths exist, and the
tracked main tree is clean.

No commit is needed for ignored runtime deletion.

- [ ] **Step 6: End OMC state and remove its local snapshot last**

After all OMC-guided implementation, verification, review, and remediation are
complete, clear/end the OMC workflow and make this the last filesystem action:

```bash
rm -rf -- ./.omc
test ! -e .omc
```

Do not call another OMC state tool after this step. Use the already captured
test, review, Git, and filesystem results for the final user report.
