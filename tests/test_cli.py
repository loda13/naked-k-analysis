import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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
        self.assertIn("refresh_source_required", proc.stderr)

    def test_refresh_from_html_dir_writes_cache_without_running_analysis(self):
        html = """
        <html><body><table>
        <tr><th>Ticker</th><th>分数</th><th>证据</th><th>评级</th><th>行业</th></tr>
        <tr><td>NVDA</td><td>74</td><td>B+</td><td>观察名单</td><td>半导体</td></tr>
        </table></body></html>
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html_dir = root / "html"
            cache_dir = root / "cache"
            html_dir.mkdir()
            (html_dir / "research.html").write_text(html, encoding="utf-8")

            proc = subprocess.run(
                [
                    sys.executable,
                    "stock_advisor.py",
                    "NVDA",
                    "--refresh-wss-cache",
                    "--wss-html-dir",
                    str(html_dir),
                    "--cache-dir",
                    str(cache_dir),
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            payload = json.loads(proc.stdout)
            research = json.loads((cache_dir / "research.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["research_count"], 1)
        self.assertEqual(research["tickers"]["NVDA"]["rating"], "观察名单")
