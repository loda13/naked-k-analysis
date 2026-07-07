import json
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

import naked_k_audit


class NakedKAuditTests(unittest.TestCase):
    def test_builds_structured_audit_event(self):
        event = naked_k_audit.build_audit_event(
            "plan_generated",
            {"ticker": "0700.HK", "action": "小仓试错"},
            run_id="run-1",
            level="warning",
            timestamp="2026-07-07T16:00:00+08:00",
        )

        self.assertEqual(event["event_type"], "plan_generated")
        self.assertEqual(event["level"], "warning")
        self.assertEqual(event["run_id"], "run-1")
        self.assertEqual(event["timestamp"], "2026-07-07T16:00:00+08:00")
        self.assertEqual(event["payload"]["ticker"], "0700.HK")
        self.assertEqual(event["payload"]["action"], "小仓试错")

    def test_audit_logger_writes_jsonl_events(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.jsonl"
            logger = naked_k_audit.AuditLogger(path, run_id="run-2")

            logger.info("run_started", ticker_count=2)
            logger.warning("portfolio_exposure", status="over_limit")

            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual([row["event_type"] for row in rows], ["run_started", "portfolio_exposure"])
        self.assertEqual([row["level"] for row in rows], ["info", "warning"])
        self.assertEqual(rows[0]["payload"]["ticker_count"], 2)
        self.assertEqual(rows[1]["payload"]["status"], "over_limit")
        self.assertEqual(rows[0]["run_id"], "run-2")

    def test_audit_logger_is_noop_without_path(self):
        logger = naked_k_audit.AuditLogger(None, run_id="run-3")

        event = logger.info("run_started")

        self.assertEqual(event["event_type"], "run_started")
        self.assertEqual(event["run_id"], "run-3")


if __name__ == "__main__":
    unittest.main()
