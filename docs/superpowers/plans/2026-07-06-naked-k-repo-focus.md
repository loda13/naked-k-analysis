# Naked K Repo Focus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the repository from a mixed MA/indicator advisor into a focused `naked-k-analysis` project.

**Architecture:** Keep `naked_k_analysis.py` as the CLI and report engine, extract pure candlestick pattern detection into `naked_k_patterns.py`, and keep `westock_wrapper.py` as the only market data adapter. Delete the old MA/indicator advisor modules and their tests after the naked K path no longer imports them.

**Tech Stack:** Python 3, pandas, requests/yfinance fallback data, unittest.

## Global Constraints

- Project name: `naked-k-analysis`.
- Chinese product name: `裸 K 分析`.
- Remove the old MA/indicator advisor system completely from the active codebase.
- Preserve naked K behavior: pattern detection, trigger/stop planning, ATR buffer, intraday confirmation, journal output, Markdown/JSON reports.
- Use TDD for the extraction: write failing naked K pattern/import tests before removing the old provider module.

---

### Task 1: Extract Naked K Pattern Detection

**Files:**
- Create: `naked_k_patterns.py`
- Modify: `naked_k_analysis.py`
- Modify: `tests/test_naked_k_analysis.py`
- Create: `tests/test_naked_k_patterns.py`

**Interfaces:**
- Produces: `detect_kline_patterns(frame: pandas.DataFrame) -> list[str]`
- Produces: `detect_inside_bar(frame: pandas.DataFrame) -> str | None`
- Consumes: `naked_k_analysis.detect_price_action_patterns(frame)`

- [ ] **Step 1: Write failing tests** importing `naked_k_patterns` and asserting bullish engulfing, bearish pin, and inside bar labels.
- [ ] **Step 2: Run `python -m unittest tests.test_naked_k_patterns -v` and confirm it fails because `naked_k_patterns` does not exist.**
- [ ] **Step 3: Implement `naked_k_patterns.py` with only candlestick logic copied from the old MA script.**
- [ ] **Step 4: Update `naked_k_analysis.py` to import `naked_k_patterns` instead of `ma_analysis`.**
- [ ] **Step 5: Run `python -m unittest tests.test_naked_k_patterns tests.test_naked_k_analysis -v` and confirm the naked K tests pass.**

### Task 2: Remove Old Indicator System

**Files:**
- Delete: `ma_analysis.py`
- Delete: `stock_advisor.py`
- Delete: `ma_daily_report.sh`
- Delete: `stock_analysis/__init__.py`
- Delete: `stock_analysis/advisor.py`
- Delete: `stock_analysis/data.py`
- Delete: `stock_analysis/jg_methodology.py`
- Delete: `stock_analysis/models.py`
- Delete: `stock_analysis/report.py`
- Delete: `stock_analysis/technical.py`
- Delete: `tests/test_advisor.py`
- Delete: `tests/test_cli.py`
- Delete: `tests/test_data.py`
- Delete: `tests/test_jg_methodology.py`
- Delete: `tests/test_ma_analysis.py`
- Delete: `tests/test_report.py`
- Delete: `tests/test_technical.py`
- Modify: `westock_wrapper.py`
- Modify: `tests/__init__.py`

**Interfaces:**
- Produces: `westock_wrapper.normalize_provider_ticker(ticker: str) -> str`
- Produces: `westock_wrapper.convert_ticker(ticker: str) -> str`

- [ ] **Step 1: Write/update tests proving `westock_wrapper.convert_ticker()` handles HK, US, SH, and SZ tickers without `stock_analysis.data`.**
- [ ] **Step 2: Run targeted tests and confirm the import dependency fails before implementation.**
- [ ] **Step 3: Move ticker normalization into `westock_wrapper.py`.**
- [ ] **Step 4: Delete old MA/indicator modules and tests.**
- [ ] **Step 5: Run `python -m unittest discover -v` and confirm only naked K/data wrapper tests remain and pass.**

### Task 3: Rename Project Copy and Release Notes

**Files:**
- Rewrite: `README.md`
- Rewrite: `CLAUDE.md`
- Create: `RELEASE_NOTES.md`
- Modify: `tests/__init__.py`

**Interfaces:**
- Produces: README focused on `python naked_k_analysis.py`.
- Produces: release notes for the focused naked K release.

- [ ] **Step 1: Rewrite README title, usage, features, and testing sections around naked K only.**
- [ ] **Step 2: Rewrite CLAUDE.md developer notes around the slimmed file layout.**
- [ ] **Step 3: Add release notes describing removal of the old indicator system and the new naked K focus.**
- [ ] **Step 4: Run `rg -n "stock-ma-analysis|Stock MA Analysis|stock_advisor|ma_analysis|MA20|Vegas|一目云|MACD|RSI|BOLL|FRVP|AVWAP" README.md CLAUDE.md tests naked_k_analysis.py naked_k_patterns.py westock_wrapper.py RELEASE_NOTES.md` and confirm no stale primary positioning remains.**

### Task 4: GitHub and Local Rename

**Files / External State:**
- GitHub repository: `loda13/stock-ma-analysis` -> `loda13/naked-k-analysis`
- Local directory: `/Users/lodatang/Go/stock-ma-analysis` -> `/Users/lodatang/Go/naked-k-analysis`

**Interfaces:**
- Produces: remote URL pointing at `https://github.com/loda13/naked-k-analysis`.
- Produces: current working directory renamed to `/Users/lodatang/Go/naked-k-analysis`.

- [ ] **Step 1: Run local verification before external changes.**
- [ ] **Step 2: Use GitHub CLI to inspect and rename/update release metadata if authenticated.**
- [ ] **Step 3: Rename the local directory after repository files are stable.**
- [ ] **Step 4: Run final tests from the renamed directory.**
