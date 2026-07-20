from __future__ import annotations

import copy
from dataclasses import asdict
from typing import Any

import pandas as pd

import naked_k_config
import naked_k_risk
import naked_k_trade


TECHNICAL_SNAPSHOT_FIELDS = (
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

ACTION_SIDE_MAP = {
    "买入": "long",
    "小仓试错": "long",
    "观望": "neutral",
    "减仓": "bearish_defensive",
    "回避": "bearish_defensive",
}


def snapshot_technical_conclusion(report: Any) -> dict[str, Any]:
    return copy.deepcopy(
        {field: getattr(report, field) for field in TECHNICAL_SNAPSHOT_FIELDS}
    )


def build_risk_context(
    technical_snapshot: dict[str, Any],
    trading_config: naked_k_config.TradingConfig | None = None,
) -> dict[str, Any]:
    active_config = trading_config or naked_k_config.TradingConfig()
    return {
        "technical_risk_plan": copy.deepcopy(technical_snapshot.get("risk_plan", {})),
        "risk_limits": asdict(active_config.risk),
        "portfolio_limits": asdict(active_config.portfolio),
    }


def side_for_action(action: str) -> str:
    try:
        return ACTION_SIDE_MAP[action]
    except KeyError as exc:
        raise ValueError(f"unsupported synthesis action: {action}") from exc


def _stored_technical_snapshot(report: Any) -> dict[str, Any]:
    stored = getattr(report, "technical_conclusion", None)
    if isinstance(stored, dict) and all(field in stored for field in TECHNICAL_SNAPSHOT_FIELDS):
        return copy.deepcopy(stored)
    return snapshot_technical_conclusion(report)


def _deterministic_prices(
    technical_snapshot: dict[str, Any],
    daily: pd.DataFrame,
    action: str,
) -> tuple[float, float]:
    final_side = side_for_action(action)
    technical_side = side_for_action(str(technical_snapshot["action"]))

    if action == "观望":
        price_side = "bullish"
    elif final_side == technical_side:
        return (
            float(technical_snapshot["entry_trigger"]),
            float(technical_snapshot["stop_loss"]),
        )
    elif final_side == "long":
        price_side = "bullish"
    else:
        price_side = "bearish"

    buffer_ratio = naked_k_trade.build_volatility_buffer_ratio(daily)
    latest_bar = daily.iloc[-1]
    return (
        naked_k_trade.build_breakout_trigger(
            latest_bar,
            price_side,
            buffer_ratio=buffer_ratio,
        ),
        naked_k_trade.build_invalidation_level(
            latest_bar,
            price_side,
            buffer_ratio=buffer_ratio,
        ),
    )


def _build_candidate(
    technical_snapshot: dict[str, Any],
    daily: pd.DataFrame,
    action: str,
    *,
    reason: str,
    intraday: pd.DataFrame | None,
    config: naked_k_config.TradingConfig | None,
) -> dict[str, Any]:
    side_for_action(action)
    entry_trigger, stop_loss = _deterministic_prices(technical_snapshot, daily, action)
    target_price, risk_per_share, reward_to_risk = naked_k_trade.build_trade_metrics(
        action,
        entry_trigger,
        stop_loss,
        float(technical_snapshot["resistance"]),
        float(technical_snapshot["support"]),
    )
    protected_action, _, _, reward_filter_note = naked_k_trade.downgrade_low_reward_setup(
        action,
        target_price,
        reward_to_risk,
    )

    technical_risk = technical_snapshot.get("risk_plan")
    if not isinstance(technical_risk, dict):
        technical_risk = {}
    risk_plan = naked_k_risk.build_risk_plan(
        action=action,
        entry_trigger=entry_trigger,
        stop_loss=stop_loss,
        target_price=target_price,
        current_drawdown_pct=float(technical_risk.get("current_drawdown_pct", 0.0)),
        consecutive_losses=int(technical_risk.get("consecutive_losses", 0)),
        config=config.risk if config is not None else None,
    )

    protection_reasons: list[str] = []
    if reward_filter_note:
        protection_reasons.append(reward_filter_note)
    if action in naked_k_trade.BULLISH_ACTIONS and risk_plan.get("status") == "blocked":
        protected_action = "观望"
        guardrails = risk_plan.get("guardrails")
        if isinstance(guardrails, list) and guardrails:
            protection_reasons.extend(str(item) for item in guardrails)
        else:
            protection_reasons.append("风险保护触发")

    position_guidance = naked_k_trade.build_position_guidance(
        action,
        entry_trigger,
        stop_loss,
    )
    position_size = (
        str(risk_plan["position_size"])
        if action in naked_k_trade.BULLISH_ACTIONS
        else position_guidance
    )
    signal_state = naked_k_trade.build_signal_state(action)

    execution_side = side_for_action(action)
    if execution_side == "bearish_defensive":
        risk_plan["engine_direction"] = risk_plan.get("direction")
        risk_plan["direction"] = "bearish_defensive"
        risk_plan["position_intent"] = "reduce_or_avoid_long_exposure"
        signal_state = "planned_defensive"

    if action in {"观望", "回避"}:
        risk_plan["status"] = "flat"
        risk_plan["suggested_gross_pct"] = 0.0
        risk_plan["effective_account_risk_pct"] = 0.0
    if action == "观望":
        target_price = None
        reward_to_risk = None
        position_size = "0%-10%"
        signal_state = "watching"

    base_rationale = str(technical_snapshot.get("rationale", ""))
    rationale = f"{base_rationale}；综合结论：{reason}" if reason else base_rationale
    intraday_status = naked_k_trade.build_intraday_status(
        intraday,
        action,
        entry_trigger,
        stop_loss,
    )
    return {
        "action": action,
        "signal_state": signal_state,
        "entry_trigger": entry_trigger,
        "stop_loss": stop_loss,
        "target_price": target_price,
        "risk_per_share": risk_per_share,
        "reward_to_risk": reward_to_risk,
        "position_size": position_size,
        "resistance": technical_snapshot["resistance"],
        "support": technical_snapshot["support"],
        "rationale": rationale,
        "risk_plan": risk_plan,
        "intraday_status": intraday_status,
        "protected_action": protected_action,
        "protection_reason": "；".join(dict.fromkeys(protection_reasons)),
    }


def _apply_candidate(report: Any, candidate: dict[str, Any]) -> None:
    for field in TECHNICAL_SNAPSHOT_FIELDS:
        setattr(report, field, copy.deepcopy(candidate[field]))


def _synchronized_candidate(
    technical_snapshot: dict[str, Any],
    daily: pd.DataFrame,
    action: str,
    *,
    reason: str,
    intraday: pd.DataFrame | None,
    config: naked_k_config.TradingConfig | None,
) -> tuple[dict[str, Any], str]:
    candidate = _build_candidate(
        technical_snapshot,
        daily,
        action,
        reason=reason,
        intraday=intraday,
        config=config,
    )
    protected_action = str(candidate["protected_action"])
    protection_reason = str(candidate["protection_reason"])
    if protected_action != action:
        protected_reason = "；".join(part for part in (reason, protection_reason) if part)
        candidate = _build_candidate(
            technical_snapshot,
            daily,
            protected_action,
            reason=protected_reason,
            intraday=intraday,
            config=config,
        )
    return candidate, protection_reason


def synchronize_final_action(
    report: Any,
    daily: pd.DataFrame,
    final_action: str,
    *,
    reason: str,
    intraday: pd.DataFrame | None = None,
    config: naked_k_config.TradingConfig | None = None,
) -> None:
    technical_snapshot = _stored_technical_snapshot(report)
    candidate, _ = _synchronized_candidate(
        technical_snapshot,
        daily,
        final_action,
        reason=reason,
        intraday=intraday,
        config=config,
    )
    _apply_candidate(report, candidate)


def _combined_conclusion(
    deliberation: dict[str, Any],
    *,
    status: str,
    final_action: str,
    risk_override_reason: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "technical_view": copy.deepcopy(deliberation["technical_view"]),
        "news_view": copy.deepcopy(deliberation["news_view"]),
        "conflict_analysis": str(deliberation["conflict_analysis"]),
        "model_action": str(deliberation["model_action"]),
        "final_action": final_action,
        "confidence": deliberation["confidence"],
        "decision_reasons": copy.deepcopy(deliberation["decision_reasons"]),
        "risk_flags": copy.deepcopy(deliberation["risk_flags"]),
        "evidence_ids": copy.deepcopy(deliberation["evidence_ids"]),
        "execution_note": str(deliberation["execution_note"]),
        "execution_side": side_for_action(final_action),
        "risk_override_reason": risk_override_reason,
        "price_plan_source": "deterministic_naked_k",
    }


def apply_deliberation(
    report: Any,
    daily: pd.DataFrame,
    deliberation: dict[str, Any],
    *,
    intraday: pd.DataFrame | None = None,
    config: naked_k_config.TradingConfig | None = None,
) -> dict[str, Any]:
    technical_snapshot = _stored_technical_snapshot(report)
    model_action = str(deliberation["model_action"])
    decision_reason = "；".join(str(item) for item in deliberation["decision_reasons"])

    try:
        candidate, protection_reason = _synchronized_candidate(
            technical_snapshot,
            daily,
            model_action,
            reason=decision_reason,
            intraday=intraday,
            config=config,
        )
        final_action = str(candidate["action"])
        _apply_candidate(report, candidate)
        risk_override_reason = protection_reason if final_action != model_action else ""
        combined = _combined_conclusion(
            deliberation,
            status="ok",
            final_action=final_action,
            risk_override_reason=risk_override_reason,
        )
    except Exception as exc:
        for field in TECHNICAL_SNAPSHOT_FIELDS:
            setattr(report, field, copy.deepcopy(technical_snapshot[field]))
        final_action = str(technical_snapshot["action"])
        fallback_reason = (
            "确定性价格计划重建失败，已安全回退技术结论："
            f"{type(exc).__name__}: {exc}"
        )
        combined = _combined_conclusion(
            deliberation,
            status="technical_fallback",
            final_action=final_action,
            risk_override_reason=fallback_reason,
        )

    report.combined_conclusion = combined
    return combined
