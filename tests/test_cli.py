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
        self.assertIn("short_term_action", payload)
        self.assertIn("warnings", payload)

    def test_refresh_is_explicitly_not_implemented(self):
        proc = subprocess.run(
            [sys.executable, "stock_advisor.py", "NVDA", "--refresh-wss-cache"],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("refresh_not_implemented", proc.stderr)
