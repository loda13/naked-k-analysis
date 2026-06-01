# Wall Street Skill Advisor Milestone 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working `stock_advisor.py` CLI that combines cached Wall Street Skill context, optional existing technical analyzers, and deterministic short/medium/long recommendations.

**Architecture:** Add a small `stock_analysis` package with focused modules for cache loading, optional technical/naked-K adapters, advisor rules, and report rendering. Runtime Wall Street Skill cache files stay ignored; tests use sanitized fixtures. Existing scripts keep their current CLI behavior.

**Tech Stack:** Python 3 standard library for the new package and tests; optional runtime use of existing `ma_analysis.py`, `naked_k_analysis.py`, pandas/yfinance when installed.

---

## File Structure

- Create `stock_analysis/__init__.py`: package marker.
- Create `stock_analysis/models.py`: dataclasses and enum-like strings shared across modules.
- Create `stock_analysis/cache.py`: load Wall Street Skill JSON cache and classify freshness.
- Create `stock_analysis/technical.py`: optional adapter around `ma_analysis.analyze(..., output_json=True)`.
- Create `stock_analysis/naked_k.py`: optional adapter around `naked_k_analysis.analyze_one(..., as_json=True)`.
- Create `stock_analysis/advisor.py`: deterministic recommendation rules from the spec.
- Create `stock_analysis/report.py`: Chinese text report and JSON serialization helpers.
- Create `stock_advisor.py`: CLI entrypoint.
- Modify `.gitignore`: ignore runtime WSS cache/session artifacts.
- Modify `westock_wrapper.py`: make the `westock-data` script path configurable through `WESTOCK_DATA_SCRIPT`.
- Create `tests/test_advisor.py`: deterministic advisor behavior tests.
- Create `tests/test_cache.py`: cache loading and safety tests.
- Create `tests/test_cli.py`: CLI behavior tests.
- Create `tests/fixtures/wss/research.json`, `market_risk.json`, `earnings.json`: sanitized fixture cache.

## Task 1: Cache Safety And Fixtures

**Files:**
- Create: `.gitignore`
- Create: `tests/fixtures/wss/research.json`
- Create: `tests/fixtures/wss/market_risk.json`
- Create: `tests/fixtures/wss/earnings.json`
- Test: `tests/test_cache.py`

- [ ] **Step 1: Write failing tests**

```python
import os
import unittest

from stock_analysis.cache import load_wss_context


class CacheTests(unittest.TestCase):
    def test_loads_sanitized_fixture_context(self):
        ctx = load_wss_context("tests/fixtures/wss")
        self.assertEqual(ctx.research.tickers["NVDA"].score, 74)
        self.assertEqual(ctx.market.market_state, "警戒观察")
        self.assertEqual(ctx.earnings.events["NVDA"].timing, "盘后")

    def test_runtime_cache_paths_are_gitignored(self):
        with open(".gitignore", "r", encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("data/cache/", text)
        self.assertIn(".wss-session/", text)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_cache -v`

Expected: FAIL or ERROR because `stock_analysis.cache` does not exist yet.

- [ ] **Step 3: Add fixtures and minimal cache module**

Create the fixture JSON files with NVDA, AMD, AVGO, INTC examples, a market state, and one NVDA earnings event.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_cache -v`

Expected: PASS.

## Task 2: Advisor Rules

**Files:**
- Create: `stock_analysis/models.py`
- Create: `stock_analysis/advisor.py`
- Test: `tests/test_advisor.py`

- [ ] **Step 1: Write failing advisor tests**

```python
import unittest

from stock_analysis.advisor import build_advice
from stock_analysis.cache import load_wss_context
from stock_analysis.models import NakedKSnapshot, TechnicalSnapshot


class AdvisorTests(unittest.TestCase):
    def test_buy_when_research_accepts_and_technical_bullish(self):
        ctx = load_wss_context("tests/fixtures/wss")
        advice = build_advice(
            "NVDA",
            ctx,
            technical=TechnicalSnapshot(direction="bullish", score=2.0, warnings=[]),
            naked=NakedKSnapshot(direction="bullish", invalidation=118.5, supports=[118.5], resistances=[132.0]),
        )
        self.assertEqual(advice.overall_action, "买入")
        self.assertIn("118.5", advice.invalidation)

    def test_avoid_when_research_marks_weak(self):
        ctx = load_wss_context("tests/fixtures/wss")
        advice = build_advice("INTC", ctx, technical=TechnicalSnapshot(direction="bullish", score=2.0, warnings=[]))
        self.assertEqual(advice.overall_action, "回避")

    def test_missing_research_caps_to_watch(self):
        ctx = load_wss_context("tests/fixtures/wss")
        advice = build_advice("UNKNOWN", ctx, technical=TechnicalSnapshot(direction="bullish", score=2.0, warnings=[]))
        self.assertEqual(advice.overall_action, "观望")
        self.assertEqual(advice.confidence, "中")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_advisor -v`

Expected: FAIL or ERROR because advisor/model modules do not exist yet.

- [ ] **Step 3: Implement dataclasses and deterministic rules**

Implement `ResearchEntry`, `MarketRiskSnapshot`, `EarningsEvent`, `WssContext`, `TechnicalSnapshot`, `NakedKSnapshot`, and `Advice`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_advisor -v`

Expected: PASS.

## Task 3: CLI And Reports

**Files:**
- Create: `stock_analysis/report.py`
- Create: `stock_analysis/technical.py`
- Create: `stock_analysis/naked_k.py`
- Create: `stock_advisor.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

```python
import json
import subprocess
import sys
import unittest


class CliTests(unittest.TestCase):
    def test_json_cli_outputs_advice(self):
        proc = subprocess.run(
            [sys.executable, "stock_advisor.py", "NVDA", "--cache-dir", "tests/fixtures/wss", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["ticker"], "NVDA")
        self.assertIn(payload["overall_action"], ["买入", "小仓试错", "持有", "观望"])

    def test_refresh_is_explicitly_not_implemented(self):
        proc = subprocess.run(
            [sys.executable, "stock_advisor.py", "NVDA", "--refresh-wss-cache"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("refresh_not_implemented", proc.stderr)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_cli -v`

Expected: FAIL or ERROR because `stock_advisor.py` does not exist yet.

- [ ] **Step 3: Implement report rendering and CLI**

The CLI should:

- Parse `ticker`, `--cache-dir`, `--json`, `--horizons`, and `--refresh-wss-cache`.
- Return non-zero for refresh in Milestone 1.
- Load WSS context from cache.
- Attempt optional technical/naked-K adapters and continue with warnings if dependencies are missing.
- Print JSON or compact Chinese report.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_cli -v`

Expected: PASS.

## Task 4: Provider Path Portability

**Files:**
- Modify: `westock_wrapper.py`
- Test: `tests/test_westock_wrapper.py`

- [ ] **Step 1: Write failing westock path test**

```python
import os
import unittest
from unittest.mock import patch

import westock_wrapper


class WestockWrapperTests(unittest.TestCase):
    def test_uses_env_script_path(self):
        with patch.dict(os.environ, {"WESTOCK_DATA_SCRIPT": "/tmp/westock.js"}):
            cmd = westock_wrapper.build_westock_command("NVDA", "day", 10)
        self.assertEqual(cmd[1], "/tmp/westock.js")
        self.assertEqual(cmd[-3:], ["usNVDA", "day", "10"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_westock_wrapper -v`

Expected: FAIL because `build_westock_command` does not exist yet.

- [ ] **Step 3: Implement `build_westock_command` and use it in `fetch_kline`**

Keep current default path as fallback for compatibility, but allow `WESTOCK_DATA_SCRIPT`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_westock_wrapper -v`

Expected: PASS.

## Task 5: Full Verification

**Files:**
- All above.

- [ ] **Step 1: Run all unit tests**

Run: `python3 -m unittest discover -v`

Expected: PASS.

- [ ] **Step 2: Run CLI JSON smoke test**

Run: `python3 stock_advisor.py NVDA --cache-dir tests/fixtures/wss --json`

Expected: JSON containing `ticker`, `overall_action`, `confidence`, `short_term_action`, `medium_term_action`, `long_term_action`, `evidence`, and `warnings`.

- [ ] **Step 3: Run CLI text smoke test**

Run: `python3 stock_advisor.py NVDA --cache-dir tests/fixtures/wss`

Expected: Chinese report with action, confidence, short/medium/long actions, invalidation, evidence, warnings, and disclaimer.

- [ ] **Step 4: Check git status**

Run: `git status --short`

Expected: only intentional files changed.
