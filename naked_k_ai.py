from __future__ import annotations

from typing import Any


def _value(item: Any, field: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(field, default)
    return getattr(item, field, default)


def _as_dict(item: Any, field: str) -> dict[str, Any]:
    value = _value(item, field, {})
    return value if isinstance(value, dict) else {}


def _setup_key(sample: dict[str, Any]) -> str:
    return str(sample.get("setup") or sample.get("setup_key") or sample.get("trade_setup_key") or "")


def calibrate_historical_edge(
    samples: list[dict[str, Any]],
    setup_key: str | None = None,
    regime: str | None = None,
    min_samples: int = 10,
) -> dict[str, Any]:
    filtered: list[dict[str, Any]] = []
    for sample in samples:
        if setup_key is not None and _setup_key(sample) != setup_key:
            continue
        if regime is not None and str(sample.get("regime") or "") != regime:
            continue
        if sample.get("r_multiple") is None:
            continue
        filtered.append(sample)

    values = [float(sample["r_multiple"]) for sample in filtered]
    sample_count = len(values)
    if not values:
        return {
            "sample_count": 0,
            "win_rate": None,
            "average_r": None,
            "confidence_source": "insufficient_samples",
            "note": "没有足够历史样本，不能把主观判断伪装成胜率",
        }

    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    confidence_source = "historical_samples" if sample_count >= min_samples else "insufficient_samples"
    return {
        "sample_count": sample_count,
        "win_rate": round(len(wins) / sample_count * 100, 2),
        "average_r": round(sum(values) / sample_count, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
        "best_r": round(max(values), 2),
        "worst_r": round(min(values), 2),
        "confidence_source": confidence_source,
        "note": (
            "样本达到阈值，可作为交易剧本的历史校准"
            if confidence_source == "historical_samples"
            else "样本不足，仅保留为观察数据，不输出概率化胜率"
        ),
    }


def attribute_plan_outcome(report: Any, outcome: dict[str, Any] | None = None) -> dict[str, Any]:
    outcome = outcome or _as_dict(report, "review")
    error_type = str(outcome.get("error_type") or "")
    status = str(outcome.get("status") or "")
    note = str(outcome.get("note") or "")
    price_action = _as_dict(report, "price_action")
    timeframe = _as_dict(report, "timeframe_context")

    if error_type in {"假突破", "假跌破"}:
        failure_type = "failed_breakout"
        lesson = "触发后没有收盘确认，说明突破行为被对手盘吸收，后续需要等待确认K或小周期结构再入场"
    elif error_type == "缺少确认K" or status == "未触发":
        failure_type = "no_confirmation"
        lesson = "计划没有被市场触发，正确处理是继续等待，而不是提前在区间中部追价"
    elif timeframe.get("alignment") == "conflict":
        failure_type = "timeframe_conflict"
        lesson = "小周期机会与高周期方向冲突，应该降低仓位或等待高周期重新确认"
    elif price_action.get("warnings"):
        failure_type = "context_warning"
        lesson = "价格行为已经给出风险提示，复盘时应检查是否忽略了影线、量价或区域压力"
    else:
        failure_type = "not_applicable"
        lesson = "当前没有明确失败归因，继续记录样本等待更多复盘证据"

    return {
        "status": status or "unknown",
        "failure_type": failure_type,
        "source_error_type": error_type or None,
        "note": note,
        "lesson": lesson,
    }


def build_ai_analysis_payload(report: Any) -> dict[str, Any]:
    setup = _as_dict(report, "trade_setup")
    regime = _as_dict(report, "market_regime")
    return {
        "schema_version": "naked-k-ai-assistant-v1",
        "signal_boundary": {
            "signal_source": "deterministic_price_action_engine",
            "llm_role": "explain_review_challenge_only",
            "allowed": ["explain_market_behavior", "summarize_plan", "attribute_failure", "draft_journal_notes"],
            "forbidden": ["change_action", "invent_entry", "invent_stop", "invent_target", "override_risk_plan"],
        },
        "engine_plan": {
            "ticker": _value(report, "ticker"),
            "name": _value(report, "name"),
            "action": _value(report, "action"),
            "signal_state": _value(report, "signal_state"),
            "entry_trigger": _value(report, "entry_trigger"),
            "stop_loss": _value(report, "stop_loss"),
            "target_price": _value(report, "target_price"),
            "reward_to_risk": _value(report, "reward_to_risk"),
            "position_size": _value(report, "position_size"),
        },
        "market_context": {
            "price_action": _as_dict(report, "price_action"),
            "market_structure": _as_dict(report, "market_structure"),
            "market_regime": regime,
            "timeframe_context": _as_dict(report, "timeframe_context"),
            "price_zones": _as_dict(report, "price_zones"),
            "candle_context": _value(report, "candle_context", []),
        },
        "setup_context": {
            "setup_key": setup.get("key"),
            "setup_name": setup.get("name"),
            "setup_direction": setup.get("direction"),
            "regime": regime.get("state"),
        },
        "risk_context": _as_dict(report, "risk_plan"),
        "trader_brief": _as_dict(report, "trader_brief"),
    }


def build_ai_trading_assistant(
    report: Any,
    historical_samples: list[dict[str, Any]] | None = None,
    min_samples: int = 10,
) -> dict[str, Any]:
    payload = build_ai_analysis_payload(report)
    setup_key = str(payload["setup_context"].get("setup_key") or "")
    regime = payload["setup_context"].get("regime")
    calibrated_edge = calibrate_historical_edge(
        historical_samples or [],
        setup_key=setup_key or None,
        regime=str(regime) if regime is not None else None,
        min_samples=min_samples,
    )
    attribution = attribute_plan_outcome(report)
    return {
        **payload,
        "calibrated_edge": calibrated_edge,
        "failure_attribution": attribution,
        "assistant_notes": [
            "AI只做解释、复盘和质疑，不改变确定性引擎给出的动作、触发位、止损位和风控计划",
            (
                f"样本校准胜率：{calibrated_edge['win_rate']}%，平均R：{calibrated_edge['average_r']}"
                if calibrated_edge["confidence_source"] == "historical_samples"
                else "样本校准胜率：样本不足，暂不输出概率化胜率"
            ),
            attribution["lesson"],
        ],
    }


def format_ai_assistant_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "暂无"
    edge = payload.get("calibrated_edge") or {}
    notes = payload.get("assistant_notes") or []
    edge_text = (
        f"历史样本{edge.get('sample_count')}，胜率{edge.get('win_rate')}%，平均R {edge.get('average_r')}"
        if edge.get("confidence_source") == "historical_samples"
        else "历史样本不足，不输出概率化胜率"
    )
    llm = payload.get("llm_commentary") or {}
    llm_text = ""
    if llm.get("status") == "ok":
        parsed = llm.get("parsed") or {}
        journal_note = parsed.get("journal_note") or parsed.get("plan_review") or str(llm.get("content", ""))[:120]
        llm_text = f"；LLM复盘：{journal_note}"
    elif llm.get("status") == "error":
        llm_text = f"；LLM复盘失败：{llm.get('error_type')}"
    return f"边界：AI只解释不改信号；校准：{edge_text}；复盘：{' / '.join(str(item) for item in notes[:2])}{llm_text}"
