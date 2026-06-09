import json
import subprocess
import sys
import unittest


class CliTests(unittest.TestCase):
    def test_json_cli_outputs_advice(self):
        proc = subprocess.run(
            [sys.executable, "stock_advisor.py", "NVDA", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )

        payload = json.loads(proc.stdout)

        self.assertEqual(payload["ticker"], "NVDA")
        self.assertIn(payload["overall_action"], ["买入", "小仓试错", "持有", "观望"])
        self.assertIn("short_term_action", payload)
        self.assertIn("warnings", payload)
        self.assertIn("entry_triggers", payload)
        self.assertIn("blocked_by", payload)
        self.assertIn("data_sources", payload)
        self.assertIn("technical", payload["data_sources"])
        self.assertNotIn("naked_k", payload["data_sources"])
        self.assertEqual(set(payload["evidence"]), {"technical"})
        self.assertNotIn("risk_reward", payload)

    def test_removed_refresh_flags_are_rejected(self):
        proc = subprocess.run(
            [sys.executable, "stock_advisor.py", "NVDA", "--cache-dir", "tests/fixtures/cache"],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("unrecognized arguments", proc.stderr)
