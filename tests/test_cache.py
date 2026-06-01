import unittest
import tempfile
import json
from datetime import date
from pathlib import Path

from stock_analysis.cache import load_wss_context


class CacheTests(unittest.TestCase):
    def test_loads_sanitized_fixture_context(self):
        ctx = load_wss_context("tests/fixtures/wss")

        self.assertEqual(ctx.research.tickers["NVDA"].score, 74)
        self.assertEqual(ctx.research.tickers["NVDA"].moat, "CUDA生态和开发者锁定")
        self.assertEqual(ctx.research.tickers["NVDA"].industry_position, "AI加速卡龙头")
        self.assertEqual(ctx.market.market_state, "警戒观察")
        self.assertEqual(ctx.earnings.events["NVDA"].timing, "盘后")

    def test_runtime_cache_paths_are_gitignored(self):
        with open(".gitignore", "r", encoding="utf-8") as fh:
            text = fh.read()

        self.assertIn("data/cache/", text)
        self.assertIn(".wss-session/", text)

    def test_stale_cache_files_add_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            (cache_dir / "research.json").write_text(
                json.dumps({"as_of": "2026-05-01", "tickers": {}, "avoid": []}),
                encoding="utf-8",
            )
            (cache_dir / "market_risk.json").write_text(
                json.dumps({"as_of": "2026-05-01", "market_state": "趋势仍强", "rules": []}),
                encoding="utf-8",
            )
            (cache_dir / "earnings.json").write_text(
                json.dumps({"as_of": "2026-05-01", "events": {}}),
                encoding="utf-8",
            )

            ctx = load_wss_context(str(cache_dir), today=date(2026, 6, 1))

        self.assertIn("WSS研究缓存已过期", " ".join(ctx.warnings))
        self.assertIn("WSS市场风险缓存已过期", " ".join(ctx.warnings))
