import copy
import unittest
from dataclasses import asdict
from unittest.mock import patch

import pandas as pd

import naked_k_config
import naked_k_planner
import naked_k_risk
import naked_k_synthesis
import naked_k_trade


TECHNICAL_FIELDS = (
    "action",
    "signal_state",
    "entry_trigger",
    "stop_loss",
    "target_price",
    "risk_per_share",
    "reward_to_risk",
    "position_size",
    "resistance",
    "support",
    "rationale",
    "risk_plan",
    "intraday_status",
)


class NakedKSynthesisTests(unittest.TestCase):
    def _daily(self):
        return pd.DataFrame(
            {
                "Open": [96.0, 98.0, 100.0],
                "High": [104.0, 108.0, 110.0],
                "Low": [92.0, 94.0, 90.0],
                "Close": [100.0, 102.0, 106.0],
                "Volume": [1000, 1100, 1200],
            },
            index=pd.date_range("2026-07-17", periods=3, freq="D"),
        )

    def _intraday(self):
        frame = pd.DataFrame(
            {
                "Open": [105.0],
                "High": [108.0],
                "Low": [104.0],
                "Close": [107.0],
                "Volume": [900.0],
            },
            index=pd.to_datetime(["2026-07-20 14:00:00"]),
        )
        frame.attrs["source"] = "fixture"
        frame.attrs["interval"] = "1h"
        return frame

    def _report(
        self,
        *,
        ticker="TEST",
        action="观望",
        entry_trigger=120.0,
        stop_loss=80.0,
        resistance=150.0,
        support=70.0,
        risk_plan=None,
    ):
        report = naked_k_planner.InstrumentReport(
            name="测试",
            ticker=ticker,
            action=action,
            entry_trigger=entry_trigger,
            stop_loss=stop_loss,
            target_price=None,
            risk_per_share=round(abs(entry_trigger - stop_loss), 2),
            reward_to_risk=None,
            signal_state=naked_k_trade.build_signal_state(action),
            resistance=resistance,
            support=support,
            position_size=naked_k_trade.build_position_guidance(action, entry_trigger, stop_loss),
            rationale="原始技术结论",
            daily_patterns=[],
            weekly_patterns=[],
            weekly_context="中性",
            data_sources={"daily": "fixture", "weekly": "fixture"},
            latest_k_dates={"daily": "2026-07-19", "weekly": "2026-07-19"},
            latest_closes={"daily": 106.0, "weekly": 106.0},
            review={"status": "观察中"},
            improvement="等待确认",
            intraday_status={"status": "原技术盘中状态", "nested": {"seen": True}},
            risk_plan=risk_plan
            or {
                "status": "flat" if action == "观望" else "active",
                "current_drawdown_pct": 0.0,
                "max_drawdown_pct": 8.0,
                "consecutive_losses": 0,
                "guardrails": ["原始保护"],
            },
        )
        report.technical_conclusion = naked_k_synthesis.snapshot_technical_conclusion(report)
        return report

    def _synthesized_report(
        self,
        *,
        ticker,
        action,
        confidence,
        gross_pct,
        account_risk_pct=1.0,
        status="ok",
        model_action=None,
    ):
        entry_trigger, stop_loss = (
            (89.0, 111.0) if action in {"减仓", "回避"} else (112.0, 94.0)
        )
        report = self._report(
            ticker=ticker,
            action=action,
            entry_trigger=entry_trigger,
            stop_loss=stop_loss,
        )
        report.risk_plan.update(
            {
                "status": "active" if gross_pct or account_risk_pct else "flat",
                "direction": "short" if action == "减仓" else "long",
                "suggested_gross_pct": gross_pct,
                "effective_account_risk_pct": account_risk_pct,
            }
        )
        report.technical_conclusion = naked_k_synthesis.snapshot_technical_conclusion(report)
        report.combined_conclusion = self._deliberation(
            technical_action=action,
            model_action=model_action or action,
            status=status,
            confidence=confidence,
        )
        report.combined_conclusion.update(
            {
                "final_action": action,
                "execution_side": naked_k_synthesis.side_for_action(action),
                "risk_override_reason": "",
                "price_plan_source": "deterministic_naked_k",
            }
        )
        return report

    def _portfolio_config(self, **portfolio_overrides):
        limits = {
            "max_total_gross_pct": 100.0,
            "max_direction_gross_pct": 100.0,
            "max_market_gross_pct": 100.0,
            "max_single_name_gross_pct": 100.0,
            "max_total_account_risk_pct": 100.0,
        }
        limits.update(portfolio_overrides)
        return naked_k_config.build_trading_config({"portfolio": limits})

    def _deliberation(self, *, technical_action="观望", model_action="买入", **overrides):
        payload = {
            "status": "ok",
            "technical_view": {"action": technical_action, "summary": "技术面原判断"},
            "news_view": {"direction": "strong_bullish", "summary": "消息面偏积极"},
            "conflict_analysis": "消息催化与技术等待存在冲突",
            "model_action": model_action,
            "confidence": 78,
            "decision_reasons": ["消息具有较高重要性"],
            "risk_flags": ["后续兑现仍待验证"],
            "evidence_ids": ["news-01"],
            "execution_note": "由裸K规则生成执行价格",
        }
        payload.update(overrides)
        return payload

    def test_snapshot_is_deep_and_risk_context_has_exact_config_sections(self):
        report = self._report(action="买入", entry_trigger=112.0, stop_loss=94.0)
        snapshot = naked_k_synthesis.snapshot_technical_conclusion(report)
        original_action = snapshot["action"]
        original_guardrails = list(snapshot["risk_plan"]["guardrails"])

        report.action = "回避"
        report.risk_plan["guardrails"].append("live mutation")

        self.assertEqual(snapshot["action"], original_action)
        self.assertEqual(snapshot["risk_plan"]["guardrails"], original_guardrails)
        self.assertEqual(set(snapshot), set(TECHNICAL_FIELDS))

        config = naked_k_config.build_trading_config(
            {
                "risk": {"account_risk_pct": 0.6, "max_drawdown_pct": 5.0},
                "portfolio": {"max_total_gross_pct": 55.0, "max_single_name_gross_pct": 12.0},
            }
        )
        context = naked_k_synthesis.build_risk_context(snapshot, config)
        self.assertEqual(
            set(context),
            {"technical_risk_plan", "risk_limits", "portfolio_limits"},
        )
        self.assertEqual(context["risk_limits"], asdict(config.risk))
        self.assertEqual(context["portfolio_limits"], asdict(config.portfolio))
        self.assertEqual(context["technical_risk_plan"], snapshot["risk_plan"])
        self.assertIsNot(context["technical_risk_plan"], snapshot["risk_plan"])
        context["technical_risk_plan"]["guardrails"].append("context mutation")
        self.assertEqual(snapshot["risk_plan"]["guardrails"], original_guardrails)

        defaults = naked_k_config.TradingConfig()
        default_context = naked_k_synthesis.build_risk_context(snapshot)
        self.assertEqual(default_context["risk_limits"], asdict(defaults.risk))
        self.assertEqual(default_context["portfolio_limits"], asdict(defaults.portfolio))

    def test_side_for_action_accepts_only_the_five_supported_actions(self):
        expected = {
            "买入": "long",
            "小仓试错": "long",
            "观望": "neutral",
            "减仓": "bearish_defensive",
            "回避": "bearish_defensive",
        }
        self.assertEqual(
            {action: naked_k_synthesis.side_for_action(action) for action in expected},
            expected,
        )
        with self.assertRaises(ValueError):
            naked_k_synthesis.side_for_action("做空")

    def test_cross_direction_actions_rebuild_prices_with_matching_naked_k_side(self):
        daily = self._daily()
        bullish_report = self._report(action="观望")
        with (
            patch(
                "naked_k_synthesis.naked_k_trade.build_breakout_trigger",
                wraps=naked_k_trade.build_breakout_trigger,
            ) as breakout,
            patch(
                "naked_k_synthesis.naked_k_trade.build_invalidation_level",
                wraps=naked_k_trade.build_invalidation_level,
            ) as invalidation,
        ):
            naked_k_synthesis.synchronize_final_action(
                bullish_report,
                daily,
                "买入",
                reason="消息催化",
            )
        self.assertEqual(breakout.call_args.args[1], "bullish")
        self.assertEqual(invalidation.call_args.args[1], "bullish")

        bearish_report = self._report(action="买入", entry_trigger=112.0, stop_loss=94.0)
        with (
            patch(
                "naked_k_synthesis.naked_k_trade.build_breakout_trigger",
                wraps=naked_k_trade.build_breakout_trigger,
            ) as breakout,
            patch(
                "naked_k_synthesis.naked_k_trade.build_invalidation_level",
                wraps=naked_k_trade.build_invalidation_level,
            ) as invalidation,
        ):
            naked_k_synthesis.synchronize_final_action(
                bearish_report,
                daily,
                "回避",
                reason="消息风险",
            )
        self.assertEqual(breakout.call_args.args[1], "bearish")
        self.assertEqual(invalidation.call_args.args[1], "bearish")

    def test_same_direction_action_preserves_prices_and_recalculates_risk_cap(self):
        daily = self._daily()
        report = self._report(action="买入", entry_trigger=112.0, stop_loss=94.0)
        config = naked_k_config.build_trading_config(
            {"risk": {"action_gross_caps": {"小仓试错": 7.0}}}
        )

        naked_k_synthesis.synchronize_final_action(
            report,
            daily,
            "小仓试错",
            reason="保守参与",
            config=config,
        )

        self.assertEqual(report.action, "小仓试错")
        self.assertEqual(report.entry_trigger, 112.0)
        self.assertEqual(report.stop_loss, 94.0)
        self.assertEqual(report.risk_per_share, 18.0)
        self.assertEqual(report.risk_plan["max_gross_pct"], 7.0)
        self.assertLessEqual(report.risk_plan["suggested_gross_pct"], 7.0)

    def test_observation_rebuilds_bullish_boundaries_and_clears_directionality(self):
        daily = self._daily()
        report = self._report(action="减仓", entry_trigger=89.0, stop_loss=111.0)
        buffer_ratio = naked_k_trade.build_volatility_buffer_ratio(daily)
        expected_upper = naked_k_trade.build_breakout_trigger(
            daily.iloc[-1], "bullish", buffer_ratio=buffer_ratio
        )
        expected_lower = naked_k_trade.build_invalidation_level(
            daily.iloc[-1], "bullish", buffer_ratio=buffer_ratio
        )

        naked_k_synthesis.synchronize_final_action(
            report,
            daily,
            "观望",
            reason="等待确认",
        )

        self.assertEqual(report.action, "观望")
        self.assertEqual(report.entry_trigger, expected_upper)
        self.assertEqual(report.stop_loss, expected_lower)
        self.assertIsNone(report.target_price)
        self.assertIsNone(report.reward_to_risk)
        self.assertEqual(report.signal_state, "watching")
        self.assertEqual(report.position_size, "0%-10%")
        self.assertEqual(report.risk_plan["direction"], "none")
        self.assertEqual(report.risk_plan["suggested_gross_pct"], 0.0)
        self.assertEqual(report.risk_plan["effective_account_risk_pct"], 0.0)

    def test_apply_deliberation_recalculates_all_executable_fields_and_ignores_model_numbers(self):
        daily = self._daily()
        intraday = self._intraday()
        report = self._report(action="观望")
        deliberation = self._deliberation(
            entry_trigger=99999.0,
            stop_loss=88888.0,
            target_price=77777.0,
            unrelated_numeric_value=66666.0,
        )
        buffer_ratio = naked_k_trade.build_volatility_buffer_ratio(daily)
        entry = naked_k_trade.build_breakout_trigger(daily.iloc[-1], "bullish", buffer_ratio=buffer_ratio)
        stop = naked_k_trade.build_invalidation_level(daily.iloc[-1], "bullish", buffer_ratio=buffer_ratio)
        target, risk_per_share, reward_to_risk = naked_k_trade.build_trade_metrics(
            "买入", entry, stop, report.resistance, report.support
        )
        expected_risk = naked_k_risk.build_risk_plan(
            action="买入",
            entry_trigger=entry,
            stop_loss=stop,
            target_price=target,
        )
        expected_intraday = naked_k_trade.build_intraday_status(intraday, "买入", entry, stop)

        combined = naked_k_synthesis.apply_deliberation(
            report,
            daily,
            deliberation,
            intraday=intraday,
        )

        self.assertEqual(report.action, "买入")
        self.assertEqual(report.entry_trigger, entry)
        self.assertEqual(report.stop_loss, stop)
        self.assertEqual(report.target_price, target)
        self.assertEqual(report.risk_per_share, risk_per_share)
        self.assertEqual(report.reward_to_risk, reward_to_risk)
        self.assertEqual(report.position_size, expected_risk["position_size"])
        self.assertEqual(report.signal_state, "planned_long")
        self.assertEqual(report.intraday_status, expected_intraday)
        self.assertEqual(report.risk_plan, expected_risk)
        self.assertNotIn(99999.0, (report.entry_trigger, report.stop_loss, report.target_price))
        self.assertEqual(combined, report.combined_conclusion)
        self.assertEqual(combined["model_action"], "买入")
        self.assertEqual(combined["final_action"], "买入")
        self.assertEqual(combined["risk_override_reason"], "")
        self.assertEqual(combined["execution_side"], "long")
        self.assertEqual(combined["price_plan_source"], "deterministic_naked_k")

    def test_low_reward_bullish_proposal_is_synchronized_to_observation(self):
        daily = self._daily()
        report = self._report(action="观望", resistance=120.0, support=70.0)

        combined = naked_k_synthesis.apply_deliberation(
            report,
            daily,
            self._deliberation(model_action="买入"),
        )

        self.assertEqual(combined["model_action"], "买入")
        self.assertEqual(combined["final_action"], "观望")
        self.assertEqual(report.action, "观望")
        self.assertTrue(combined["risk_override_reason"])
        self.assertIn("盈亏比", combined["risk_override_reason"])
        self.assertIsNone(report.target_price)
        self.assertEqual(report.risk_plan["suggested_gross_pct"], 0.0)
        self.assertEqual(report.risk_plan["effective_account_risk_pct"], 0.0)

    def test_drawdown_blocks_bullish_proposal_while_consecutive_losses_reduce_it(self):
        daily = self._daily()
        blocked_report = self._report(
            risk_plan={
                "current_drawdown_pct": 8.0,
                "max_drawdown_pct": 8.0,
                "consecutive_losses": 0,
                "guardrails": [],
            }
        )
        blocked = naked_k_synthesis.apply_deliberation(
            blocked_report,
            daily,
            self._deliberation(model_action="买入"),
        )
        self.assertEqual(blocked["model_action"], "买入")
        self.assertEqual(blocked["final_action"], "观望")
        self.assertIn("最大回撤保护", blocked["risk_override_reason"])
        self.assertEqual(blocked_report.risk_plan["current_drawdown_pct"], 8.0)

        reduced_report = self._report(
            risk_plan={
                "current_drawdown_pct": 0.0,
                "max_drawdown_pct": 8.0,
                "consecutive_losses": 3,
                "guardrails": [],
            }
        )
        reduced = naked_k_synthesis.apply_deliberation(
            reduced_report,
            daily,
            self._deliberation(model_action="买入"),
        )
        self.assertEqual(reduced["final_action"], "买入")
        self.assertEqual(reduced["risk_override_reason"], "")
        self.assertEqual(reduced_report.risk_plan["status"], "reduced")
        self.assertEqual(reduced_report.risk_plan["effective_account_risk_pct"], 0.5)
        self.assertEqual(reduced_report.risk_plan["consecutive_losses"], 3)

    def test_bearish_actions_are_defensive_and_avoid_has_no_phantom_risk(self):
        daily = self._daily()
        report = self._report(action="买入", entry_trigger=112.0, stop_loss=94.0)

        combined = naked_k_synthesis.apply_deliberation(
            report,
            daily,
            self._deliberation(technical_action="买入", model_action="回避"),
        )

        self.assertEqual(report.action, "回避")
        self.assertEqual(combined["execution_side"], "bearish_defensive")
        self.assertEqual(report.signal_state, "planned_defensive")
        self.assertEqual(report.risk_plan["engine_direction"], "short")
        self.assertEqual(report.risk_plan["direction"], "bearish_defensive")
        self.assertEqual(report.risk_plan["position_intent"], "reduce_or_avoid_long_exposure")
        self.assertNotEqual(report.risk_plan["position_intent"], "open_short")
        self.assertEqual(report.risk_plan["suggested_gross_pct"], 0.0)
        self.assertEqual(report.risk_plan["effective_account_risk_pct"], 0.0)

    def test_custom_avoid_cap_still_has_zero_no_new_position_risk_guidance(self):
        daily = self._daily()
        report = self._report(action="买入", entry_trigger=112.0, stop_loss=94.0)
        config = naked_k_config.build_trading_config(
            {"risk": {"action_gross_caps": {"回避": 25.0}}}
        )

        naked_k_synthesis.apply_deliberation(
            report,
            daily,
            self._deliberation(technical_action="买入", model_action="回避"),
            config=config,
        )

        self.assertEqual(report.action, "回避")
        self.assertEqual(report.position_size, "0%-5%")
        self.assertEqual(report.risk_plan["status"], "flat")
        self.assertEqual(report.risk_plan["suggested_gross_pct"], 0.0)
        self.assertEqual(report.risk_plan["effective_account_risk_pct"], 0.0)
        self.assertEqual(report.risk_plan["position_size"], "0%（无新仓计划）")
        self.assertEqual(report.risk_plan["position_intent"], "reduce_or_avoid_long_exposure")
        self.assertNotIn("做空", report.risk_plan["position_size"])

    def test_synthesis_failure_restores_snapshot_and_retains_validated_deliberation(self):
        daily = self._daily()
        report = self._report(action="观望")
        stored_snapshot = copy.deepcopy(report.technical_conclusion)
        deliberation = self._deliberation(model_action="买入")

        with patch(
            "naked_k_synthesis.naked_k_trade.build_trade_metrics",
            side_effect=RuntimeError("price rebuild failed"),
        ):
            combined = naked_k_synthesis.apply_deliberation(report, daily, deliberation)

        for field in TECHNICAL_FIELDS:
            self.assertEqual(getattr(report, field), stored_snapshot[field], field)
        self.assertEqual(combined["status"], "technical_fallback")
        self.assertEqual(combined["technical_view"], deliberation["technical_view"])
        self.assertEqual(combined["news_view"], deliberation["news_view"])
        self.assertEqual(combined["conflict_analysis"], deliberation["conflict_analysis"])
        self.assertEqual(combined["model_action"], "买入")
        self.assertEqual(combined["final_action"], stored_snapshot["action"])
        self.assertEqual(combined["confidence"], deliberation["confidence"])
        self.assertEqual(combined["decision_reasons"], deliberation["decision_reasons"])
        self.assertEqual(combined["risk_flags"], deliberation["risk_flags"])
        self.assertEqual(combined["evidence_ids"], deliberation["evidence_ids"])
        self.assertIn("price rebuild failed", combined["risk_override_reason"])
        self.assertEqual(combined["price_plan_source"], "deterministic_naked_k")
        self.assertEqual(report.combined_conclusion, combined)

    def test_partial_report_mutation_is_deeply_rolled_back_on_apply_failure(self):
        daily = self._daily()
        report = self._report(action="观望")
        stored_snapshot = copy.deepcopy(report.technical_conclusion)
        deliberation = self._deliberation(model_action="买入")

        def mutate_then_fail(live_report, candidate):
            live_report.action = candidate["action"]
            live_report.entry_trigger = candidate["entry_trigger"]
            live_report.risk_plan["guardrails"].append("partial mutation")
            live_report.intraday_status["nested"]["seen"] = False
            raise RuntimeError("apply failed after partial mutation")

        with patch(
            "naked_k_synthesis._apply_candidate",
            side_effect=mutate_then_fail,
        ):
            combined = naked_k_synthesis.apply_deliberation(report, daily, deliberation)

        for field in TECHNICAL_FIELDS:
            self.assertEqual(getattr(report, field), stored_snapshot[field], field)
        self.assertEqual(combined["status"], "technical_fallback")
        self.assertEqual(combined["model_action"], deliberation["model_action"])
        self.assertEqual(combined["final_action"], stored_snapshot["action"])
        self.assertEqual(combined["technical_view"], deliberation["technical_view"])
        self.assertEqual(combined["news_view"], deliberation["news_view"])
        self.assertEqual(combined["conflict_analysis"], deliberation["conflict_analysis"])
        self.assertEqual(combined["decision_reasons"], deliberation["decision_reasons"])
        self.assertEqual(combined["risk_flags"], deliberation["risk_flags"])
        self.assertEqual(combined["evidence_ids"], deliberation["evidence_ids"])
        self.assertIn("apply failed after partial mutation", combined["risk_override_reason"])

    def test_portfolio_guard_leaves_within_limit_proposals_untouched(self):
        reports = [
            self._synthesized_report(
                ticker="AAA", action="买入", confidence=60, gross_pct=10.0
            ),
            self._synthesized_report(
                ticker="BBB", action="减仓", confidence=40, gross_pct=5.0
            ),
        ]
        before = copy.deepcopy(reports)

        result = naked_k_synthesis.apply_portfolio_guardrails(
            reports,
            {report.ticker: self._daily() for report in reports},
            config=self._portfolio_config(max_total_gross_pct=20.0),
        )

        self.assertEqual(result["status"], "within_limits")
        self.assertEqual(result["overrides"], [])
        self.assertEqual(result["unresolved_guardrails"], [])
        self.assertEqual(reports, before)

    def test_portfolio_guard_uses_confidence_gross_and_ticker_priority(self):
        reports = [
            self._synthesized_report(
                ticker="HIGH", action="买入", confidence=90, gross_pct=20.0
            ),
            self._synthesized_report(
                ticker="SMALL", action="买入", confidence=40, gross_pct=10.0
            ),
            self._synthesized_report(
                ticker="BIG-B", action="小仓试错", confidence=40, gross_pct=20.0
            ),
            self._synthesized_report(
                ticker="BIG-A", action="减仓", confidence=40, gross_pct=20.0
            ),
            self._synthesized_report(
                ticker="FLAT-WATCH", action="观望", confidence=1, gross_pct=0.0,
                account_risk_pct=0.0,
            ),
            self._synthesized_report(
                ticker="FLAT-AVOID", action="回避", confidence=1, gross_pct=0.0,
                account_risk_pct=0.0,
            ),
        ]

        with patch(
            "naked_k_news_llm.requests.post",
            side_effect=AssertionError("portfolio guard must not call a model"),
        ), patch(
            "naked_k_synthesis.synchronize_final_action",
            wraps=naked_k_synthesis.synchronize_final_action,
        ) as synchronize:
            result = naked_k_synthesis.apply_portfolio_guardrails(
                reports,
                {report.ticker: self._daily() for report in reports},
                config=self._portfolio_config(max_total_gross_pct=30.0),
            )

        self.assertEqual(result["status"], "within_limits")
        self.assertEqual(
            [override["ticker"] for override in result["overrides"]],
            ["BIG-A", "BIG-B"],
        )
        self.assertEqual(synchronize.call_count, 2)
        self.assertEqual(
            [call.args[0].ticker for call in synchronize.call_args_list],
            ["BIG-A", "BIG-B"],
        )
        by_ticker = {report.ticker: report for report in reports}
        self.assertEqual(by_ticker["BIG-A"].action, "回避")
        self.assertEqual(by_ticker["BIG-B"].action, "观望")
        self.assertEqual(by_ticker["SMALL"].action, "买入")
        self.assertEqual(by_ticker["HIGH"].action, "买入")
        self.assertEqual(by_ticker["FLAT-WATCH"].action, "观望")
        self.assertEqual(by_ticker["FLAT-AVOID"].action, "回避")
        for ticker in ("BIG-A", "BIG-B"):
            report = by_ticker[ticker]
            self.assertEqual(report.risk_plan["suggested_gross_pct"], 0.0)
            self.assertEqual(report.risk_plan["effective_account_risk_pct"], 0.0)
            self.assertEqual(
                report.combined_conclusion["final_action"], report.action
            )
            self.assertEqual(
                report.combined_conclusion["execution_side"],
                naked_k_synthesis.side_for_action(report.action),
            )
            self.assertTrue(report.combined_conclusion["risk_override_reason"])

        first_override = result["overrides"][0]
        self.assertEqual(
            set(first_override),
            {
                "ticker",
                "model_action",
                "prior_final_action",
                "protected_final_action",
                "guardrail_reason",
            },
        )
        self.assertEqual(first_override["model_action"], "减仓")
        self.assertEqual(first_override["prior_final_action"], "减仓")
        self.assertEqual(first_override["protected_final_action"], "回避")
        self.assertIn("总仓位暴露超限", first_override["guardrail_reason"])

    def test_portfolio_guard_resolves_account_risk_only_limit(self):
        reports = [
            self._synthesized_report(
                ticker="LOW", action="买入", confidence=30, gross_pct=5.0,
                account_risk_pct=1.0,
            ),
            self._synthesized_report(
                ticker="HIGH", action="小仓试错", confidence=80, gross_pct=5.0,
                account_risk_pct=1.0,
            ),
        ]

        result = naked_k_synthesis.apply_portfolio_guardrails(
            reports,
            {report.ticker: self._daily() for report in reports},
            config=self._portfolio_config(max_total_account_risk_pct=1.0),
        )

        self.assertEqual(result["status"], "within_limits")
        self.assertEqual(result["total_account_risk_pct"], 1.0)
        self.assertEqual([item["ticker"] for item in result["overrides"]], ["LOW"])
        self.assertEqual(reports[0].action, "观望")
        self.assertEqual(reports[0].risk_plan["suggested_gross_pct"], 0.0)
        self.assertEqual(reports[0].risk_plan["effective_account_risk_pct"], 0.0)

    def test_portfolio_guard_reports_unresolved_fallback_exposure_without_mutation(self):
        fallback = self._synthesized_report(
            ticker="FALLBACK",
            action="买入",
            confidence=10,
            gross_pct=50.0,
            status="technical_fallback",
        )
        before = copy.deepcopy(fallback)

        result = naked_k_synthesis.apply_portfolio_guardrails(
            [fallback],
            {fallback.ticker: self._daily()},
            config=self._portfolio_config(max_total_gross_pct=10.0),
        )

        self.assertEqual(result["status"], "over_limit")
        self.assertEqual(result["overrides"], [])
        self.assertIn("总仓位暴露超限", result["unresolved_guardrails"])
        self.assertEqual(fallback, before)

    def test_portfolio_guard_never_overrides_a_report_twice(self):
        reports = [
            self._synthesized_report(
                ticker="AAA", action="买入", confidence=10, gross_pct=20.0
            ),
            self._synthesized_report(
                ticker="BBB", action="减仓", confidence=20, gross_pct=20.0
            ),
        ]

        with patch(
            "naked_k_synthesis.synchronize_final_action",
            wraps=naked_k_synthesis.synchronize_final_action,
        ) as synchronize:
            result = naked_k_synthesis.apply_portfolio_guardrails(
                reports,
                {report.ticker: self._daily() for report in reports},
                config=self._portfolio_config(max_total_gross_pct=0.0),
            )

        synchronized_reports = [call.args[0] for call in synchronize.call_args_list]
        self.assertEqual(len(synchronized_reports), len({id(item) for item in synchronized_reports}))
        self.assertEqual(len(result["overrides"]), 2)

    def test_portfolio_guard_failure_can_be_transactionally_restored_by_caller(self):
        reports = [
            self._synthesized_report(
                ticker="AAA", action="买入", confidence=10, gross_pct=20.0
            ),
            self._synthesized_report(
                ticker="BBB", action="买入", confidence=20, gross_pct=20.0
            ),
        ]
        pre_guard = copy.deepcopy(reports)
        real_synchronize = naked_k_synthesis.synchronize_final_action
        calls = 0

        def synchronize_one_then_raise(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return real_synchronize(*args, **kwargs)
            raise RuntimeError("guard sync failed")

        with patch(
            "naked_k_synthesis.synchronize_final_action",
            side_effect=synchronize_one_then_raise,
        ):
            with self.assertRaisesRegex(RuntimeError, "guard sync failed"):
                naked_k_synthesis.apply_portfolio_guardrails(
                    reports,
                    {report.ticker: self._daily() for report in reports},
                    config=self._portfolio_config(max_total_gross_pct=0.0),
                )

        self.assertNotEqual(reports, pre_guard)
        reports[:] = pre_guard
        self.assertEqual(reports, pre_guard)


if __name__ == "__main__":
    unittest.main()
