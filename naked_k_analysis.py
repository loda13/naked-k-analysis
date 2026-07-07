#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

import naked_k_audit
import naked_k_ai
import naked_k_config
import naked_k_context
import naked_k_interpreter
import naked_k_llm
import naked_k_planner
import naked_k_portfolio
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


def append_journal(path: Path, run_date: str, report: InstrumentReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
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
    }
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


def run_analysis(
    tickers: list[tuple[str, str]],
    journal_path: Path,
    config: naked_k_config.TradingConfig | None = None,
    audit_path: Path | None = None,
    llm_config: naked_k_llm.LLMConfig | None = None,
    llm_post: naked_k_llm.PostCallable | None = None,
) -> tuple[str, list[InstrumentReport]]:
    audit = naked_k_audit.AuditLogger(audit_path)
    journal_rows = load_journal(journal_path)
    reports: list[InstrumentReport] = []
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
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
    report_text, reports = run_analysis(
        DEFAULT_TICKERS,
        journal_path,
        config=config,
        audit_path=audit_path,
        llm_config=llm_config,
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")

    if args.json:
        payload = {
            "report": report_text,
            "items": [asdict(item) for item in reports],
            "report_path": str(report_path),
            "audit_path": str(audit_path) if audit_path is not None else None,
            "llm": naked_k_llm.redact_llm_config(llm_config),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(report_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
