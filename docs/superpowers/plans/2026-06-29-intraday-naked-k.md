# Intraday Naked K Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an intraday `1h` confirmation layer to the naked K report without overriding the daily/weekly plan.

**Architecture:** `naked_k_analysis.py` keeps daily/weekly as the source of the trade plan. A new intraday helper evaluates recent `1h` bars against the plan's trigger and stop levels, producing a status string and evidence fields that are written to JSON, journal, and Markdown.

**Tech Stack:** Python, pandas, existing `westock_wrapper.download()`, `unittest`.

## Global Constraints

- Do not change the daily/weekly action decision from intraday data.
- Treat zero-volume latest `1h` bars as unconfirmed.
- Keep all new behavior covered by `tests/test_naked_k_analysis.py`.

---

### Task 1: Intraday Status Helper

**Files:**
- Modify: `naked_k_analysis.py`
- Test: `tests/test_naked_k_analysis.py`

**Interfaces:**
- Consumes: `build_intraday_status(frame, action, entry_trigger, stop_loss)`
- Produces: `dict[str, object]` with `status`, `note`, `latest_time`, `latest_close`, `latest_high`, `latest_low`, `latest_volume`, `source`

- [ ] **Step 1: Write failing tests** for near-trigger, confirmed breakout, unconfirmed zero-volume latest bar, and near-stop behavior.
- [ ] **Step 2: Run targeted tests** with `python -m unittest tests.test_naked_k_analysis -v` and confirm failures are due to missing helper.
- [ ] **Step 3: Implement minimal helper** in `naked_k_analysis.py`.
- [ ] **Step 4: Run targeted tests** and confirm they pass.

### Task 2: Wire Intraday Into Reports

**Files:**
- Modify: `naked_k_analysis.py`
- Modify: `README.md`
- Test: `tests/test_naked_k_analysis.py`

**Interfaces:**
- Consumes: `load_ohlcv(ticker, interval="1h", period="5d")`
- Produces: `InstrumentReport.intraday_status`

- [ ] **Step 1: Add failing tests** that `InstrumentReport`, journal payload, and Markdown include intraday status.
- [ ] **Step 2: Run targeted tests** and confirm failures.
- [ ] **Step 3: Add optional intraday argument to `build_trade_plan()` and load it in `run_analysis()`.
- [ ] **Step 4: Update README naked K section with intraday fields.
- [ ] **Step 5: Run `python -m unittest discover -v` and confirm all tests pass.
