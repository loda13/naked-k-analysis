#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import re
from collections.abc import Callable
from dataclasses import asdict
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pandas as pd

import naked_k_audit
import naked_k_ai
import naked_k_config
import naked_k_context
import naked_k_interpreter
import naked_k_llm
import naked_k_news
import naked_k_news_llm
import naked_k_planner
import naked_k_portfolio
import naked_k_synthesis
import naked_k_timeframes
from naked_k_trade import (
    BEARISH_ACTIONS,
    BEARISH_PATTERN_KEYS,
    BULLISH_ACTIONS,
    BULLISH_PATTERN_KEYS,
    MIN_ACTIONABLE_REWARD_TO_RISK,
    WATCH_PATTERN_KEYS,
    analyze_price_action_context,
    analyze_pullback_context,
    analyze_trend_structure,
    build_breakout_trigger,
    build_intraday_status,
    build_invalidation_level,
    build_position_guidance,
    build_signal_state,
    build_trade_metrics,
    build_volatility_buffer_ratio,
    calculate_atr,
    classify_latest_candle,
    classify_patterns,
    classify_volatility_state,
    detect_price_action_patterns,
    downgrade_low_reward_setup,
    find_price_levels,
    format_market_regime_summary,
    format_market_structure_summary,
    format_price_action_summary,
    format_price_zones_summary,
    format_risk_plan_summary,
    format_trade_setup_summary,
    resolve_weekly_context,
    review_previous_call,
)
import westock_wrapper as yf

DEFAULT_TICKERS = [
    ("腾讯", "0700.HK"),
    ("小米", "1810.HK"),
    ("PDD", "PDD"),
    ("泡泡玛特", "9992.HK"),
]
DEFAULT_JOURNAL_PATH = Path("reports/naked_k_journal.jsonl")
DEFAULT_REPORT_PATH = Path("reports/naked_k_latest.md")
DEFAULT_AUDIT_PATH = Path("reports/naked_k_audit.jsonl")

InstrumentReport = naked_k_planner.InstrumentReport


def classify_market(ticker: str) -> str:
    symbol = ticker.upper()
    if symbol.endswith(".HK"):
        return "hk"
    if symbol.endswith((".SS", ".SZ")):
        return "cn"
    return "us"


def market_timezone(market: str) -> ZoneInfo:
    return ZoneInfo("America/New_York") if market == "us" else ZoneInfo("Asia/Shanghai")


def market_close_hour(market: str) -> int:
    return 16


def trim_to_closed_bars(
    frame: pd.DataFrame,
    market: str,
    interval: str,
    now: pd.Timestamp | None = None,
) -> pd.DataFrame:
    if frame.empty:
        return frame

    tz = market_timezone(market)
    clock = now or pd.Timestamp.now(tz=tz)
    if clock.tzinfo is None:
        clock = clock.tz_localize(tz)
    else:
        clock = clock.tz_convert(tz)

    last_ts = pd.Timestamp(frame.index[-1])
    last_date = last_ts.date()
    current_date = clock.date()

    if interval == "1d" and last_date == current_date and clock.hour < market_close_hour(market):
        return frame.iloc[:-1]

    if interval == "1wk":
        current_week = clock.isocalendar()[:2]
        last_week = last_ts.isocalendar()[:2]
        before_weekly_close = clock.weekday() < 4 or (clock.weekday() == 4 and clock.hour < market_close_hour(market))
        if last_week == current_week and before_weekly_close:
            return frame.iloc[:-1]

    if interval == "1mo" and (last_ts.year, last_ts.month) == (clock.year, clock.month):
        return frame.iloc[:-1]

    if interval == "1h" and len(frame) > 1:
        latest_volume = pd.to_numeric(pd.Series([frame.iloc[-1].get("Volume")]), errors="coerce").iloc[0]
        if pd.notna(latest_volume) and float(latest_volume) <= 0:
            return frame.iloc[:-1]

    return frame


def load_ohlcv(ticker: str, interval: str, period: str) -> pd.DataFrame:
    frame = yf.download(ticker, period=period, interval=interval, progress=False)
    if frame is None or getattr(frame, "empty", True):
        raise ValueError(f"{ticker} {interval} 无可用数据")
    frame = frame[["Open", "High", "Low", "Close", "Volume"]].dropna().copy()
    frame.index = pd.to_datetime(frame.index)
    frame = frame.sort_index()
    frame = trim_to_closed_bars(frame, market=classify_market(ticker), interval=interval)
    if frame.empty:
        raise ValueError(f"{ticker} {interval} 只有未收盘K线")
    return frame


def build_trade_plan(
    name: str,
    ticker: str,
    daily: pd.DataFrame,
    weekly: pd.DataFrame,
    previous: dict[str, Any] | None,
    intraday: pd.DataFrame | None = None,
    monthly: pd.DataFrame | None = None,
    config: naked_k_config.TradingConfig | None = None,
) -> InstrumentReport:
    return naked_k_planner.build_trade_plan(
        name,
        ticker,
        daily,
        weekly,
        previous,
        intraday=intraday,
        monthly=monthly,
        config=config,
    )


def load_journal(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def latest_journal_entry(
    rows: list[dict[str, Any]],
    ticker: str,
    current_daily_date: str | None = None,
) -> dict[str, Any] | None:
    matches = [row for row in rows if row.get("ticker") == ticker]
    if current_daily_date is not None:
        current_ts = pd.Timestamp(current_daily_date)
        matches = [
            row
            for row in matches
            if (
                (row.get("latest_k_dates") or {}).get("daily")
                and pd.Timestamp((row.get("latest_k_dates") or {}).get("daily")) < current_ts
            )
        ]
    return matches[-1] if matches else None


NEWS_CONCLUSION_FIELDS = (
    "technical_conclusion",
    "news_analysis",
    "combined_conclusion",
)


def serialize_report(
    report: InstrumentReport,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    serialized = asdict(report)
    result = dict(serialized if payload is None else payload)
    if any(serialized[field] for field in NEWS_CONCLUSION_FIELDS):
        result.update({field: serialized[field] for field in NEWS_CONCLUSION_FIELDS})
    else:
        for field in NEWS_CONCLUSION_FIELDS:
            result.pop(field, None)
    return result


def append_journal(path: Path, run_date: str, report: InstrumentReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = serialize_report(report, {
        "run_date": run_date,
        "name": report.name,
        "ticker": report.ticker,
        "action": report.action,
        "entry_trigger": report.entry_trigger,
        "stop_loss": report.stop_loss,
        "target_price": report.target_price,
        "risk_per_share": report.risk_per_share,
        "reward_to_risk": report.reward_to_risk,
        "signal_state": report.signal_state,
        "resistance": report.resistance,
        "support": report.support,
        "position_size": report.position_size,
        "daily_patterns": report.daily_patterns,
        "weekly_patterns": report.weekly_patterns,
        "weekly_context": report.weekly_context,
        "data_sources": report.data_sources,
        "latest_k_dates": report.latest_k_dates,
        "latest_closes": report.latest_closes,
        "review": report.review,
        "improvement": report.improvement,
        "intraday_status": report.intraday_status,
        "price_action": report.price_action,
        "market_structure": report.market_structure,
        "market_regime": report.market_regime,
        "risk_plan": report.risk_plan,
        "trade_setup": report.trade_setup,
        "price_zones": report.price_zones,
        "timeframe_context": report.timeframe_context,
        "trader_brief": report.trader_brief,
        "candle_context": report.candle_context,
        "ai_assistant": report.ai_assistant,
    })
    rows = load_journal(path)
    match_key = (report.ticker, report.latest_k_dates["daily"])
    rows = [
        row
        for row in rows
        if (row.get("ticker"), (row.get("latest_k_dates") or {}).get("daily")) != match_key
    ]
    rows.append(payload)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_data_audit_payload(ticker: str, interval: str, period: str, frame: pd.DataFrame) -> dict[str, Any]:
    latest = pd.Timestamp(frame.index[-1]).isoformat() if not frame.empty else None
    return {
        "ticker": ticker,
        "interval": interval,
        "period": period,
        "rows": len(frame),
        "latest": latest,
        "source": str(frame.attrs.get("source", "unknown")),
    }


def _single_line(value: Any) -> str:
    return " ".join(str("" if value is None else value).split())


def _markdown_label(value: Any) -> str:
    text = escape(_single_line(value), quote=False)
    return (
        text.replace("\\", "\\\\")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def _safe_http_url(value: Any) -> str:
    url = _single_line(value)
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def _news_error_type(value: Any) -> str:
    if isinstance(value, dict):
        error_type = value.get("error_type")
        return _news_error_type(error_type) if error_type else ""
    text = _single_line(value)
    exception_names = re.findall(r"[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception)", text)
    if exception_names:
        return exception_names[0]
    prefix = text.split(":", 1)[0]
    return prefix if prefix.replace("_", "").isalnum() and " " not in prefix else ""


def _unavailable_news_collection(
    name: str,
    ticker: str,
    *,
    error_type: str,
    lookback_days: int,
) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "name": name,
        "ticker": ticker,
        "as_of": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "window_days": lookback_days,
        "freshness": "unavailable",
        "items": [],
        "source_errors": [error_type] if error_type else [],
    }


def _restore_technical_conclusion(report: InstrumentReport) -> None:
    for field in naked_k_synthesis.TECHNICAL_SNAPSHOT_FIELDS:
        setattr(report, field, copy.deepcopy(report.technical_conclusion[field]))


def _technical_fallback_combined(
    report: InstrumentReport,
    *,
    reason: str,
    deliberation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    technical_action = str(report.technical_conclusion["action"])
    if deliberation:
        combined = {
            "status": "technical_fallback",
            "technical_view": copy.deepcopy(deliberation["technical_view"]),
            "news_view": copy.deepcopy(deliberation["news_view"]),
            "conflict_analysis": _single_line(deliberation["conflict_analysis"]),
            "model_action": str(deliberation["model_action"]),
            "final_action": technical_action,
            "confidence": deliberation["confidence"],
            "decision_reasons": copy.deepcopy(deliberation["decision_reasons"]),
            "risk_flags": copy.deepcopy(deliberation["risk_flags"]),
            "evidence_ids": copy.deepcopy(deliberation["evidence_ids"]),
            "execution_note": _single_line(deliberation["execution_note"]),
        }
    else:
        round1 = report.news_analysis.get("round1")
        round1 = round1 if isinstance(round1, dict) else {}
        combined = {
            "status": "technical_fallback",
            "technical_view": {"action": technical_action, "summary": "保留原始裸K技术结论"},
            "news_view": {
                "direction": _single_line(round1.get("direction")) or "unavailable",
                "summary": _single_line(round1.get("summary")) or "消息面不可用或不足",
            },
            "conflict_analysis": _single_line(reason) or "消息面不可用，保留技术结论",
            "model_action": technical_action,
            "final_action": technical_action,
            "confidence": round1.get("confidence", 0),
            "decision_reasons": ["消息面流程未形成有效综合动作，保留技术动作"],
            "risk_flags": [],
            "evidence_ids": copy.deepcopy(round1.get("evidence_ids", [])),
            "execution_note": "沿用原始裸K执行计划",
        }
    combined.update(
        {
            "execution_side": naked_k_synthesis.side_for_action(technical_action),
            "risk_override_reason": _single_line(reason),
            "price_plan_source": "technical_snapshot",
        }
    )
    report.combined_conclusion = combined
    return combined


def _news_fallback_result(
    collection: dict[str, Any],
    news_config: naked_k_news_llm.AnthropicNewsConfig,
    *,
    status: str,
    error_type: str,
    message: str,
) -> dict[str, Any]:
    return {
        "status": "technical_fallback",
        "news_analysis": {
            "status": status,
            "collection": copy.deepcopy(collection),
            "round1": {"error_type": error_type, "message": message},
            "provider": news_config.provider,
            "model": news_config.model,
        },
        "deliberation": {},
        "fallback_reason": error_type,
    }


_NEWS_AUDIT_FIELDS = {
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


def _log_news_audit(
    audit: naked_k_audit.AuditLogger,
    event_type: str,
    *,
    level: str = "info",
    **payload: Any,
) -> None:
    safe_payload = {
        key: value
        for key, value in payload.items()
        if key in _NEWS_AUDIT_FIELDS and value not in (None, "")
    }
    audit.log(event_type, level=level, **safe_payload)


def _format_news_blocks(report: InstrumentReport) -> list[str]:
    if not any(getattr(report, field) for field in NEWS_CONCLUSION_FIELDS):
        return []

    technical = report.technical_conclusion or {}
    news = report.news_analysis or {}
    combined = report.combined_conclusion or {}
    collection = news.get("collection")
    collection = collection if isinstance(collection, dict) else {}
    round1 = news.get("round1")
    round1 = round1 if isinstance(round1, dict) else {}
    items = collection.get("items")
    items = items if isinstance(items, list) else []

    lines = [
        "### 技术面结论",
        f"- 技术动作：{_single_line(technical.get('action')) or '暂无'}",
        (
            f"- 技术价格计划：触发 {_single_line(technical.get('entry_trigger')) or '暂无'}；"
            f"失效 {_single_line(technical.get('stop_loss')) or '暂无'}；"
            f"目标 {_single_line(technical.get('target_price')) or '暂无'}"
        ),
        "",
        "### 消息面结论",
    ]
    if news.get("status") == "insufficient":
        evidence = round1.get("evidence_ids")
        evidence_text = "、".join(_single_line(item) for item in evidence or []) or "无"
        lines.extend(
            [
                "- 消息面不足：第一轮数据质量不足，综合动作回退技术结论",
                (
                    f"- 方向：{_single_line(round1.get('direction')) or '暂无'}；"
                    f"评分：{_single_line(round1.get('score')) or '暂无'}；"
                    f"置信度：{_single_line(round1.get('confidence')) or '暂无'}"
                ),
                f"- 摘要：{_single_line(round1.get('summary')) or '暂无'}",
                f"- 证据：{evidence_text}",
            ]
        )
    elif round1.get("direction"):
        evidence = round1.get("evidence_ids")
        evidence_text = "、".join(_single_line(item) for item in evidence or []) or "无"
        lines.extend(
            [
                (
                    f"- 方向：{_single_line(round1.get('direction'))}；"
                    f"评分：{_single_line(round1.get('score'))}；"
                    f"置信度：{_single_line(round1.get('confidence'))}"
                ),
                f"- 摘要：{_single_line(round1.get('summary')) or '暂无'}",
                f"- 证据：{evidence_text}",
            ]
        )
    else:
        unavailable_type = _news_error_type(round1)
        if not unavailable_type:
            source_errors = collection.get("source_errors")
            if isinstance(source_errors, list) and source_errors:
                unavailable_type = _single_line(source_errors[0])
        status_text = "消息面不足" if news.get("status") == "insufficient" else "消息面不可用"
        lines.append(f"- {status_text}：{unavailable_type or '未取得可验证消息证据'}")

    lines.extend(
        [
            "",
            "### 技术与消息冲突/一致性",
            f"- 分析：{_single_line(combined.get('conflict_analysis')) or '消息面未形成有效结论，沿用技术判断'}",
            "",
            "### 综合结论",
            f"- 模型动作：{_single_line(combined.get('model_action')) or _single_line(technical.get('action'))}",
            f"- 风险保护后最终动作：{_single_line(combined.get('final_action')) or report.action}",
            f"- 决策理由：{'；'.join(_single_line(item) for item in combined.get('decision_reasons', [])) or '沿用技术结论'}",
            f"- 覆盖原因：{_single_line(combined.get('risk_override_reason')) or '无'}",
            "",
            "### 消息来源",
        ]
    )
    if items:
        for index, item in enumerate(items, start=1):
            title = _markdown_label(item.get("title")) or "未命名消息"
            publisher = _markdown_label(item.get("publisher")) or "未知发布方"
            published_at = _markdown_label(item.get("published_at")) or "日期未知"
            url = _safe_http_url(item.get("url"))
            source = f"[{title}]({url})" if url else title
            lines.append(f"{index}. {source} — {publisher}；{published_at}")
    else:
        lines.append("- 无可用消息来源。")
    lines.append("")
    return lines


def format_report(
    run_date: str,
    reports: list[InstrumentReport],
    journal_path: Path,
    config: naked_k_config.TradingConfig | None = None,
) -> str:
    sections = [
        f"# 裸K收盘报告",
        f"生成日期：{run_date}",
        f"日志：{journal_path}",
        "",
    ]
    for report in reports:
        target_text = str(report.target_price) if report.target_price is not None else "暂无"
        reward_to_risk_text = f"{report.reward_to_risk}R" if report.reward_to_risk is not None else "暂无"
        intraday = report.intraday_status or {"status": "无盘中数据", "note": "未获取到1h盘中K线"}
        intraday_detail = []
        if intraday.get("latest_time"):
            intraday_detail.append(str(intraday["latest_time"]))
        if intraday.get("latest_close") is not None:
            intraday_detail.append(f"最新{intraday['latest_close']}")
        if intraday.get("source"):
            intraday_detail.append(f"source={intraday['source']}")
        intraday_note = str(intraday.get("note") or "")
        intraday_line = f"{intraday.get('status', '无盘中数据')}"
        if intraday_detail:
            intraday_line += f"（{'，'.join(intraday_detail)}）"
        if intraday_note:
            intraday_line += f"；{intraday_note}"
        sections.extend(
            [
                f"## {report.name} {report.ticker}",
                f"- 数据源：日线 `{report.data_sources['daily']}`，周线 `{report.data_sources['weekly']}`",
                f"- 最新K线：日线 {report.latest_k_dates['daily']} 收 {report.latest_closes['daily']}；周线 {report.latest_k_dates['weekly']} 收 {report.latest_closes['weekly']}",
                f"- 当前动作：{report.action}",
                f"- 信号状态：{report.signal_state}",
                f"- 入场触发位：{report.entry_trigger}",
                f"- 失效/止损位：{report.stop_loss}",
                f"- 第一目标位：{target_text}",
                f"- 单股风险：{report.risk_per_share}",
                f"- 目标盈亏比：{reward_to_risk_text}",
                f"- 盘中状态：{intraday_line}",
                f"- 多周期框架：{naked_k_timeframes.format_timeframe_context(report.timeframe_context)}",
                f"- 交易员简报：{naked_k_interpreter.format_trader_brief(report.trader_brief)}",
                f"- 裸K解读：{format_price_action_summary(report.price_action)}",
                f"- 市场结构：{format_market_structure_summary(report.market_structure)}",
                f"- 市场状态：{format_market_regime_summary(report.market_regime)}",
                f"- 交易剧本：{format_trade_setup_summary(report.trade_setup)}",
                f"- 关键价格区域：{format_price_zones_summary(report.price_zones)}",
                f"- K线行为上下文：{naked_k_context.format_candle_context_summary(report.candle_context)}",
                f"- AI交易助手：{naked_k_ai.format_ai_assistant_summary(report.ai_assistant)}",
                f"- 风险计划：{format_risk_plan_summary(report.risk_plan)}",
                f"- 上方压力：{report.resistance}",
                f"- 下方支撑：{report.support}",
                f"- 仓位建议：{report.position_size}",
                f"- 理由：{report.rationale}",
                f"- 复盘：{report.review['status']}；错误类型：{report.review['error_type'] or '无'}；备注：{report.review['note']}",
                f"- 持续优化：{report.improvement}",
                "",
            ]
        )
        sections.extend(_format_news_blocks(report))

    ranked = sorted(
        reports,
        key=lambda item: {"买入": 0, "小仓试错": 1, "观望": 2, "减仓": 3, "回避": 4}.get(item.action, 9),
    )
    best_trial = next((item for item in ranked if item.action in {"买入", "小仓试错"}), None)
    best_trial_text = (
        f"{best_trial.name}（{best_trial.action}）"
        if best_trial is not None
        else "暂无（无满足触发条件标的）"
    )
    portfolio_exposure = naked_k_portfolio.evaluate_portfolio_exposure(
        reports,
        config=config.portfolio if config is not None else None,
    )
    sections.extend(
        [
            "## 今日结论",
            f"- 最值得试错：{best_trial_text}",
            f"- 继续观察：{next((item.name for item in ranked if item.action == '观望'), ranked[1].name if len(ranked) > 1 else ranked[0].name)}",
            f"- 需要回避：{next((item.name for item in ranked if item.action in {'回避', '减仓'}), ranked[-1].name)}",
            f"- 组合风险：{naked_k_portfolio.format_portfolio_exposure(portfolio_exposure)}",
            "",
            "不构成投资建议；以上仅作交易辅助。",
        ]
    )
    return "\n".join(sections)


def _capture_technical_fields(report: InstrumentReport) -> dict[str, Any]:
    return copy.deepcopy(
        {
            field: getattr(report, field)
            for field in naked_k_synthesis.TECHNICAL_SNAPSHOT_FIELDS
        }
    )


def _recover_news_branch(
    report: InstrumentReport,
    technical_snapshot: dict[str, Any],
    *,
    error_type: str,
    news_config: naked_k_news_llm.AnthropicNewsConfig,
    news_lookback_days: int,
    audit: naked_k_audit.AuditLogger,
    emitted_events: set[str],
) -> None:
    report.technical_conclusion = copy.deepcopy(technical_snapshot)
    _restore_technical_conclusion(report)
    collection = _unavailable_news_collection(
        report.name,
        report.ticker,
        error_type=error_type,
        lookback_days=news_lookback_days,
    )
    fallback = _news_fallback_result(
        collection,
        news_config,
        status="error",
        error_type=error_type,
        message="News integration branch failed",
    )
    report.news_analysis = fallback["news_analysis"]
    combined = _technical_fallback_combined(report, reason=error_type)
    event_payloads = {
        "news_collected": {
            "status": "unavailable",
            "item_count": 0,
            "error_type": error_type,
        },
        "news_assessed": {
            "status": "error",
            "item_count": 0,
            "error_type": error_type,
        },
        "decision_deliberated": {
            "status": combined["status"],
            "item_count": 0,
            "model_action": combined["model_action"],
            "final_action": combined["final_action"],
            "error_type": error_type,
        },
    }
    for event_type, payload in event_payloads.items():
        if event_type in emitted_events:
            continue
        _log_news_audit(
            audit,
            event_type,
            level="warning",
            ticker=report.ticker,
            name=report.name,
            provider=news_config.provider,
            model=news_config.model,
            **payload,
        )
        emitted_events.add(event_type)


def _run_news_for_report(
    report: InstrumentReport,
    daily: pd.DataFrame,
    intraday: pd.DataFrame | None,
    *,
    config: naked_k_config.TradingConfig | None,
    news_config: naked_k_news_llm.AnthropicNewsConfig,
    news_post: naked_k_news_llm.PostCallable | None,
    news_get: Callable[..., Any] | None,
    news_search_factory: naked_k_news.SearchFactory | None,
    news_lookback_days: int,
    news_max_items: int,
    news_bootstrap_error: dict[str, str] | None,
    audit: naked_k_audit.AuditLogger,
    emitted_events: set[str],
) -> None:
    report.technical_conclusion = naked_k_synthesis.snapshot_technical_conclusion(report)
    bootstrap_error_type = _news_error_type(news_bootstrap_error)
    collection_error_type = bootstrap_error_type

    if bootstrap_error_type:
        collection = _unavailable_news_collection(
            report.name,
            report.ticker,
            error_type=bootstrap_error_type,
            lookback_days=news_lookback_days,
        )
    else:
        try:
            collection = naked_k_news.collect_news(
                report.name,
                report.ticker,
                lookback_days=news_lookback_days,
                max_items=news_max_items,
                search_factory=news_search_factory,
                get=news_get,
            )
            if not isinstance(collection, dict):
                raise TypeError("news collection must be a dictionary")
            source_errors = collection.get("source_errors")
            if collection.get("status") == "unavailable" and isinstance(source_errors, list) and source_errors:
                collection_error_type = _single_line(source_errors[0])
        except Exception as exc:
            collection_error_type = type(exc).__name__
            collection = _unavailable_news_collection(
                report.name,
                report.ticker,
                error_type=collection_error_type,
                lookback_days=news_lookback_days,
            )

    items = collection.get("items")
    item_count = len(items) if isinstance(items, list) else 0
    _log_news_audit(
        audit,
        "news_collected",
        level="warning" if collection.get("status") != "ok" else "info",
        ticker=report.ticker,
        name=report.name,
        provider=news_config.provider,
        model=news_config.model,
        status=collection.get("status"),
        item_count=item_count,
        error_type=collection_error_type,
    )
    emitted_events.add("news_collected")

    risk_context_error_type = ""
    try:
        risk_context = naked_k_synthesis.build_risk_context(report.technical_conclusion, config)
    except Exception as exc:
        risk_context_error_type = type(exc).__name__
        risk_context = {}

    if risk_context_error_type:
        result = _news_fallback_result(
            collection,
            news_config,
            status="error",
            error_type=risk_context_error_type,
            message="News risk context unavailable",
        )
    elif bootstrap_error_type or (
        collection_error_type and collection.get("status") == "unavailable"
    ):
        result = _news_fallback_result(
            collection,
            news_config,
            status="unavailable",
            error_type=collection_error_type or "NewsUnavailable",
            message="News analysis unavailable",
        )
    else:
        try:
            result = naked_k_news_llm.run_two_pass_deliberation(
                name=report.name,
                ticker=report.ticker,
                collection=collection,
                technical_snapshot=report.technical_conclusion,
                risk_context=risk_context,
                config=news_config,
                post=news_post,
            )
            if not isinstance(result, dict):
                raise TypeError("news deliberation result must be a dictionary")
        except Exception as exc:
            error_type = type(exc).__name__
            result = _news_fallback_result(
                collection,
                news_config,
                status="error",
                error_type=error_type,
                message="News deliberation stage failed",
            )

    news_analysis = result.get("news_analysis")
    report.news_analysis = copy.deepcopy(news_analysis) if isinstance(news_analysis, dict) else {
        "status": "error",
        "collection": copy.deepcopy(collection),
        "round1": {"error_type": "InvalidNewsResult", "message": "News analysis unavailable"},
        "provider": news_config.provider,
        "model": news_config.model,
    }
    assessment_error_type = _news_error_type(report.news_analysis.get("round1"))
    _log_news_audit(
        audit,
        "news_assessed",
        level="warning" if report.news_analysis.get("status") != "ok" else "info",
        ticker=report.ticker,
        name=report.name,
        provider=news_config.provider,
        model=news_config.model,
        status=report.news_analysis.get("status"),
        item_count=item_count,
        error_type=assessment_error_type,
    )
    emitted_events.add("news_assessed")

    deliberation = result.get("deliberation")
    valid_deliberation = result.get("status") == "ok" and isinstance(deliberation, dict) and bool(deliberation)
    decision_error_type = ""
    if valid_deliberation:
        try:
            combined = naked_k_synthesis.apply_deliberation(
                report,
                daily,
                deliberation,
                intraday=intraday,
                config=config,
            )
            if combined.get("status") != "ok":
                decision_error_type = (
                    _news_error_type(combined.get("risk_override_reason"))
                    or "SynthesisError"
                )
                combined["risk_override_reason"] = (
                    "确定性价格计划重建失败，已安全回退技术结论"
                    f"（{decision_error_type}）"
                )
        except Exception as exc:
            decision_error_type = type(exc).__name__
            _restore_technical_conclusion(report)
            combined = _technical_fallback_combined(
                report,
                reason=f"综合执行失败，已回退技术结论（{decision_error_type}）",
                deliberation=deliberation,
            )
    else:
        fallback_reason = _single_line(result.get("fallback_reason")) or "消息面不可用或不足"
        decision_error_type = _news_error_type(fallback_reason)
        _restore_technical_conclusion(report)
        combined = _technical_fallback_combined(report, reason=fallback_reason)

    _log_news_audit(
        audit,
        "decision_deliberated",
        level="warning" if combined.get("status") != "ok" else "info",
        ticker=report.ticker,
        name=report.name,
        provider=news_config.provider,
        model=news_config.model,
        status=combined.get("status"),
        item_count=item_count,
        model_action=combined.get("model_action"),
        final_action=combined.get("final_action"),
        error_type=decision_error_type,
    )
    emitted_events.add("decision_deliberated")


def run_analysis(
    tickers: list[tuple[str, str]],
    journal_path: Path,
    config: naked_k_config.TradingConfig | None = None,
    audit_path: Path | None = None,
    llm_config: naked_k_llm.LLMConfig | None = None,
    llm_post: naked_k_llm.PostCallable | None = None,
    news_config: naked_k_news_llm.AnthropicNewsConfig | None = None,
    news_post: naked_k_news_llm.PostCallable | None = None,
    news_get: Callable[..., Any] | None = None,
    news_search_factory: naked_k_news.SearchFactory | None = None,
    news_lookback_days: int = 7,
    news_max_items: int = 12,
    news_bootstrap_error: dict[str, str] | None = None,
) -> tuple[str, list[InstrumentReport]]:
    audit = naked_k_audit.AuditLogger(audit_path)
    journal_rows = load_journal(journal_path)
    reports: list[InstrumentReport] = []
    news_enabled = bool(news_config is not None and news_config.enabled)
    daily_by_ticker: dict[str, pd.DataFrame] = {}
    intraday_by_ticker: dict[str, pd.DataFrame | None] = {}
    run_date = pd.Timestamp.now(tz="Asia/Shanghai").strftime("%Y-%m-%d %H:%M:%S %Z")
    audit.info("run_started", ticker_count=len(tickers), journal_path=journal_path, run_date=run_date)

    for name, ticker in tickers:
        try:
            daily = load_ohlcv(ticker, interval="1d", period="18mo")
            audit.info("data_loaded", **build_data_audit_payload(ticker, "1d", "18mo", daily))
            weekly = load_ohlcv(ticker, interval="1wk", period="5y")
            audit.info("data_loaded", **build_data_audit_payload(ticker, "1wk", "5y", weekly))
        except Exception as exc:
            audit.error(
                "run_failed",
                ticker=ticker,
                name=name,
                stage="required_data_load",
                error_type=exc.__class__.__name__,
                error=str(exc),
            )
            raise
        try:
            monthly = load_ohlcv(ticker, interval="1mo", period="10y")
            audit.info("data_loaded", **build_data_audit_payload(ticker, "1mo", "10y", monthly))
        except Exception as exc:
            audit.warning(
                "data_unavailable",
                ticker=ticker,
                interval="1mo",
                period="10y",
                error_type=exc.__class__.__name__,
                error=str(exc),
            )
            monthly = None
        try:
            intraday = load_ohlcv(ticker, interval="1h", period="5d")
            audit.info("data_loaded", **build_data_audit_payload(ticker, "1h", "5d", intraday))
        except Exception as exc:
            audit.warning(
                "data_unavailable",
                ticker=ticker,
                interval="1h",
                period="5d",
                error_type=exc.__class__.__name__,
                error=str(exc),
            )
            intraday = None
        previous = latest_journal_entry(
            journal_rows,
            ticker,
            current_daily_date=daily.index[-1].strftime("%Y-%m-%d"),
        )
        report = build_trade_plan(
            name,
            ticker,
            daily,
            weekly,
            previous,
            intraday=intraday,
            monthly=monthly,
            config=config,
        )
        if news_enabled and news_config is not None:
            technical_snapshot = _capture_technical_fields(report)
            emitted_news_events: set[str] = set()
            try:
                _run_news_for_report(
                    report,
                    daily,
                    intraday,
                    config=config,
                    news_config=news_config,
                    news_post=news_post,
                    news_get=news_get,
                    news_search_factory=news_search_factory,
                    news_lookback_days=news_lookback_days,
                    news_max_items=news_max_items,
                    news_bootstrap_error=news_bootstrap_error,
                    audit=audit,
                    emitted_events=emitted_news_events,
                )
            except Exception as exc:
                _recover_news_branch(
                    report,
                    technical_snapshot,
                    error_type=type(exc).__name__,
                    news_config=news_config,
                    news_lookback_days=news_lookback_days,
                    audit=audit,
                    emitted_events=emitted_news_events,
                )
            daily_by_ticker[ticker] = daily
            intraday_by_ticker[ticker] = intraday
        if llm_config is not None and llm_config.enabled:
            commentary = naked_k_llm.safe_generate_llm_commentary(
                report.ai_assistant,
                config=llm_config,
                post=llm_post,
            )
            report.ai_assistant["llm_commentary"] = commentary
            audit_level = "info" if commentary.get("status") == "ok" else "warning"
            audit.log(
                "llm_commentary_generated",
                level=audit_level,
                ticker=ticker,
                name=name,
                status=commentary.get("status"),
                provider=commentary.get("provider"),
                model=commentary.get("model"),
                error_type=commentary.get("error_type"),
            )
        if not news_enabled:
            append_journal(journal_path, run_date, report)
        reports.append(report)
        audit.info(
            "plan_generated",
            ticker=ticker,
            name=name,
            action=report.action,
            signal_state=report.signal_state,
            setup_key=(report.trade_setup or {}).get("key"),
            risk_status=(report.risk_plan or {}).get("status"),
            timeframe_alignment=(report.timeframe_context or {}).get("alignment"),
            reward_to_risk=report.reward_to_risk,
        )

    if news_enabled and news_config is not None:
        pre_guard_reports = copy.deepcopy(reports)
        try:
            naked_k_synthesis.apply_portfolio_guardrails(
                reports,
                daily_by_ticker,
                intraday_by_ticker=intraday_by_ticker,
                config=config,
            )
        except Exception as exc:
            reports = pre_guard_reports
            audit.warning("portfolio_guard_failed", error_type=type(exc).__name__)

        for report in reports:
            combined = report.combined_conclusion or {}
            _log_news_audit(
                audit,
                "signal_synthesized",
                level="warning" if combined.get("status") != "ok" else "info",
                ticker=report.ticker,
                name=report.name,
                provider=news_config.provider,
                model=news_config.model,
                status=combined.get("status"),
                model_action=combined.get("model_action"),
                final_action=report.action,
                override_reason=combined.get("risk_override_reason"),
            )
            append_journal(journal_path, run_date, report)

    portfolio_exposure = naked_k_portfolio.evaluate_portfolio_exposure(
        reports,
        config=config.portfolio if config is not None else None,
    )
    portfolio_level = "warning" if portfolio_exposure.get("status") == "over_limit" else "info"
    audit.log("portfolio_exposure", level=portfolio_level, **portfolio_exposure)
    audit.info("run_completed", report_count=len(reports), actions=[report.action for report in reports])
    return format_report(run_date, reports, journal_path, config=config), reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成固定标的的裸K收盘报告")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--journal-path", default=str(DEFAULT_JOURNAL_PATH), help="复盘日志路径")
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH), help="Markdown 报告输出路径")
    parser.add_argument("--config-path", default="", help="JSON 参数配置路径")
    parser.add_argument("--audit-path", default=str(DEFAULT_AUDIT_PATH), help="结构化运行审计 JSONL 路径")
    parser.add_argument("--llm", action="store_true", help="启用 OpenAI-compatible LLM 复盘增强")
    parser.add_argument("--llm-base-url", default="", help="OpenAI-compatible base URL；也可用 LLM_BASE_URL/NAKED_K_LLM_BASE_URL")
    parser.add_argument("--llm-model", default="", help="LLM 模型名；也可用 LLM_MODEL/NAKED_K_LLM_MODEL")
    parser.add_argument("--news", action="store_true", help="启用公开消息面和两轮综合斟酌")
    parser.add_argument("--news-model", default="", help="Anthropic-compatible 消息模型；也可用 NAKED_K_NEWS_MODEL/ANTHROPIC_MODEL")
    parser.add_argument("--news-lookback-days", type=int, default=7, help="消息主窗口自然日数")
    parser.add_argument("--news-max-items", type=int, default=12, help="每个标的送入模型的最大去重消息数")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.news_lookback_days <= 0 or args.news_max_items <= 0:
        print("news lookback days and max items must be positive")
        return 2
    journal_path = Path(args.journal_path)
    report_path = Path(args.report_path)
    audit_path = Path(args.audit_path) if args.audit_path else None
    config = naked_k_config.load_trading_config(args.config_path or None)
    llm_config = naked_k_llm.load_llm_config(
        enabled=args.llm,
        base_url=args.llm_base_url or None,
        model=args.llm_model or None,
    )
    if args.llm:
        naked_k_llm.validate_llm_config(llm_config)
    news_config: naked_k_news_llm.AnthropicNewsConfig | None = None
    news_bootstrap_error: dict[str, str] | None = None
    if args.news:
        try:
            news_config = naked_k_news_llm.load_news_config(
                enabled=True,
                model=args.news_model or None,
            )
            if news_config.model:
                naked_k_news_llm.validate_news_config(news_config)
            else:
                news_config = naked_k_news_llm.resolve_news_model(news_config)
        except naked_k_news_llm.NewsModelSelectionRequired as exc:
            print("\n".join(exc.model_ids))
            return 2
        except Exception as exc:
            if news_config is None:
                news_config = naked_k_news_llm.AnthropicNewsConfig(
                    enabled=True,
                    model=args.news_model,
                )
            news_bootstrap_error = {
                "error_type": type(exc).__name__,
                "message": "News configuration or model discovery failed",
            }
    report_text, reports = run_analysis(
        DEFAULT_TICKERS,
        journal_path,
        config=config,
        audit_path=audit_path,
        llm_config=llm_config,
        news_config=news_config,
        news_lookback_days=args.news_lookback_days,
        news_max_items=args.news_max_items,
        news_bootstrap_error=news_bootstrap_error,
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")

    if args.json:
        payload = {
            "report": report_text,
            "items": [serialize_report(item) for item in reports],
            "report_path": str(report_path),
            "audit_path": str(audit_path) if audit_path is not None else None,
            "llm": naked_k_llm.redact_llm_config(llm_config),
        }
        if news_config is not None and news_config.enabled:
            payload["news"] = naked_k_news_llm.redact_news_config(news_config)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(report_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
