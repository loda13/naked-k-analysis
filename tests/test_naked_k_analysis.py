import unittest
import copy
import io
import inspect
from contextlib import redirect_stdout
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo
import json
import sys

import pandas as pd

import naked_k_config
import naked_k_llm
import naked_k_analysis
import naked_k_news
import naked_k_news_llm


class NakedKAnalysisTests(unittest.TestCase):
    def _integration_frame(self):
        frame = pd.DataFrame(
            {
                "Open": [96.0, 98.0, 100.0],
                "High": [104.0, 108.0, 110.0],
                "Low": [92.0, 94.0, 90.0],
                "Close": [100.0, 102.0, 106.0],
                "Volume": [1000.0, 1100.0, 1200.0],
            },
            index=pd.date_range("2026-07-17", periods=3, freq="D"),
        )
        frame.attrs["source"] = "fixture"
        return frame

    def _integration_report(self, ticker="TEST", action="观望"):
        return naked_k_analysis.InstrumentReport(
            name=f"公司-{ticker}",
            ticker=ticker,
            action=action,
            entry_trigger=120.0,
            stop_loss=80.0,
            target_price=None,
            risk_per_share=40.0,
            reward_to_risk=None,
            signal_state="watching",
            resistance=150.0,
            support=70.0,
            position_size="0%-10%",
            rationale="原始技术结论",
            daily_patterns=[],
            weekly_patterns=[],
            weekly_context="周线中性",
            data_sources={"daily": "fixture", "weekly": "fixture", "monthly": "fixture"},
            latest_k_dates={"daily": "2026-07-19", "weekly": "2026-07-19", "monthly": "2026-06-30"},
            latest_closes={"daily": 106.0, "weekly": 106.0, "monthly": 101.0},
            review={"status": "观察中", "error_type": None, "note": "测试"},
            improvement="等待确认",
            intraday_status={"status": "盘中观察", "note": "测试"},
            risk_plan={
                "status": "flat",
                "direction": "none",
                "suggested_gross_pct": 0.0,
                "effective_account_risk_pct": 0.0,
                "current_drawdown_pct": 0.0,
                "consecutive_losses": 0,
                "guardrails": [],
            },
            ai_assistant={"status": "ok"},
        )

    def _fake_load_ohlcv(self, _ticker, interval, period):
        del period
        frame = self._integration_frame().copy()
        frame.attrs["source"] = f"fixture-{interval}"
        return frame

    def _news_config(self, model="model-a"):
        return naked_k_news_llm.AnthropicNewsConfig(
            enabled=True,
            base_url="https://gateway.example/anthropic",
            auth_token="fake-news-secret",
            model=model,
        )

    def _news_collection(self, ticker="TEST"):
        return {
            "status": "ok",
            "name": f"公司-{ticker}",
            "ticker": ticker,
            "as_of": "2026-07-20T12:00:00+08:00",
            "window_days": 7,
            "freshness": "primary",
            "items": [
                {
                    "id": "news-01",
                    "title": "新增订单\n落地",
                    "publisher": "测试媒体",
                    "published_at": "2026-07-19T03:00:00+00:00",
                    "url": "https://news.example/item-1",
                    "summary": "订单已公开披露",
                    "source_provider": "yahoo",
                    "freshness": "primary",
                }
            ],
            "source_errors": [],
        }

    def _round1(self, **overrides):
        payload = {
            "status": "ok",
            "direction": "strong_bullish",
            "score": 2,
            "confidence": 86,
            "materiality": "high",
            "horizon": "short_term",
            "summary": "消息面偏积极",
            "positive_factors": ["新增订单"],
            "negative_factors": ["兑现仍有不确定性"],
            "evidence_ids": ["news-01"],
            "uncertainties": ["合同执行进度未知"],
            "data_quality": "sufficient",
        }
        payload.update(overrides)
        return payload

    def _round2(self, technical_action="观望", model_action="买入", **overrides):
        payload = {
            "status": "ok",
            "technical_view": {"action": technical_action, "summary": "技术面等待突破"},
            "news_view": {"direction": "strong_bullish", "summary": "消息面形成催化"},
            "conflict_analysis": "消息催化与技术等待存在冲突",
            "model_action": model_action,
            "confidence": 78,
            "decision_reasons": ["消息具有较高重要性"],
            "risk_flags": ["兑现仍待验证"],
            "evidence_ids": ["news-01"],
            "execution_note": "由裸K规则生成执行价格",
        }
        payload.update(overrides)
        return payload

    def _anthropic_response(self, model_payload):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(model_payload, ensure_ascii=False),
                        }
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                    "stop_reason": "end_turn",
                }

        return FakeResponse()

    def _sequential_news_post(self, responses):
        remaining = list(responses)

        def post(_url, headers, timeout, **_kwargs):
            del headers, timeout
            response = remaining.pop(0)
            if isinstance(response, Exception):
                raise response
            return self._anthropic_response(response)

        return post

    def _invoke_main(
        self,
        argv,
        *,
        news_config=None,
        load_news_error=None,
        resolve_error=None,
        run_result=("report", []),
        run_side_effect=None,
    ):
        output = io.StringIO()
        active_news_config = news_config or self._news_config()
        with (
            patch.object(sys, "argv", ["naked_k_analysis.py", *argv]),
            patch.object(
                naked_k_analysis.naked_k_config,
                "load_trading_config",
                return_value=naked_k_config.TradingConfig(),
            ),
            patch.object(
                naked_k_analysis.naked_k_llm,
                "load_llm_config",
                return_value=naked_k_llm.LLMConfig(),
            ),
            patch.object(
                naked_k_news_llm,
                "load_news_config",
                return_value=active_news_config,
                side_effect=load_news_error,
            ) as load_news,
            patch.object(
                naked_k_news_llm,
                "resolve_news_model",
                return_value=active_news_config,
                side_effect=resolve_error,
            ),
            patch.object(naked_k_news_llm, "validate_news_config"),
            patch.object(
                naked_k_analysis,
                "run_analysis",
                return_value=run_result,
                side_effect=run_side_effect,
            ) as run,
            redirect_stdout(output),
        ):
            exit_code = naked_k_analysis.main()
        return exit_code, output.getvalue(), run, load_news

    def test_news_cli_defaults_are_disabled_and_have_no_token_argument(self):
        with patch.object(sys, "argv", ["naked_k_analysis.py"]):
            args = naked_k_analysis.parse_args()

        self.assertFalse(getattr(args, "news", None))
        self.assertEqual(getattr(args, "news_model", None), "")
        self.assertEqual(getattr(args, "news_lookback_days", None), 7)
        self.assertEqual(getattr(args, "news_max_items", None), 12)
        self.assertFalse(any("token" in name for name in vars(args)))

    def test_news_cli_accepts_explicit_model_and_collection_limits(self):
        with patch.object(
            sys,
            "argv",
            [
                "naked_k_analysis.py",
                "--news",
                "--news-model",
                "model-a",
                "--news-lookback-days",
                "5",
                "--news-max-items",
                "8",
            ],
        ):
            try:
                args = naked_k_analysis.parse_args()
            except SystemExit:
                self.fail("news CLI flags must be accepted")

        self.assertTrue(getattr(args, "news", None))
        self.assertEqual(getattr(args, "news_model", None), "model-a")
        self.assertEqual(getattr(args, "news_lookback_days", None), 5)
        self.assertEqual(getattr(args, "news_max_items", None), 8)
        self.assertFalse(any("token" in name for name in vars(args)))

    def test_news_disabled_preserves_legacy_report_journal_and_serialized_shape(self):
        technical = self._integration_report()
        expected_fields = {
            "action": technical.action,
            "entry_trigger": technical.entry_trigger,
            "stop_loss": technical.stop_loss,
            "target_price": technical.target_price,
        }
        with TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            with (
                patch.object(naked_k_analysis, "load_ohlcv", side_effect=self._fake_load_ohlcv),
                patch.object(naked_k_analysis, "build_trade_plan", return_value=technical),
                patch.object(naked_k_news, "collect_news", side_effect=AssertionError("news collection called")) as collect,
                patch.object(
                    naked_k_news_llm,
                    "run_two_pass_deliberation",
                    side_effect=AssertionError("news model called"),
                ) as deliberate,
            ):
                markdown, reports = naked_k_analysis.run_analysis(
                    [("测试", "TEST")],
                    journal_path,
                )

            journal_row = naked_k_analysis.load_journal(journal_path)[0]

        self.assertEqual(collect.call_count, 0)
        self.assertEqual(deliberate.call_count, 0)
        self.assertNotIn("### 技术面结论", markdown)
        self.assertNotIn("### 消息面结论", markdown)
        self.assertEqual(
            {field: getattr(reports[0], field) for field in expected_fields},
            expected_fields,
        )
        self.assertEqual(reports[0].technical_conclusion, {})
        self.assertEqual(reports[0].news_analysis, {})
        self.assertEqual(reports[0].combined_conclusion, {})
        self.assertNotIn("technical_conclusion", journal_row)
        self.assertNotIn("news_analysis", journal_row)
        self.assertNotIn("combined_conclusion", journal_row)
        self.assertTrue(hasattr(naked_k_analysis, "serialize_report"))
        serialized = naked_k_analysis.serialize_report(reports[0])
        self.assertNotIn("technical_conclusion", serialized)
        self.assertNotIn("news_analysis", serialized)
        self.assertNotIn("combined_conclusion", serialized)
        json.dumps(serialized, ensure_ascii=False)

    def test_news_disabled_journals_first_ticker_before_second_required_load_fails(self):
        calls = []

        def load(ticker, interval, period):
            calls.append((ticker, interval, period))
            if ticker == "FAIL" and interval == "1d":
                raise RuntimeError("required load failed")
            return self._fake_load_ohlcv(ticker, interval, period)

        def build(name, ticker, *_args, **_kwargs):
            return self._integration_report(ticker=ticker)

        with TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            with (
                patch.object(naked_k_analysis, "load_ohlcv", side_effect=load),
                patch.object(naked_k_analysis, "build_trade_plan", side_effect=build),
            ):
                with self.assertRaisesRegex(RuntimeError, "required load failed"):
                    naked_k_analysis.run_analysis(
                        [("成功", "OK"), ("失败", "FAIL")],
                        journal_path,
                    )

            rows = naked_k_analysis.load_journal(journal_path)

        self.assertEqual([row["ticker"] for row in rows], ["OK"])
        self.assertIn(("FAIL", "1d", "18mo"), calls)

    def test_news_pipeline_snapshots_then_deliberates_and_keeps_legacy_llm_separate(self):
        self.assertIn("news_config", inspect.signature(naked_k_analysis.run_analysis).parameters)
        technical = self._integration_report()
        request_bodies = []

        def news_post(url, headers, json, timeout):
            del url, headers, timeout
            request_bodies.append(copy.deepcopy(json))
            self.assertTrue(technical.technical_conclusion)
            payload = self._round1() if len(request_bodies) == 1 else self._round2()
            return self._anthropic_response(payload)

        class LegacyResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": '{"market_reading":"独立复盘","journal_note":"等待确认"}'
                            }
                        }
                    ]
                }

        legacy_config = naked_k_llm.LLMConfig(
            enabled=True,
            base_url="https://legacy.example/v1",
            api_key="fake-legacy-secret",
            model="legacy-model",
        )
        with TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            with (
                patch.object(naked_k_analysis, "load_ohlcv", side_effect=self._fake_load_ohlcv),
                patch.object(naked_k_analysis, "build_trade_plan", return_value=technical),
                patch.object(naked_k_news, "collect_news", return_value=self._news_collection()),
            ):
                markdown, reports = naked_k_analysis.run_analysis(
                    [("测试", "TEST")],
                    journal_path,
                    llm_config=legacy_config,
                    llm_post=lambda *_args, **_kwargs: LegacyResponse(),
                    news_config=self._news_config(),
                    news_post=news_post,
                    news_lookback_days=7,
                    news_max_items=12,
                )
            journal_row = naked_k_analysis.load_journal(journal_path)[0]

        report = reports[0]
        self.assertEqual(len(request_bodies), 2)
        round1_input = json.loads(request_bodies[0]["messages"][0]["content"])
        round2_input = json.loads(request_bodies[1]["messages"][0]["content"])
        self.assertNotIn("technical_snapshot", round1_input)
        self.assertEqual(round2_input["technical_snapshot"], report.technical_conclusion)
        self.assertIsNot(report.technical_conclusion, report.news_analysis)
        self.assertIsNot(report.news_analysis, report.combined_conclusion)
        self.assertEqual(report.action, "买入")
        self.assertEqual(report.action, report.combined_conclusion["final_action"])
        self.assertEqual(report.combined_conclusion["model_action"], "买入")
        self.assertNotEqual(report.entry_trigger, report.technical_conclusion["entry_trigger"])
        self.assertNotEqual(report.stop_loss, report.technical_conclusion["stop_loss"])
        self.assertEqual(report.combined_conclusion["price_plan_source"], "deterministic_naked_k")
        self.assertEqual(
            report.ai_assistant["llm_commentary"]["parsed"]["market_reading"],
            "独立复盘",
        )
        self.assertEqual(journal_row["action"], report.action)
        self.assertEqual(journal_row["technical_conclusion"], report.technical_conclusion)
        self.assertEqual(journal_row["news_analysis"], report.news_analysis)
        self.assertEqual(journal_row["combined_conclusion"], report.combined_conclusion)
        json.dumps(asdict(report), ensure_ascii=False)
        self.assertIn("### 技术面结论", markdown)

    def test_news_failure_is_isolated_per_ticker(self):
        def build(name, ticker, *_args, **_kwargs):
            report = self._integration_report(ticker=ticker)
            report.name = name
            return report

        def news_post(_url, headers, timeout, **kwargs):
            del headers, timeout
            user_payload = json.loads(kwargs["json"]["messages"][0]["content"])
            if user_payload.get("company", {}).get("ticker") == "FAIL":
                raise RuntimeError("source failed fake-news-secret")
            if "company" in user_payload:
                return self._anthropic_response(self._round1())
            return self._anthropic_response(self._round2())

        def collect(name, ticker, **_kwargs):
            collection = self._news_collection(ticker)
            collection["name"] = name
            return collection

        with TemporaryDirectory() as tmpdir:
            with (
                patch.object(naked_k_analysis, "load_ohlcv", side_effect=self._fake_load_ohlcv),
                patch.object(naked_k_analysis, "build_trade_plan", side_effect=build),
                patch.object(naked_k_news, "collect_news", side_effect=collect),
            ):
                _, reports = naked_k_analysis.run_analysis(
                    [("失败公司", "FAIL"), ("成功公司", "PASS")],
                    Path(tmpdir) / "journal.jsonl",
                    news_config=self._news_config(),
                    news_post=news_post,
                )

        by_ticker = {report.ticker: report for report in reports}
        self.assertEqual(set(by_ticker), {"FAIL", "PASS"})
        self.assertEqual(by_ticker["FAIL"].action, "观望")
        self.assertEqual(by_ticker["FAIL"].technical_conclusion["action"], "观望")
        self.assertEqual(by_ticker["FAIL"].combined_conclusion["status"], "technical_fallback")
        self.assertEqual(by_ticker["PASS"].action, "买入")
        self.assertEqual(by_ticker["PASS"].combined_conclusion["final_action"], "买入")

    def test_news_two_pass_failures_always_keep_the_technical_plan(self):
        scenarios = {
            "round one request": [RuntimeError("request failed")],
            "round one insufficient": [self._round1(data_quality="insufficient", evidence_ids=[])],
            "round two request": [self._round1(), RuntimeError("round two failed")],
            "invalid evidence": [self._round1(evidence_ids=["news-99"])],
            "anti tamper": [self._round1(), self._round2(entry_trigger=999.0)],
        }
        for label, responses in scenarios.items():
            with self.subTest(label=label), TemporaryDirectory() as tmpdir:
                news_post = self._sequential_news_post(responses)

                technical = self._integration_report()
                with (
                    patch.object(naked_k_analysis, "load_ohlcv", side_effect=self._fake_load_ohlcv),
                    patch.object(naked_k_analysis, "build_trade_plan", return_value=technical),
                    patch.object(naked_k_news, "collect_news", return_value=self._news_collection()),
                ):
                    _, reports = naked_k_analysis.run_analysis(
                        [("测试", "TEST")],
                        Path(tmpdir) / "journal.jsonl",
                        news_config=self._news_config(),
                        news_post=news_post,
                    )

                report = reports[0]
                self.assertEqual(report.action, "观望")
                self.assertEqual(report.entry_trigger, 120.0)
                self.assertEqual(report.stop_loss, 80.0)
                self.assertEqual(report.technical_conclusion["action"], "观望")
                self.assertEqual(report.combined_conclusion["final_action"], "观望")
                self.assertEqual(report.combined_conclusion["status"], "technical_fallback")

    def test_synthesis_exception_preserves_valid_model_action_but_restores_execution(self):
        news_post = self._sequential_news_post([self._round1(), self._round2()])

        def explode_after_mutation(report, *_args, **_kwargs):
            report.action = "买入"
            report.entry_trigger = 999.0
            raise RuntimeError("FULL_PROMPT_SENTINEL fake-news-secret")

        with TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            audit_path = Path(tmpdir) / "audit.jsonl"
            with (
                patch.object(naked_k_analysis, "load_ohlcv", side_effect=self._fake_load_ohlcv),
                patch.object(naked_k_analysis, "build_trade_plan", return_value=self._integration_report()),
                patch.object(naked_k_news, "collect_news", return_value=self._news_collection()),
                patch.object(naked_k_analysis.naked_k_synthesis, "apply_deliberation", side_effect=explode_after_mutation),
            ):
                _, reports = naked_k_analysis.run_analysis(
                    [("测试", "TEST")],
                    journal_path,
                    audit_path=audit_path,
                    news_config=self._news_config(),
                    news_post=news_post,
                )
            audit_text = audit_path.read_text(encoding="utf-8")
            journal_text = journal_path.read_text(encoding="utf-8")

        report = reports[0]
        self.assertEqual(report.action, "观望")
        self.assertEqual(report.entry_trigger, 120.0)
        self.assertEqual(report.combined_conclusion["model_action"], "买入")
        self.assertEqual(report.combined_conclusion["final_action"], "观望")
        self.assertEqual(report.combined_conclusion["decision_reasons"], ["消息具有较高重要性"])
        self.assertIn("RuntimeError", report.combined_conclusion["risk_override_reason"])
        self.assertNotIn("FULL_PROMPT_SENTINEL", audit_text + journal_text)
        self.assertNotIn("fake-news-secret", audit_text + journal_text)

    def test_portfolio_guard_exception_rolls_back_every_report_before_persistence(self):
        def build(name, ticker, *_args, **_kwargs):
            report = self._integration_report(ticker=ticker)
            report.name = name
            return report

        def collect(name, ticker, **_kwargs):
            collection = self._news_collection(ticker)
            collection["name"] = name
            return collection

        def news_post(_url, headers, timeout, **kwargs):
            del headers, timeout
            user_payload = json.loads(kwargs["json"]["messages"][0]["content"])
            return self._anthropic_response(
                self._round1() if "company" in user_payload else self._round2()
            )

        class GuardExplosion(RuntimeError):
            pass

        def mutate_then_raise(reports, *_args, **_kwargs):
            reports[0].action = "观望"
            reports[0].entry_trigger = 777.0
            reports[0].combined_conclusion["final_action"] = "观望"
            raise GuardExplosion("FULL_PROMPT_SENTINEL fake-news-secret")

        with TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            audit_path = Path(tmpdir) / "audit.jsonl"
            with (
                patch.object(naked_k_analysis, "load_ohlcv", side_effect=self._fake_load_ohlcv),
                patch.object(naked_k_analysis, "build_trade_plan", side_effect=build),
                patch.object(naked_k_news, "collect_news", side_effect=collect),
                patch.object(
                    naked_k_analysis.naked_k_synthesis,
                    "apply_portfolio_guardrails",
                    side_effect=mutate_then_raise,
                ),
            ):
                markdown, reports = naked_k_analysis.run_analysis(
                    [("甲", "AAA"), ("乙", "BBB")],
                    journal_path,
                    audit_path=audit_path,
                    news_config=self._news_config(),
                    news_post=news_post,
                )
            rows = naked_k_analysis.load_journal(journal_path)
            events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual([report.action for report in reports], ["买入", "买入"])
        self.assertEqual([report.combined_conclusion["final_action"] for report in reports], ["买入", "买入"])
        self.assertEqual([row["action"] for row in rows], ["买入", "买入"])
        self.assertIn("- 当前动作：买入", markdown)
        warning = next(event for event in events if event["event_type"] == "portfolio_guard_failed")
        self.assertEqual(warning["level"], "warning")
        self.assertEqual(warning["payload"], {"error_type": "GuardExplosion"})

    def test_risk_context_exception_is_isolated_inside_the_news_branch(self):
        original_build_risk_context = naked_k_analysis.naked_k_synthesis.build_risk_context
        risk_calls = 0

        def build_risk_context(snapshot, config):
            nonlocal risk_calls
            risk_calls += 1
            if risk_calls == 1:
                raise RuntimeError("FULL_PROMPT_SENTINEL fake-news-secret")
            return original_build_risk_context(snapshot, config)

        def build(name, ticker, *_args, **_kwargs):
            report = self._integration_report(ticker=ticker)
            report.name = name
            return report

        def collect(name, ticker, **_kwargs):
            collection = self._news_collection(ticker)
            collection["name"] = name
            return collection

        def news_post(_url, headers, timeout, **kwargs):
            del headers, timeout
            user_payload = json.loads(kwargs["json"]["messages"][0]["content"])
            return self._anthropic_response(
                self._round1() if "company" in user_payload else self._round2()
            )

        with TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            audit_path = Path(tmpdir) / "audit.jsonl"
            with (
                patch.object(naked_k_analysis, "load_ohlcv", side_effect=self._fake_load_ohlcv),
                patch.object(naked_k_analysis, "build_trade_plan", side_effect=build),
                patch.object(naked_k_news, "collect_news", side_effect=collect),
                patch.object(
                    naked_k_analysis.naked_k_synthesis,
                    "build_risk_context",
                    side_effect=build_risk_context,
                ),
            ):
                _, reports = naked_k_analysis.run_analysis(
                    [("甲", "AAA"), ("乙", "BBB")],
                    journal_path,
                    audit_path=audit_path,
                    news_config=self._news_config(),
                    news_post=news_post,
                )
            persisted = journal_path.read_text(encoding="utf-8") + audit_path.read_text(encoding="utf-8")

        self.assertEqual([report.ticker for report in reports], ["AAA", "BBB"])
        self.assertEqual(reports[0].action, "观望")
        self.assertEqual(reports[0].combined_conclusion["status"], "technical_fallback")
        self.assertEqual(reports[1].action, "买入")
        self.assertNotIn("FULL_PROMPT_SENTINEL", persisted)
        self.assertNotIn("fake-news-secret", persisted)

    def test_outer_news_boundary_recovers_when_snapshot_helper_raises(self):
        original_snapshot = naked_k_analysis.naked_k_synthesis.snapshot_technical_conclusion
        snapshot_calls = 0

        def snapshot(report):
            nonlocal snapshot_calls
            snapshot_calls += 1
            if snapshot_calls == 1:
                raise RuntimeError("FULL_PROMPT_SENTINEL fake-news-secret")
            return original_snapshot(report)

        def build(name, ticker, *_args, **_kwargs):
            report = self._integration_report(ticker=ticker)
            report.name = name
            return report

        with TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            audit_path = Path(tmpdir) / "audit.jsonl"
            with (
                patch.object(naked_k_analysis, "load_ohlcv", side_effect=self._fake_load_ohlcv),
                patch.object(naked_k_analysis, "build_trade_plan", side_effect=build),
                patch.object(naked_k_news, "collect_news", return_value=self._news_collection()),
                patch.object(
                    naked_k_analysis.naked_k_synthesis,
                    "snapshot_technical_conclusion",
                    side_effect=snapshot,
                ),
            ):
                _, reports = naked_k_analysis.run_analysis(
                    [("失败快照", "FAIL"), ("成功快照", "PASS")],
                    journal_path,
                    audit_path=audit_path,
                    news_config=self._news_config(),
                    news_post=self._sequential_news_post([self._round1(), self._round2()]),
                )
            persisted = (
                journal_path.read_text(encoding="utf-8")
                + audit_path.read_text(encoding="utf-8")
            )

        self.assertEqual([report.ticker for report in reports], ["FAIL", "PASS"])
        self.assertEqual(reports[0].action, "观望")
        self.assertEqual(reports[0].technical_conclusion["action"], "观望")
        self.assertEqual(reports[0].combined_conclusion["status"], "technical_fallback")
        self.assertEqual(reports[1].action, "买入")
        self.assertNotIn("FULL_PROMPT_SENTINEL", persisted)
        self.assertNotIn("fake-news-secret", persisted)

    def test_synthesis_internal_fallback_sanitizes_raw_exception_before_journaling(self):
        news_post = self._sequential_news_post([self._round1(), self._round2()])

        with TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            with (
                patch.object(naked_k_analysis, "load_ohlcv", side_effect=self._fake_load_ohlcv),
                patch.object(naked_k_analysis, "build_trade_plan", return_value=self._integration_report()),
                patch.object(naked_k_news, "collect_news", return_value=self._news_collection()),
                patch.object(
                    naked_k_analysis.naked_k_synthesis,
                    "_synchronized_candidate",
                    side_effect=RuntimeError("FULL_PROMPT_SENTINEL fake-news-secret"),
                ),
            ):
                _, reports = naked_k_analysis.run_analysis(
                    [("测试", "TEST")],
                    journal_path,
                    news_config=self._news_config(),
                    news_post=news_post,
                )
            journal_text = journal_path.read_text(encoding="utf-8")

        combined = reports[0].combined_conclusion
        self.assertEqual(combined["model_action"], "买入")
        self.assertEqual(combined["final_action"], "观望")
        self.assertIn("RuntimeError", combined["risk_override_reason"])
        self.assertNotIn("FULL_PROMPT_SENTINEL", journal_text)
        self.assertNotIn("fake-news-secret", journal_text)

    def test_main_ambiguous_news_model_prints_only_ids_and_returns_two(self):
        with TemporaryDirectory() as tmpdir:
            exit_code, output, run, _ = self._invoke_main(
                ["--news", "--report-path", str(Path(tmpdir) / "report.md")],
                news_config=self._news_config(model=""),
                resolve_error=naked_k_news_llm.NewsModelSelectionRequired(
                    ("model-z", "model-a")
                ),
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(output, "model-a\nmodel-z\n")
        run.assert_not_called()

    def test_main_sanitizes_news_bootstrap_failures_and_still_runs_technical_reports(self):
        failures = [
            ValueError("missing token fake-news-secret"),
            naked_k_news_llm.NewsModelDiscoveryError("network fake-news-secret"),
            naked_k_news_llm.NewsModelDiscoveryError("HTTP fake-news-secret"),
            naked_k_news_llm.NewsModelDiscoveryError("JSON fake-news-secret"),
            naked_k_news_llm.NewsModelDiscoveryError("empty fake-news-secret"),
            RuntimeError("unexpected fake-news-secret"),
        ]
        for failure in failures:
            with self.subTest(error=type(failure).__name__), TemporaryDirectory() as tmpdir:
                captured = {}

                def run_analysis(*_args, **kwargs):
                    captured.update(kwargs)
                    return "technical fallback report", []

                config = self._news_config(model="")
                exit_code, output, _, _ = self._invoke_main(
                    [
                        "--news",
                        "--report-path",
                        str(Path(tmpdir) / "report.md"),
                        "--journal-path",
                        str(Path(tmpdir) / "journal.jsonl"),
                        "--audit-path",
                        str(Path(tmpdir) / "audit.jsonl"),
                    ],
                    news_config=config,
                    resolve_error=failure,
                    run_side_effect=run_analysis,
                )

                self.assertEqual(exit_code, 0)
                self.assertEqual(
                    captured["news_bootstrap_error"],
                    {
                        "error_type": type(failure).__name__,
                        "message": "News configuration or model discovery failed",
                    },
                )
                self.assertIs(captured["news_config"], config)
                self.assertNotIn("fake-news-secret", output)

    def test_main_rejects_nonpositive_news_limits_before_running(self):
        for flag in ("--news-lookback-days", "--news-max-items"):
            with self.subTest(flag=flag), TemporaryDirectory() as tmpdir:
                exit_code, output, run, _ = self._invoke_main(
                    [
                        "--news",
                        flag,
                        "0",
                        "--report-path",
                        str(Path(tmpdir) / "report.md"),
                    ]
                )

                self.assertEqual(exit_code, 2)
                run.assert_not_called()
                self.assertIn("positive", output)

    def test_main_news_json_uses_redacted_config_and_conditional_report_fields(self):
        report = self._integration_report()
        report.technical_conclusion = {"action": "观望"}
        report.news_analysis = {"status": "unavailable"}
        report.combined_conclusion = {"model_action": "观望", "final_action": "观望"}
        config = self._news_config(model="model-a")

        with TemporaryDirectory() as tmpdir:
            exit_code, output, run, load_news = self._invoke_main(
                [
                    "--news",
                    "--news-model",
                    "model-a",
                    "--json",
                    "--report-path",
                    str(Path(tmpdir) / "report.md"),
                    "--journal-path",
                    str(Path(tmpdir) / "journal.jsonl"),
                    "--audit-path",
                    "",
                ],
                news_config=config,
                run_result=("report", [report]),
            )
            payload = json.loads(output)

        self.assertEqual(exit_code, 0)
        load_news.assert_called_once_with(enabled=True, model="model-a")
        self.assertEqual(payload["news"]["auth_token"], "***")
        self.assertNotIn("fake-news-secret", output)
        self.assertEqual(payload["items"][0]["technical_conclusion"], {"action": "观望"})
        self.assertIn("news_analysis", payload["items"][0])
        self.assertIn("combined_conclusion", payload["items"][0])
        self.assertEqual(run.call_args.kwargs["news_lookback_days"], 7)
        self.assertEqual(run.call_args.kwargs["news_max_items"], 12)

    def test_news_audit_has_four_ordered_metadata_only_events(self):
        news_post = self._sequential_news_post(
            [
                self._round1(raw_prompt="FULL_PROMPT_SENTINEL"),
                self._round2(raw_content="FULL_PROMPT_SENTINEL"),
            ]
        )

        with TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            audit_path = Path(tmpdir) / "audit.jsonl"
            with (
                patch.object(naked_k_analysis, "load_ohlcv", side_effect=self._fake_load_ohlcv),
                patch.object(naked_k_analysis, "build_trade_plan", return_value=self._integration_report()),
                patch.object(naked_k_news, "collect_news", return_value=self._news_collection()),
            ):
                naked_k_analysis.run_analysis(
                    [("测试", "TEST")],
                    journal_path,
                    audit_path=audit_path,
                    news_config=self._news_config(),
                    news_post=news_post,
                )

            audit_text = audit_path.read_text(encoding="utf-8")
            journal_text = journal_path.read_text(encoding="utf-8")
            events = [json.loads(line) for line in audit_text.splitlines()]

        news_events = [
            event
            for event in events
            if event["event_type"]
            in {"news_collected", "news_assessed", "decision_deliberated", "signal_synthesized"}
        ]
        self.assertEqual(
            [event["event_type"] for event in news_events],
            ["news_collected", "news_assessed", "decision_deliberated", "signal_synthesized"],
        )
        allowed = {
            "ticker",
            "name",
            "provider",
            "model",
            "status",
            "item_count",
            "model_action",
            "final_action",
            "error_type",
            "override_reason",
        }
        for event in news_events:
            self.assertLessEqual(set(event["payload"]), allowed)
        self.assertNotIn("fake-news-secret", audit_text + journal_text)
        self.assertNotIn("FULL_PROMPT_SENTINEL", audit_text + journal_text)
        self.assertNotIn("headers", audit_text)
        self.assertNotIn("input_tokens", audit_text)

    def test_news_journal_is_deferred_until_after_guard_final_action(self):
        news_post = self._sequential_news_post([self._round1(), self._round2()])

        with TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            journal_existed_during_guard = []

            def guard(reports, *_args, **_kwargs):
                journal_existed_during_guard.append(journal_path.exists())
                reports[0].action = "观望"
                reports[0].combined_conclusion["final_action"] = "观望"
                reports[0].combined_conclusion["risk_override_reason"] = "组合风险保护"
                return {"status": "within_limits", "overrides": []}

            with (
                patch.object(naked_k_analysis, "load_ohlcv", side_effect=self._fake_load_ohlcv),
                patch.object(naked_k_analysis, "build_trade_plan", return_value=self._integration_report()),
                patch.object(naked_k_news, "collect_news", return_value=self._news_collection()),
                patch.object(
                    naked_k_analysis.naked_k_synthesis,
                    "apply_portfolio_guardrails",
                    side_effect=guard,
                ),
            ):
                _, reports = naked_k_analysis.run_analysis(
                    [("测试", "TEST")],
                    journal_path,
                    news_config=self._news_config(),
                    news_post=news_post,
                )
            row = naked_k_analysis.load_journal(journal_path)[0]

        self.assertEqual(journal_existed_during_guard, [False])
        self.assertEqual(reports[0].action, "观望")
        self.assertEqual(row["action"], "观望")
        self.assertEqual(row["combined_conclusion"]["final_action"], "观望")

    def test_news_bootstrap_fallback_skips_collection_and_model_but_emits_all_events(self):
        with TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            audit_path = Path(tmpdir) / "audit.jsonl"
            with (
                patch.object(naked_k_analysis, "load_ohlcv", side_effect=self._fake_load_ohlcv),
                patch.object(naked_k_analysis, "build_trade_plan", return_value=self._integration_report()),
                patch.object(naked_k_news, "collect_news", side_effect=AssertionError("collection called")) as collect,
                patch.object(
                    naked_k_news_llm,
                    "run_two_pass_deliberation",
                    side_effect=AssertionError("model called"),
                ) as deliberate,
            ):
                markdown, reports = naked_k_analysis.run_analysis(
                    [("测试", "TEST")],
                    journal_path,
                    audit_path=audit_path,
                    news_config=self._news_config(model=""),
                    news_bootstrap_error={
                        "error_type": "ValueError FULL_PROMPT_SENTINEL fake-news-secret",
                        "message": "FULL_PROMPT_SENTINEL fake-news-secret",
                    },
                )
            persisted = (
                journal_path.read_text(encoding="utf-8")
                + audit_path.read_text(encoding="utf-8")
            )
            events = [
                json.loads(line)
                for line in audit_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(collect.call_count, 0)
        self.assertEqual(deliberate.call_count, 0)
        self.assertEqual(reports[0].action, "观望")
        self.assertEqual(reports[0].news_analysis["status"], "unavailable")
        self.assertEqual(reports[0].combined_conclusion["final_action"], "观望")
        self.assertIn("消息面不可用", markdown)
        self.assertNotIn("FULL_PROMPT_SENTINEL", persisted)
        self.assertNotIn("fake-news-secret", persisted)
        news_events = [event["event_type"] for event in events if event["event_type"].startswith("news_")]
        self.assertEqual(news_events, ["news_collected", "news_assessed"])
        synthesized = [
            event["event_type"]
            for event in events
            if event["event_type"] in {"decision_deliberated", "signal_synthesized"}
        ]
        self.assertEqual(synthesized, ["decision_deliberated", "signal_synthesized"])

    def test_format_report_renders_five_ordered_news_blocks_from_final_action(self):
        report = self._integration_report()
        report.action = "观望"
        report.technical_conclusion = {
            "action": "观望",
            "entry_trigger": 120.0,
            "stop_loss": 80.0,
            "target_price": None,
        }
        report.news_analysis = {
            "status": "ok",
            "collection": self._news_collection(),
            "round1": self._round1(summary="消息面\n偏积极"),
            "provider": "anthropic_compatible",
            "model": "model-a",
        }
        report.news_analysis["collection"]["items"].append(
            {
                "id": "news-02",
                "title": "<script>& trusted](javascript:alert(1)) [click\n### injected",
                "publisher": "trusted [publisher](javascript:alert(1)) <img>",
                "published_at": "<script>2026-07-18</script>",
                "url": "javascript:alert(document.domain)",
                "summary": "不可信元数据",
                "source_provider": "fake",
                "freshness": "primary",
            }
        )
        report.combined_conclusion = {
            **self._round2(conflict_analysis="消息催化\n与技术等待冲突"),
            "final_action": "观望",
            "execution_side": "neutral",
            "risk_override_reason": "组合风险保护",
            "price_plan_source": "deterministic_naked_k",
        }

        markdown = naked_k_analysis.format_report(
            "2026-07-20 16:00:00 CST",
            [report],
            naked_k_analysis.DEFAULT_JOURNAL_PATH,
        )

        headings = [
            "### 技术面结论",
            "### 消息面结论",
            "### 技术与消息冲突/一致性",
            "### 综合结论",
            "### 消息来源",
        ]
        positions = [markdown.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("技术动作：观望", markdown)
        self.assertIn("方向：strong_bullish；评分：2；置信度：86", markdown)
        self.assertIn("证据：news-01", markdown)
        self.assertIn("消息催化 与技术等待冲突", markdown)
        self.assertIn("模型动作：买入", markdown)
        self.assertIn("风险保护后最终动作：观望", markdown)
        self.assertIn("覆盖原因：组合风险保护", markdown)
        self.assertIn("1. [新增订单 落地](https://news.example/item-1) — 测试媒体；2026-07-19", markdown)
        today = markdown.split("## 今日结论", 1)[1]
        self.assertIn("最值得试错：暂无", today)
        self.assertIn("继续观察：公司-TEST", today)
        self.assertNotIn("最值得试错：公司-TEST（买入）", today)
        self.assertNotIn("消息面\n偏积极", markdown)
        self.assertNotIn("消息催化\n与技术等待冲突", markdown)
        self.assertNotIn("](javascript:", markdown)
        self.assertNotIn("[click](", markdown)
        self.assertNotIn("[publisher](", markdown)
        self.assertNotIn("\n### injected", markdown)
        self.assertNotIn("<script>", markdown)
        self.assertNotIn("<img>", markdown)

    def test_main_default_off_does_not_load_news_config_and_keeps_legacy_json_shape(self):
        report = self._integration_report()
        with TemporaryDirectory() as tmpdir:
            exit_code, output, _, load_news = self._invoke_main(
                [
                    "--json",
                    "--report-path",
                    str(Path(tmpdir) / "report.md"),
                    "--journal-path",
                    str(Path(tmpdir) / "journal.jsonl"),
                    "--audit-path",
                    "",
                ],
                load_news_error=AssertionError(
                    "news env must stay untouched when disabled"
                ),
                run_result=("report", [report]),
            )
            payload = json.loads(output)

        self.assertEqual(exit_code, 0)
        load_news.assert_not_called()
        self.assertNotIn("news", payload)
        self.assertNotIn("technical_conclusion", payload["items"][0])
        self.assertNotIn("news_analysis", payload["items"][0])
        self.assertNotIn("combined_conclusion", payload["items"][0])

    def test_main_news_config_loading_error_becomes_sanitized_bootstrap_fallback(self):
        captured = {}

        def run_analysis(*_args, **kwargs):
            captured.update(kwargs)
            return "technical fallback report", []

        with TemporaryDirectory() as tmpdir:
            exit_code, output, _, _ = self._invoke_main(
                [
                    "--news",
                    "--report-path",
                    str(Path(tmpdir) / "report.md"),
                    "--journal-path",
                    str(Path(tmpdir) / "journal.jsonl"),
                    "--audit-path",
                    "",
                ],
                load_news_error=ValueError(
                    "bad env FULL_PROMPT_SENTINEL fake-news-secret"
                ),
                run_side_effect=run_analysis,
            )

        self.assertEqual(exit_code, 0)
        self.assertTrue(captured["news_config"].enabled)
        self.assertEqual(
            captured["news_bootstrap_error"],
            {
                "error_type": "ValueError",
                "message": "News configuration or model discovery failed",
            },
        )
        self.assertNotIn("FULL_PROMPT_SENTINEL", output)
        self.assertNotIn("fake-news-secret", output)

    def test_format_report_labels_insufficient_news_and_does_not_invent_evidence(self):
        report = self._integration_report()
        report.technical_conclusion = {
            "action": "观望",
            "entry_trigger": 120.0,
            "stop_loss": 80.0,
            "target_price": None,
        }
        report.news_analysis = {
            "status": "insufficient",
            "collection": self._news_collection(),
            "round1": self._round1(data_quality="insufficient", evidence_ids=[]),
            "provider": "anthropic_compatible",
            "model": "model-a",
        }
        report.combined_conclusion = {
            "status": "technical_fallback",
            "technical_view": {"action": "观望", "summary": "保留技术结论"},
            "news_view": {"direction": "strong_bullish", "summary": "证据不足"},
            "conflict_analysis": "消息证据不足，沿用技术判断",
            "model_action": "观望",
            "final_action": "观望",
            "confidence": 0,
            "decision_reasons": ["保留技术动作"],
            "risk_flags": [],
            "evidence_ids": [],
            "execution_note": "沿用技术计划",
            "execution_side": "neutral",
            "risk_override_reason": "Round-one news data is insufficient",
            "price_plan_source": "technical_snapshot",
        }

        markdown = naked_k_analysis.format_report(
            "2026-07-20 16:00:00 CST",
            [report],
            naked_k_analysis.DEFAULT_JOURNAL_PATH,
        )

        self.assertIn("消息面不足", markdown)
        self.assertIn("证据：无", markdown)
        self.assertIn("风险保护后最终动作：观望", markdown)
        self.assertNotIn("news-99", markdown)

    def test_build_breakout_trigger_uses_signal_bar_extreme_with_buffer(self):
        bar = pd.Series({"High": 100.0, "Low": 95.0})

        trigger = naked_k_analysis.build_breakout_trigger(bar, side="bullish", buffer_ratio=0.01)
        invalidation = naked_k_analysis.build_invalidation_level(bar, side="bullish", buffer_ratio=0.01)

        self.assertEqual(trigger, 101.0)
        self.assertEqual(invalidation, 94.05)

    def test_volatility_buffer_expands_when_atr_is_large(self):
        quiet = pd.DataFrame(
            {
                "High": [100.5] * 20,
                "Low": [99.5] * 20,
                "Close": [100.0] * 20,
            }
        )
        volatile = pd.DataFrame(
            {
                "High": [110.0] * 20,
                "Low": [90.0] * 20,
                "Close": [100.0] * 20,
            }
        )

        quiet_buffer = naked_k_analysis.build_volatility_buffer_ratio(quiet)
        volatile_buffer = naked_k_analysis.build_volatility_buffer_ratio(volatile)

        self.assertEqual(quiet_buffer, 0.002)
        self.assertGreater(volatile_buffer, quiet_buffer)

    def test_price_action_context_flags_failed_breakout_rejection(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
                "High": [106.0, 107.0, 108.0, 109.0, 110.0, 112.0],
                "Low": [98.0, 99.0, 100.0, 101.0, 102.0, 103.0],
                "Close": [104.0, 105.0, 106.0, 107.0, 108.0, 106.0],
                "Volume": [1000, 980, 1020, 1010, 990, 1800],
            },
            index=pd.date_range("2026-06-22", periods=6, freq="D"),
        )

        context = naked_k_analysis.analyze_price_action_context(frame, lookback=5)

        self.assertEqual(context["bias"], "bearish")
        self.assertIn("上破5日高点失败", context["signals"])
        self.assertIn("上影线压力", context["candle"])
        self.assertGreater(context["close_position_pct"], 0)
        self.assertLess(context["close_position_pct"], 50)
        self.assertEqual(context["volume_pressure"], "派发压力")
        self.assertIn("放量上破失败", context["warnings"])

    def test_price_action_context_flags_trend_volume_and_volatility_confirmation(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 102.0, 104.0, 106.0, 108.0, 110.0],
                "High": [103.0, 105.0, 107.0, 109.0, 111.0, 118.0],
                "Low": [99.0, 101.0, 103.0, 105.0, 107.0, 109.0],
                "Close": [102.0, 104.0, 106.0, 108.0, 110.0, 117.0],
                "Volume": [1000, 1050, 980, 1020, 1010, 1900],
            },
            index=pd.date_range("2026-06-22", periods=6, freq="D"),
        )

        context = naked_k_analysis.analyze_price_action_context(frame, lookback=5)

        self.assertEqual(context["bias"], "bullish")
        self.assertEqual(context["trend"]["direction"], "up")
        self.assertEqual(context["trend"]["strength"], "strong")
        self.assertEqual(context["volatility_state"], "突破扩张")
        self.assertEqual(context["volume_pressure"], "量价确认")
        self.assertIn("趋势结构向上", context["signals"])
        self.assertIn("放量突破扩张", context["signals"])

    def test_price_action_context_classifies_bullish_pullback_depth(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 106.0, 112.0, 118.0, 118.0, 115.0],
                "High": [106.0, 113.0, 120.0, 121.0, 119.0, 116.0],
                "Low": [99.0, 105.0, 111.0, 116.0, 114.0, 112.0],
                "Close": [105.0, 112.0, 119.0, 118.0, 115.0, 113.0],
                "Volume": [1000, 1100, 1300, 1200, 900, 850],
            },
            index=pd.date_range("2026-06-22", periods=6, freq="D"),
        )

        context = naked_k_analysis.analyze_price_action_context(frame, lookback=5)

        self.assertEqual(context["pullback"]["direction"], "bullish")
        self.assertEqual(context["pullback"]["zone"], "健康回撤")
        self.assertAlmostEqual(context["pullback"]["depth_pct"], 36.4, places=1)

    def test_price_action_context_flags_failed_breakdown_reclaim(self):
        frame = pd.DataFrame(
            {
                "Open": [102.0, 101.0, 100.0, 99.0, 98.0, 97.0],
                "High": [108.0, 107.0, 106.0, 105.0, 104.0, 101.0],
                "Low": [96.0, 95.0, 95.5, 95.2, 95.1, 93.0],
                "Close": [100.0, 99.0, 98.0, 97.0, 96.0, 100.0],
                "Volume": [1000, 980, 1020, 1010, 990, 1800],
            },
            index=pd.date_range("2026-06-22", periods=6, freq="D"),
        )

        context = naked_k_analysis.analyze_price_action_context(frame, lookback=5)

        self.assertEqual(context["bias"], "bullish")
        self.assertIn("下破5日低点收回", context["signals"])
        self.assertIn("下影线承接", context["candle"])
        self.assertGreater(context["close_position_pct"], 75)

    def test_trade_plan_uses_price_action_breakout_when_no_named_pattern(self):
        daily = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0, 103.0, 104.0, 108.0],
                "High": [106.0, 107.0, 108.0, 109.0, 110.0, 113.0],
                "Low": [98.0, 99.0, 100.0, 101.0, 102.0, 107.0],
                "Close": [104.0, 105.0, 106.0, 107.0, 108.0, 112.0],
                "Volume": [1000, 980, 1020, 1010, 990, 1800],
            },
            index=pd.date_range("2026-06-22", periods=6, freq="D"),
        )
        weekly = daily.copy()

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, weekly, previous=None)

        self.assertEqual(report.action, "小仓试错")
        self.assertEqual(report.signal_state, "planned_long")
        self.assertEqual(report.price_action["bias"], "bullish")
        self.assertIn("收盘突破5日高点", report.price_action["signals"])
        self.assertIn("裸K结构", report.rationale)

    def test_trade_plan_reports_market_structure_and_regime(self):
        daily = pd.DataFrame(
            {
                "Open": [9.0, 10.5, 10.0, 12.5, 12.0, 14.5, 14.0, 15.5, 15.0, 18.0],
                "High": [10.0, 12.0, 11.0, 14.0, 13.0, 16.0, 15.0, 17.0, 16.0, 19.0],
                "Low": [8.0, 9.0, 8.5, 10.0, 9.5, 12.0, 11.0, 13.0, 12.5, 15.0],
                "Close": [9.0, 11.0, 10.0, 13.0, 12.0, 15.0, 14.0, 16.0, 15.0, 18.5],
                "Volume": [1000, 1200, 950, 1300, 980, 1400, 1000, 1500, 1050, 1800],
            },
            index=pd.date_range("2026-06-01", periods=10, freq="D"),
        )
        weekly = daily.copy()

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, weekly, previous=None)
        text = naked_k_analysis.format_report("2026-06-12 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertEqual(report.market_structure["sequence"], "HH/HL")
        self.assertEqual(report.market_structure["latest_event"]["kind"], "BOS")
        self.assertEqual(report.market_regime["state"], "trend")
        self.assertIn("- 市场结构：", text)
        self.assertIn("BOS", text)
        self.assertIn("- 市场状态：趋势市场", text)

    def test_trade_plan_reports_multitimeframe_context(self):
        daily = pd.DataFrame(
            {
                "Open": [18.0, 19.0, 20.0, 21.0, 22.0, 23.0],
                "High": [20.0, 21.0, 22.0, 23.0, 24.0, 26.0],
                "Low": [17.0, 18.0, 19.0, 20.0, 21.0, 22.0],
                "Close": [19.0, 20.0, 21.0, 22.0, 23.0, 25.0],
                "Volume": [1000, 1000, 1000, 1000, 1000, 1600],
            },
            index=pd.date_range("2026-06-01", periods=6, freq="D"),
        )
        weekly = daily.copy()
        monthly = daily.copy()

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, weekly, previous=None, monthly=monthly)
        text = naked_k_analysis.format_report("2026-06-12 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertEqual(report.timeframe_context["macro"]["role"], "长期方向")
        self.assertIn("大周期方向", report.timeframe_context["framework"])
        self.assertIn("- 多周期框架：", text)

    def test_trade_plan_reports_trader_brief(self):
        daily = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0, 103.0, 104.0, 108.0],
                "High": [106.0, 107.0, 108.0, 109.0, 110.0, 113.0],
                "Low": [98.0, 99.0, 100.0, 101.0, 102.0, 107.0],
                "Close": [104.0, 105.0, 106.0, 107.0, 108.0, 112.0],
                "Volume": [1000, 980, 1020, 1010, 990, 1800],
            },
            index=pd.date_range("2026-06-22", periods=6, freq="D"),
        )
        weekly = daily.copy()

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, weekly, previous=None)
        text = naked_k_analysis.format_report("2026-06-29 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertIn("交易计划", report.trader_brief)
        self.assertIn("胜率估计", report.trader_brief["交易计划"])
        self.assertIn("- 交易员简报：", text)

    def test_trade_plan_reports_structured_risk_plan(self):
        daily = pd.DataFrame(
            {
                "Open": [100.0, 140.0, 101.0, 100.0, 94.0],
                "High": [102.0, 140.0, 102.0, 101.0, 107.0],
                "Low": [98.0, 110.0, 95.0, 94.0, 93.0],
                "Close": [101.0, 120.0, 100.0, 95.0, 106.0],
                "Volume": [1000, 1000, 1000, 1000, 1200],
            },
            index=pd.to_datetime(["2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"]),
        )
        weekly = daily.copy()

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, weekly, previous=None)
        text = naked_k_analysis.format_report("2026-06-26 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertEqual(report.risk_plan["direction"], "long")
        self.assertEqual(report.risk_plan["status"], "active")
        self.assertIn("1R", report.risk_plan["targets_by_r"])
        self.assertEqual(report.position_size, report.risk_plan["position_size"])
        self.assertIn("- 风险计划：", text)
        self.assertIn("账户风险", text)

    def test_trade_plan_accepts_configured_risk_limits(self):
        config = naked_k_config.TradingConfig(
            risk=naked_k_config.RiskConfig(
                account_risk_pct=0.5,
                action_gross_caps={"买入": 8.0, "小仓试错": 4.0, "减仓": 5.0, "回避": 0.0, "观望": 0.0},
            )
        )
        daily = pd.DataFrame(
            {
                "Open": [100.0, 140.0, 101.0, 100.0, 94.0],
                "High": [102.0, 140.0, 102.0, 101.0, 107.0],
                "Low": [98.0, 110.0, 95.0, 94.0, 93.0],
                "Close": [101.0, 120.0, 100.0, 95.0, 106.0],
                "Volume": [1000, 1000, 1000, 1000, 1200],
            },
            index=pd.to_datetime(["2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"]),
        )

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, daily.copy(), previous=None, config=config)

        self.assertEqual(report.risk_plan["base_account_risk_pct"], 0.5)
        self.assertEqual(report.risk_plan["max_gross_pct"], config.risk.action_gross_caps[report.action])

    def test_trade_plan_reports_trade_setup_playbook(self):
        daily = pd.DataFrame(
            {
                "Open": [9.0, 10.5, 10.0, 12.5, 12.0, 14.5, 14.0, 15.5, 15.0, 18.0],
                "High": [10.0, 12.0, 11.0, 14.0, 13.0, 16.0, 15.0, 17.0, 16.0, 19.0],
                "Low": [8.0, 9.0, 8.5, 10.0, 9.5, 12.0, 11.0, 13.0, 12.5, 15.0],
                "Close": [9.0, 11.0, 10.0, 13.0, 12.0, 15.0, 14.0, 16.0, 15.0, 18.5],
                "Volume": [1000, 1200, 950, 1300, 980, 1400, 1000, 1500, 1050, 1800],
            },
            index=pd.date_range("2026-06-01", periods=10, freq="D"),
        )
        weekly = daily.copy()

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, weekly, previous=None)
        text = naked_k_analysis.format_report("2026-06-12 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertEqual(report.trade_setup["key"], "bullish_bos_continuation")
        self.assertEqual(report.trade_setup["direction"], "long")
        self.assertIn("多头BOS趋势延续", text)
        self.assertIn("- 交易剧本：", text)

    def test_trade_plan_reports_structured_price_zones(self):
        daily = pd.DataFrame(
            {
                "Open": [100, 105, 101, 106, 102, 107, 103, 106, 102, 105],
                "High": [104, 111.0, 105, 111.4, 106, 111.2, 107, 110.8, 106, 108],
                "Low": [98, 102, 99, 103, 100, 104, 101, 103, 99, 101],
                "Close": [103, 104, 104, 105, 105, 106, 106, 104, 103, 104],
                "Volume": [1000, 1700, 1000, 1800, 1000, 1750, 1000, 1600, 1000, 1000],
            },
            index=pd.date_range("2026-06-01", periods=10, freq="D"),
        )
        weekly = daily.copy()

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, weekly, previous=None)
        text = naked_k_analysis.format_report("2026-06-12 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertEqual(report.price_zones["nearest_resistance"]["kind"], "supply")
        self.assertEqual(report.price_zones["liquidity_pools"][0]["kind"], "buy_side_liquidity")
        self.assertEqual(report.resistance, report.price_zones["nearest_resistance"]["midpoint"])
        self.assertIn("- 关键价格区域：", text)
        self.assertIn("供给区", text)
        self.assertIn("上方买方流动性池", text)

    def test_position_guidance_is_capped_by_risk_budget(self):
        guidance = naked_k_analysis.build_position_guidance(
            action="小仓试错",
            entry_trigger=105.0,
            stop_loss=95.0,
        )

        self.assertIn("最高约10.5%", guidance)
        self.assertIn("按1%账户风险", guidance)

    def test_bullish_trade_plan_includes_target_and_reward_to_risk(self):
        daily = pd.DataFrame(
            {
                "Open": [100.0, 140.0, 101.0, 100.0, 94.0],
                "High": [102.0, 140.0, 102.0, 101.0, 107.0],
                "Low": [98.0, 110.0, 95.0, 94.0, 93.0],
                "Close": [101.0, 120.0, 100.0, 95.0, 106.0],
                "Volume": [1000, 1000, 1000, 1000, 1200],
            },
            index=pd.to_datetime(["2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"]),
        )
        weekly = daily.copy()

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, weekly, previous=None)

        self.assertEqual(report.action, "买入")
        self.assertGreater(report.target_price, report.entry_trigger)
        self.assertGreater(report.reward_to_risk, 0)
        self.assertIn("最高约", report.position_size)
        self.assertEqual(report.signal_state, "planned_long")

    def test_bullish_trade_plan_downgrades_when_first_target_has_poor_reward_to_risk(self):
        daily = pd.DataFrame(
            {
                "Open": [100.0, 110.0, 101.0, 100.0, 94.0],
                "High": [102.0, 120.0, 102.0, 101.0, 107.0],
                "Low": [98.0, 105.0, 95.0, 94.0, 93.0],
                "Close": [101.0, 108.0, 100.0, 95.0, 106.0],
                "Volume": [1000, 1000, 1000, 1000, 1200],
            },
            index=pd.to_datetime(["2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"]),
        )
        weekly = daily.copy()

        report = naked_k_analysis.build_trade_plan("测试", "TEST", daily, weekly, previous=None)

        self.assertEqual(report.action, "观望")
        self.assertEqual(report.signal_state, "watching")
        self.assertIsNone(report.target_price)
        self.assertIsNone(report.reward_to_risk)
        self.assertEqual(report.position_size, "0%-10%")
        self.assertIn("盈亏比不足", report.rationale)

    def test_intraday_status_marks_confirmed_breakout(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 105.0],
                "High": [106.0, 108.0],
                "Low": [99.0, 104.0],
                "Close": [105.5, 107.2],
                "Volume": [1000, 1200],
            },
            index=pd.to_datetime(["2026-06-29 10:30:00", "2026-06-29 11:30:00"]),
        )

        status = naked_k_analysis.build_intraday_status(frame, "小仓试错", entry_trigger=106.0, stop_loss=95.0)

        self.assertEqual(status["status"], "盘中确认")
        self.assertEqual(status["latest_close"], 107.2)

    def test_intraday_status_marks_unconfirmed_breakout(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0],
                "High": [106.5],
                "Low": [99.0],
                "Close": [105.2],
                "Volume": [1000],
            },
            index=pd.to_datetime(["2026-06-29 10:30:00"]),
        )

        status = naked_k_analysis.build_intraday_status(frame, "小仓试错", entry_trigger=106.0, stop_loss=95.0)

        self.assertEqual(status["status"], "盘中突破未确认")

    def test_intraday_status_downgrades_zero_volume_latest_bar(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 106.0],
                "High": [105.0, 108.0],
                "Low": [99.0, 106.0],
                "Close": [104.0, 108.0],
                "Volume": [1000, 0],
            },
            index=pd.to_datetime(["2026-06-29 10:30:00", "2026-06-29 11:19:22"]),
        )

        status = naked_k_analysis.build_intraday_status(frame, "小仓试错", entry_trigger=106.0, stop_loss=95.0)

        self.assertEqual(status["status"], "盘中数据未确认")
        self.assertEqual(status["latest_volume"], 0)

    def test_intraday_status_marks_near_trigger_and_near_stop(self):
        near_trigger = pd.DataFrame(
            {
                "Open": [100.0],
                "High": [105.4],
                "Low": [99.0],
                "Close": [105.1],
                "Volume": [1000],
            },
            index=pd.to_datetime(["2026-06-29 10:30:00"]),
        )
        near_stop = pd.DataFrame(
            {
                "Open": [100.0],
                "High": [101.0],
                "Low": [95.4],
                "Close": [95.8],
                "Volume": [1000],
            },
            index=pd.to_datetime(["2026-06-29 10:30:00"]),
        )

        trigger_status = naked_k_analysis.build_intraday_status(
            near_trigger,
            "小仓试错",
            entry_trigger=106.0,
            stop_loss=95.0,
        )
        stop_status = naked_k_analysis.build_intraday_status(
            near_stop,
            "小仓试错",
            entry_trigger=106.0,
            stop_loss=95.0,
        )

        self.assertEqual(trigger_status["status"], "接近触发")
        self.assertEqual(stop_status["status"], "接近失效位")

    def test_format_report_does_not_append_r_to_missing_reward_to_risk(self):
        report = naked_k_analysis.InstrumentReport(
            name="测试",
            ticker="TEST",
            action="观望",
            entry_trigger=101.0,
            stop_loss=95.0,
            target_price=None,
            risk_per_share=6.0,
            reward_to_risk=None,
            signal_state="watching",
            resistance=100.0,
            support=95.0,
            position_size="0%-10%",
            rationale="无明确信号",
            daily_patterns=[],
            weekly_patterns=[],
            weekly_context="周线中性",
            data_sources={"daily": "fixture", "weekly": "fixture"},
            latest_k_dates={"daily": "2026-06-26", "weekly": "2026-06-26"},
            latest_closes={"daily": 99.0, "weekly": 99.0},
            review={"status": "观察中", "error_type": None, "note": "测试"},
            improvement="测试",
            intraday_status={"status": "盘中观察", "note": "测试"},
        )

        text = naked_k_analysis.format_report("2026-06-29 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertIn("- 目标盈亏比：暂无\n", text)
        self.assertNotIn("暂无R", text)

    def test_format_report_includes_intraday_status(self):
        report = naked_k_analysis.InstrumentReport(
            name="测试",
            ticker="TEST",
            action="小仓试错",
            entry_trigger=106.0,
            stop_loss=95.0,
            target_price=120.0,
            risk_per_share=11.0,
            reward_to_risk=1.27,
            signal_state="planned_long",
            resistance=120.0,
            support=95.0,
            position_size="最高约9.6%仓位",
            rationale="测试",
            daily_patterns=["🟢看涨吸收"],
            weekly_patterns=[],
            weekly_context="周线中性",
            data_sources={"daily": "fixture", "weekly": "fixture"},
            latest_k_dates={"daily": "2026-06-26", "weekly": "2026-06-26"},
            latest_closes={"daily": 105.0, "weekly": 105.0},
            review={"status": "观察中", "error_type": None, "note": "测试"},
            improvement="测试",
            intraday_status={
                "status": "盘中确认",
                "note": "最近有效1h收盘站上触发位",
                "latest_time": "2026-06-29 11:30:00",
                "latest_close": 107.2,
                "source": "fixture",
            },
        )

        text = naked_k_analysis.format_report("2026-06-29 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertIn("- 盘中状态：盘中确认", text)
        self.assertIn("最近有效1h收盘站上触发位", text)

    def test_format_report_includes_price_action_context(self):
        report = naked_k_analysis.InstrumentReport(
            name="测试",
            ticker="TEST",
            action="小仓试错",
            entry_trigger=113.2,
            stop_loss=106.8,
            target_price=None,
            risk_per_share=6.4,
            reward_to_risk=None,
            signal_state="planned_long",
            resistance=113.0,
            support=101.0,
            position_size="最高约15.0%仓位",
            rationale="测试",
            daily_patterns=[],
            weekly_patterns=[],
            weekly_context="周线中性",
            data_sources={"daily": "fixture", "weekly": "fixture"},
            latest_k_dates={"daily": "2026-06-26", "weekly": "2026-06-26"},
            latest_closes={"daily": 112.0, "weekly": 112.0},
            review={"status": "观察中", "error_type": None, "note": "测试"},
            improvement="测试",
            intraday_status={"status": "盘中观察", "note": "测试"},
            price_action={
                "bias": "bullish",
                "candle": ["强阳收近高点"],
                "signals": ["收盘突破5日高点"],
                "close_position_pct": 83.3,
                "trend": {"state": "上升结构", "strength": "strong"},
                "volatility_state": "突破扩张",
                "volume_pressure": "量价确认",
                "pullback": {"direction": "bullish", "zone": "健康回撤", "depth_pct": 36.4},
            },
        )

        text = naked_k_analysis.format_report("2026-06-29 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertIn("- 裸K解读：", text)
        self.assertIn("强阳收近高点", text)
        self.assertIn("收盘突破5日高点", text)
        self.assertIn("上升结构", text)
        self.assertIn("突破扩张", text)
        self.assertIn("健康回撤", text)
        self.assertIn("量价确认", text)

    def test_format_report_uses_none_for_best_trial_when_no_actionable_setups(self):
        report = naked_k_analysis.InstrumentReport(
            name="测试",
            ticker="TEST",
            action="观望",
            entry_trigger=101.0,
            stop_loss=95.0,
            target_price=None,
            risk_per_share=6.0,
            reward_to_risk=None,
            signal_state="watching",
            resistance=100.0,
            support=95.0,
            position_size="0%-10%",
            rationale="测试",
            daily_patterns=[],
            weekly_patterns=[],
            weekly_context="周线中性",
            data_sources={"daily": "fixture", "weekly": "fixture"},
            latest_k_dates={"daily": "2026-06-26", "weekly": "2026-06-26"},
            latest_closes={"daily": 99.0, "weekly": 99.0},
            review={"status": "观察中", "error_type": None, "note": "测试"},
            improvement="测试",
            intraday_status={"status": "盘中观察", "note": "测试"},
        )

        text = naked_k_analysis.format_report("2026-06-29 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertIn("- 最值得试错：暂无（无满足触发条件标的）", text)

    def test_format_report_includes_portfolio_exposure_summary(self):
        report = naked_k_analysis.InstrumentReport(
            name="测试",
            ticker="0700.HK",
            action="小仓试错",
            entry_trigger=101.0,
            stop_loss=95.0,
            target_price=112.0,
            risk_per_share=6.0,
            reward_to_risk=1.83,
            signal_state="planned_long",
            resistance=112.0,
            support=95.0,
            position_size="最高约10.0%仓位",
            rationale="测试",
            daily_patterns=[],
            weekly_patterns=[],
            weekly_context="周线中性",
            data_sources={"daily": "fixture", "weekly": "fixture"},
            latest_k_dates={"daily": "2026-06-26", "weekly": "2026-06-26"},
            latest_closes={"daily": 99.0, "weekly": 99.0},
            review={"status": "观察中", "error_type": None, "note": "测试"},
            improvement="测试",
            intraday_status={"status": "盘中观察", "note": "测试"},
            risk_plan={"direction": "long", "suggested_gross_pct": 10.0, "effective_account_risk_pct": 0.8},
        )

        text = naked_k_analysis.format_report("2026-06-29 16:00:00 CST", [report], naked_k_analysis.DEFAULT_JOURNAL_PATH)

        self.assertIn("- 组合风险：", text)
        self.assertIn("总仓位", text)

    def test_run_analysis_writes_structured_audit_events(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0, 103.0, 104.0, 108.0],
                "High": [106.0, 107.0, 108.0, 109.0, 110.0, 113.0],
                "Low": [98.0, 99.0, 100.0, 101.0, 102.0, 107.0],
                "Close": [104.0, 105.0, 106.0, 107.0, 108.0, 112.0],
                "Volume": [1000, 980, 1020, 1010, 990, 1800],
            },
            index=pd.date_range("2026-06-22", periods=6, freq="D"),
        )
        frame.attrs["source"] = "fixture"

        def fake_load_ohlcv(_ticker, interval, period):
            loaded = frame.copy()
            loaded.attrs["source"] = f"fixture-{interval}"
            return loaded

        with TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            audit_path = Path(tmpdir) / "audit.jsonl"
            with patch.object(naked_k_analysis, "load_ohlcv", side_effect=fake_load_ohlcv):
                _, reports = naked_k_analysis.run_analysis(
                    [("测试", "TEST")],
                    journal_path,
                    audit_path=audit_path,
                )

            events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]

        event_types = [event["event_type"] for event in events]
        self.assertIn("run_started", event_types)
        self.assertIn("data_loaded", event_types)
        self.assertIn("plan_generated", event_types)
        self.assertIn("portfolio_exposure", event_types)
        self.assertIn("run_completed", event_types)
        self.assertEqual(reports[0].ticker, "TEST")
        data_events = [event for event in events if event["event_type"] == "data_loaded"]
        self.assertEqual({event["payload"]["interval"] for event in data_events}, {"1d", "1wk", "1mo", "1h"})
        plan_event = next(event for event in events if event["event_type"] == "plan_generated")
        self.assertEqual(plan_event["payload"]["ticker"], "TEST")
        self.assertEqual(plan_event["payload"]["action"], reports[0].action)

    def test_run_analysis_attaches_llm_commentary_when_enabled(self):
        frame = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0, 103.0, 104.0, 108.0],
                "High": [106.0, 107.0, 108.0, 109.0, 110.0, 113.0],
                "Low": [98.0, 99.0, 100.0, 101.0, 102.0, 107.0],
                "Close": [104.0, 105.0, 106.0, 107.0, 108.0, 112.0],
                "Volume": [1000, 980, 1020, 1010, 990, 1800],
            },
            index=pd.date_range("2026-06-22", periods=6, freq="D"),
        )

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": '{"market_reading":"突破测试","journal_note":"等待回踩确认"}'
                            }
                        }
                    ]
                }

        def fake_load_ohlcv(_ticker, interval, period):
            loaded = frame.copy()
            loaded.attrs["source"] = f"fixture-{interval}"
            return loaded

        def fake_post(url, headers, json, timeout):
            return FakeResponse()

        llm_config = naked_k_llm.LLMConfig(
            enabled=True,
            base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
            api_key="test-secret-key",
            model="glm-5.2",
        )

        with TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            audit_path = Path(tmpdir) / "audit.jsonl"
            with patch.object(naked_k_analysis, "load_ohlcv", side_effect=fake_load_ohlcv):
                _, reports = naked_k_analysis.run_analysis(
                    [("测试", "TEST")],
                    journal_path,
                    audit_path=audit_path,
                    llm_config=llm_config,
                    llm_post=fake_post,
                )

            audit_text = audit_path.read_text(encoding="utf-8")

        commentary = reports[0].ai_assistant["llm_commentary"]
        self.assertEqual(commentary["status"], "ok")
        self.assertEqual(commentary["parsed"]["journal_note"], "等待回踩确认")
        self.assertIn("llm_commentary_generated", audit_text)
        self.assertNotIn("test-secret-key", audit_text)

    def test_review_previous_bullish_call_flags_false_breakout(self):
        previous = {
            "action": "小仓试错",
            "entry_trigger": 101.0,
            "stop_loss": 94.0,
        }
        current_bar = pd.Series({"Open": 100.5, "High": 102.0, "Low": 96.0, "Close": 99.0})

        review = naked_k_analysis.review_previous_call(previous, current_bar, current_close=99.0)

        self.assertEqual(review["status"], "未命中")
        self.assertEqual(review["error_type"], "假突破")

    def test_review_previous_bullish_call_marks_trigger_without_entry_when_not_confirmed(self):
        previous = {
            "action": "买入",
            "entry_trigger": 101.0,
            "stop_loss": 94.0,
        }
        current_bar = pd.Series({"Open": 100.0, "High": 100.8, "Low": 97.0, "Close": 98.5})

        review = naked_k_analysis.review_previous_call(previous, current_bar, current_close=98.5)

        self.assertEqual(review["status"], "未触发")
        self.assertEqual(review["error_type"], "缺少确认K")

    def test_drop_incomplete_hk_daily_bar_before_close(self):
        frame = pd.DataFrame(
            {
                "Open": [420.0, 423.0],
                "High": [430.0, 425.0],
                "Low": [418.0, 420.0],
                "Close": [424.0, 423.6],
                "Volume": [1000, 900],
            },
            index=pd.to_datetime(["2026-06-26", "2026-06-29"]),
        )

        trimmed = naked_k_analysis.trim_to_closed_bars(
            frame,
            market="hk",
            interval="1d",
            now=pd.Timestamp("2026-06-29 10:55:00", tz=ZoneInfo("Asia/Shanghai")),
        )

        self.assertEqual(trimmed.index[-1].strftime("%Y-%m-%d"), "2026-06-26")

    def test_drop_incomplete_hk_weekly_bar_during_current_week(self):
        frame = pd.DataFrame(
            {
                "Open": [410.0, 423.0],
                "High": [438.0, 425.0],
                "Low": [405.0, 420.0],
                "Close": [424.0, 423.6],
                "Volume": [5000, 900],
            },
            index=pd.to_datetime(["2026-06-26", "2026-06-29"]),
        )

        trimmed = naked_k_analysis.trim_to_closed_bars(
            frame,
            market="hk",
            interval="1wk",
            now=pd.Timestamp("2026-06-29 10:55:00", tz=ZoneInfo("Asia/Shanghai")),
        )

        self.assertEqual(trimmed.index[-1].strftime("%Y-%m-%d"), "2026-06-26")

    def test_drop_incomplete_monthly_bar_during_current_month(self):
        frame = pd.DataFrame(
            {
                "Open": [410.0, 423.0],
                "High": [438.0, 425.0],
                "Low": [405.0, 420.0],
                "Close": [424.0, 423.6],
                "Volume": [5000, 900],
            },
            index=pd.to_datetime(["2026-05-31", "2026-06-01"]),
        )

        trimmed = naked_k_analysis.trim_to_closed_bars(
            frame,
            market="hk",
            interval="1mo",
            now=pd.Timestamp("2026-06-29 10:55:00", tz=ZoneInfo("Asia/Shanghai")),
        )

        self.assertEqual(trimmed.index[-1].strftime("%Y-%m-%d"), "2026-05-31")

    def test_drop_zero_volume_latest_intraday_bar(self):
        frame = pd.DataFrame(
            {
                "Open": [420.0, 423.0],
                "High": [424.0, 425.0],
                "Low": [419.0, 422.0],
                "Close": [423.5, 424.0],
                "Volume": [1200, 0],
            },
            index=pd.to_datetime(["2026-06-30 14:00:00", "2026-06-30 15:00:00"]),
        )

        trimmed = naked_k_analysis.trim_to_closed_bars(
            frame,
            market="hk",
            interval="1h",
            now=pd.Timestamp("2026-06-30 15:20:00", tz=ZoneInfo("Asia/Shanghai")),
        )

        self.assertEqual(len(trimmed), 1)
        self.assertEqual(trimmed.index[-1].strftime("%Y-%m-%d %H:%M:%S"), "2026-06-30 14:00:00")

    def test_latest_journal_entry_skips_same_trading_day(self):
        rows = [
            {"ticker": "PDD", "latest_k_dates": {"daily": "2026-06-25"}, "action": "观望"},
            {"ticker": "PDD", "latest_k_dates": {"daily": "2026-06-26"}, "action": "买入"},
        ]

        latest = naked_k_analysis.latest_journal_entry(rows, "PDD", current_daily_date="2026-06-26")

        self.assertEqual(latest["latest_k_dates"]["daily"], "2026-06-25")

    def test_latest_journal_entry_ignores_future_trading_day(self):
        rows = [
            {"ticker": "9992.HK", "latest_k_dates": {"daily": "2026-06-26"}, "action": "观望"},
            {"ticker": "9992.HK", "latest_k_dates": {"daily": "2026-06-29"}, "action": "买入"},
        ]

        latest = naked_k_analysis.latest_journal_entry(rows, "9992.HK", current_daily_date="2026-06-26")

        self.assertIsNone(latest)

    def test_append_journal_replaces_same_ticker_same_daily_bar(self):
        with TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            base_report = naked_k_analysis.InstrumentReport(
                name="PDD",
                ticker="PDD",
                action="观望",
                entry_trigger=76.0,
                stop_loss=72.0,
                target_price=None,
                risk_per_share=4.0,
                reward_to_risk=None,
                signal_state="watching",
                resistance=80.0,
                support=72.0,
                position_size="0%-10%",
                rationale="首次记录",
                daily_patterns=[],
                weekly_patterns=[],
                weekly_context="周线中性",
                data_sources={"daily": "fixture", "weekly": "fixture"},
                latest_k_dates={"daily": "2026-06-30", "weekly": "2026-06-27"},
                latest_closes={"daily": 75.0, "weekly": 75.0},
                review={"status": "观察中", "error_type": None, "note": "测试"},
                improvement="测试",
                intraday_status={"status": "盘中观察", "note": "测试"},
            )
            updated_report = naked_k_analysis.InstrumentReport(
                **{
                    **base_report.__dict__,
                    "action": "小仓试错",
                    "rationale": "重跑后的最终记录",
                    "latest_closes": {"daily": 76.5, "weekly": 75.0},
                }
            )

            naked_k_analysis.append_journal(journal_path, "2026-06-30 20:00:00 CST", base_report)
            naked_k_analysis.append_journal(journal_path, "2026-06-30 20:05:00 CST", updated_report)

            rows = naked_k_analysis.load_journal(journal_path)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["action"], "小仓试错")
            self.assertEqual(rows[0]["latest_closes"]["daily"], 76.5)


if __name__ == "__main__":
    unittest.main()
