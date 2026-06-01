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
