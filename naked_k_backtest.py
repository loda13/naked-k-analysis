from __future__ import annotations

import math
import random
from typing import Any

import pandas as pd


LONG_ACTIONS = {"买入", "小仓试错"}
SHORT_ACTIONS = {"减仓", "回避"}
DEFAULT_MARKET_CYCLES = ["trend", "range", "high_volatility", "low_volatility_compression", "bear"]


def build_walk_forward_windows(
    frame: pd.DataFrame,
    train_size: int,
    test_size: int,
    step: int | None = None,
) -> list[dict[str, Any]]:
    if train_size <= 0 or test_size <= 0:
        raise ValueError("train_size and test_size must be positive")
    if frame.empty:
        return []

    step_size = step or test_size
    if step_size <= 0:
        raise ValueError("step must be positive")

    windows: list[dict[str, Any]] = []
    start = 0
    total = len(frame)
    while start + train_size + test_size <= total:
        train_start = start
        train_end = start + train_size
        test_end = train_end + test_size
        train = frame.iloc[train_start:train_end].copy()
        test = frame.iloc[train_end:test_end].copy()
        windows.append(
            {
                "train": train,
                "test": test,
                "train_start": train.index[0],
                "train_end": train.index[-1],
                "test_start": test.index[0],
                "test_end": test.index[-1],
            }
        )
        start += step_size
    return windows


def _clean_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    columns = [column for column in ["Open", "High", "Low", "Close", "Volume"] if column in frame.columns]
    clean = frame[columns].dropna().copy()
    clean.index = pd.to_datetime(clean.index)
    return clean.sort_index()


def _history_until(frame: pd.DataFrame | None, timestamp: pd.Timestamp) -> pd.DataFrame | None:
    if frame is None:
        return None
    clean = _clean_ohlcv(frame)
    if clean.empty:
        return clean
    return clean.loc[clean.index <= timestamp].copy()


def _value(report: Any, field: str, default: Any = None) -> Any:
    if isinstance(report, dict):
        return report.get(field, default)
    return getattr(report, field, default)


def _date_text(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _target_r(report: Any, entry: float, target: float | None, risk: float) -> float | None:
    reward_to_risk = _value(report, "reward_to_risk")
    if reward_to_risk is not None:
        return round(float(reward_to_risk), 2)
    if target is None or risk <= 0:
        return None
    return round(abs(float(target) - entry) / risk, 2)


def _evaluate_report_on_next_bar(report: Any, execution_bar: pd.Series, execution_date: Any) -> dict[str, Any]:
    action = str(_value(report, "action", "观望"))
    entry = float(_value(report, "entry_trigger", 0.0))
    stop = float(_value(report, "stop_loss", 0.0))
    target_value = _value(report, "target_price")
    target = float(target_value) if target_value is not None else None
    risk = float(_value(report, "risk_per_share", 0.0) or abs(entry - stop))
    if risk <= 0 or entry <= 0:
        return {"status": "skipped", "reason": "invalid_risk"}

    high = float(execution_bar["High"])
    low = float(execution_bar["Low"])
    close = float(execution_bar["Close"])
    execution_date_text = _date_text(execution_date)

    if action in LONG_ACTIONS:
        if high < entry:
            return {"status": "skipped", "reason": "not_triggered", "execution_date": execution_date_text}
        if low <= stop:
            return {
                "status": "closed",
                "direction": "long",
                "exit_reason": "stop",
                "exit_price": round(stop, 2),
                "r_multiple": -1.0,
                "execution_date": execution_date_text,
            }
        if target is not None and high >= target:
            return {
                "status": "closed",
                "direction": "long",
                "exit_reason": "target",
                "exit_price": round(target, 2),
                "r_multiple": _target_r(report, entry, target, risk),
                "execution_date": execution_date_text,
            }
        return {
            "status": "closed",
            "direction": "long",
            "exit_reason": "close",
            "exit_price": round(close, 2),
            "r_multiple": round((close - entry) / risk, 2),
            "execution_date": execution_date_text,
        }

    if action in SHORT_ACTIONS:
        if low > entry:
            return {"status": "skipped", "reason": "not_triggered", "execution_date": execution_date_text}
        if high >= stop:
            return {
                "status": "closed",
                "direction": "short",
                "exit_reason": "stop",
                "exit_price": round(stop, 2),
                "r_multiple": -1.0,
                "execution_date": execution_date_text,
            }
        if target is not None and low <= target:
            return {
                "status": "closed",
                "direction": "short",
                "exit_reason": "target",
                "exit_price": round(target, 2),
                "r_multiple": _target_r(report, entry, target, risk),
                "execution_date": execution_date_text,
            }
        return {
            "status": "closed",
            "direction": "short",
            "exit_reason": "close",
            "exit_price": round(close, 2),
            "r_multiple": round((entry - close) / risk, 2),
            "execution_date": execution_date_text,
        }

    return {"status": "skipped", "reason": "non_actionable", "execution_date": execution_date_text}


def run_event_backtest(
    name: str,
    ticker: str,
    daily: pd.DataFrame,
    weekly: pd.DataFrame | None = None,
    monthly: pd.DataFrame | None = None,
    min_history: int = 60,
    plan_builder: Any | None = None,
) -> dict[str, Any]:
    if min_history < 2:
        raise ValueError("min_history must be at least 2")
    clean_daily = _clean_ohlcv(daily)
    if len(clean_daily) <= min_history:
        return {
            "trades": [],
            "skipped": [],
            "metrics": calculate_performance_metrics([]),
            "cycle_validation": evaluate_market_cycle_performance([]),
            "audit": {
                "no_lookahead": True,
                "evaluated_signals": 0,
                "generated_trades": 0,
                "skipped": 0,
            },
        }

    if plan_builder is None:
        import naked_k_planner

        plan_builder = naked_k_planner.build_trade_plan

    trades: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    no_lookahead = True
    evaluated_signals = 0

    for signal_pos in range(min_history - 1, len(clean_daily) - 1):
        signal_history = clean_daily.iloc[: signal_pos + 1].copy()
        signal_date = pd.Timestamp(signal_history.index[-1])
        execution_date = pd.Timestamp(clean_daily.index[signal_pos + 1])
        weekly_history = _history_until(weekly, signal_date) if weekly is not None else signal_history
        monthly_history = _history_until(monthly, signal_date) if monthly is not None else None
        if weekly_history is None or weekly_history.empty:
            weekly_history = signal_history

        report = plan_builder(
            name,
            ticker,
            signal_history,
            weekly_history,
            previous=None,
            intraday=None,
            monthly=monthly_history,
        )
        evaluated_signals += 1
        latest_dates = _value(report, "latest_k_dates", {}) or {}
        latest_daily = latest_dates.get("daily")
        if not signal_date < execution_date:
            no_lookahead = False
        if latest_daily and pd.Timestamp(latest_daily) > signal_date:
            no_lookahead = False

        result = _evaluate_report_on_next_bar(report, clean_daily.iloc[signal_pos + 1], execution_date)
        base = {
            "ticker": ticker,
            "signal_date": _date_text(signal_date),
            "execution_date": _date_text(execution_date),
            "action": _value(report, "action", "观望"),
            "entry_trigger": round(float(_value(report, "entry_trigger", 0.0)), 2),
            "stop_loss": round(float(_value(report, "stop_loss", 0.0)), 2),
            "target_price": _value(report, "target_price"),
            "setup": (_value(report, "trade_setup", {}) or {}).get("key"),
            "regime": (_value(report, "market_regime", {}) or {}).get("state"),
        }
        if result["status"] == "closed":
            trades.append({**base, **result})
        else:
            skipped.append({**base, **result})

    return {
        "trades": trades,
        "skipped": skipped,
        "metrics": calculate_performance_metrics(trades),
        "cycle_validation": evaluate_market_cycle_performance(trades),
        "audit": {
            "no_lookahead": no_lookahead,
            "evaluated_signals": evaluated_signals,
            "generated_trades": len(trades),
            "skipped": len(skipped),
        },
    }


def run_walk_forward_event_backtest(
    name: str,
    ticker: str,
    daily: pd.DataFrame,
    train_size: int,
    test_size: int,
    step: int | None = None,
    weekly: pd.DataFrame | None = None,
    monthly: pd.DataFrame | None = None,
    plan_builder: Any | None = None,
) -> dict[str, Any]:
    clean_daily = _clean_ohlcv(daily)
    windows = build_walk_forward_windows(clean_daily, train_size=train_size, test_size=test_size, step=step)
    window_results: list[dict[str, Any]] = []
    all_trades: list[dict[str, Any]] = []
    all_skipped: list[dict[str, Any]] = []
    no_lookahead = True

    for index, window in enumerate(windows, start=1):
        combined = pd.concat([window["train"], window["test"]]).sort_index()
        test_end = pd.Timestamp(window["test_end"])
        weekly_window = _history_until(weekly, test_end) if weekly is not None else None
        monthly_window = _history_until(monthly, test_end) if monthly is not None else None
        result = run_event_backtest(
            name=name,
            ticker=ticker,
            daily=combined,
            weekly=weekly_window,
            monthly=monthly_window,
            min_history=len(window["train"]),
            plan_builder=plan_builder,
        )
        no_lookahead = no_lookahead and bool(result["audit"]["no_lookahead"])
        all_trades.extend(result["trades"])
        all_skipped.extend(result["skipped"])
        window_results.append(
            {
                "window": index,
                "train_start": _date_text(window["train_start"]),
                "train_end": _date_text(window["train_end"]),
                "test_start": _date_text(window["test_start"]),
                "test_end": _date_text(window["test_end"]),
                "trades": result["trades"],
                "skipped": result["skipped"],
                "metrics": result["metrics"],
                "cycle_validation": result["cycle_validation"],
                "audit": result["audit"],
            }
        )

    return {
        "windows": window_results,
        "trades": all_trades,
        "skipped": all_skipped,
        "metrics": calculate_performance_metrics(all_trades),
        "cycle_validation": evaluate_market_cycle_performance(all_trades),
        "audit": {
            "no_lookahead": no_lookahead,
            "window_count": len(window_results),
            "generated_trades": len(all_trades),
            "skipped": len(all_skipped),
        },
    }


def _r_multiples(trades: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for trade in trades:
        if "r_multiple" not in trade:
            continue
        values.append(float(trade["r_multiple"]))
    return values


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return max_drawdown


def _sharpe(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    average = sum(values) / len(values)
    variance = sum((value - average) ** 2 for value in values) / (len(values) - 1)
    stddev = math.sqrt(variance)
    if stddev <= 0:
        return None
    return average / stddev * math.sqrt(len(values))


def calculate_performance_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    values = _r_multiples(trades)
    trade_count = len(values)
    if trade_count == 0:
        return {
            "trade_count": 0,
            "total_r": 0.0,
            "win_rate": 0.0,
            "profit_factor": None,
            "average_r": 0.0,
            "average_win_r": 0.0,
            "average_loss_r": 0.0,
            "maximum_drawdown_r": 0.0,
            "recovery_factor": None,
            "sharpe_ratio": None,
        }

    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    total_r = sum(values)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    max_drawdown = _max_drawdown(values)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    recovery_factor = total_r / max_drawdown if max_drawdown > 0 else None
    sharpe_ratio = _sharpe(values)

    return {
        "trade_count": trade_count,
        "total_r": round(total_r, 2),
        "win_rate": round(len(wins) / trade_count * 100, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "average_r": round(total_r / trade_count, 2),
        "average_win_r": round(gross_profit / len(wins), 2) if wins else 0.0,
        "average_loss_r": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "maximum_drawdown_r": round(max_drawdown, 2),
        "recovery_factor": round(recovery_factor, 2) if recovery_factor is not None else None,
        "sharpe_ratio": round(sharpe_ratio, 2) if sharpe_ratio is not None else None,
        "best_trade_r": round(max(values), 2),
        "worst_trade_r": round(min(values), 2),
    }


def evaluate_market_cycle_performance(
    trades: list[dict[str, Any]],
    required_cycles: list[str] | None = None,
    cycle_field: str = "regime",
) -> dict[str, Any]:
    required = required_cycles or DEFAULT_MARKET_CYCLES
    grouped: dict[str, list[dict[str, Any]]] = {}
    for trade in trades:
        cycle = str(trade.get(cycle_field) or "unknown")
        grouped.setdefault(cycle, []).append(trade)

    cycles: dict[str, dict[str, Any]] = {}
    for cycle, cycle_trades in sorted(grouped.items()):
        cycles[cycle] = {
            "trade_count": len(cycle_trades),
            "metrics": calculate_performance_metrics(cycle_trades),
        }

    observed = sorted(cycles)
    missing = [cycle for cycle in required if cycle not in cycles]
    averages = {
        cycle: float(payload["metrics"].get("average_r", 0.0))
        for cycle, payload in cycles.items()
        if int(payload["metrics"].get("trade_count", 0)) > 0
    }
    if averages:
        best_cycle = max(averages, key=lambda cycle: averages[cycle])
        worst_cycle = min(averages, key=lambda cycle: averages[cycle])
        average_dispersion = round(averages[best_cycle] - averages[worst_cycle], 2)
    else:
        best_cycle = None
        worst_cycle = None
        average_dispersion = 0.0

    fragile = bool(missing) or any(value < 0 for value in averages.values()) or average_dispersion >= 2.0
    return {
        "cycles": cycles,
        "coverage": {
            "required_cycles": required,
            "observed_cycles": observed,
            "missing_cycles": missing,
        },
        "robustness": {
            "best_cycle": best_cycle,
            "worst_cycle": worst_cycle,
            "average_r_dispersion": average_dispersion,
            "fragile": fragile,
        },
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def run_monte_carlo_simulation(
    trades: list[dict[str, Any]],
    iterations: int = 1000,
    seed: int | None = None,
) -> dict[str, Any]:
    if iterations <= 0:
        raise ValueError("iterations must be positive")

    values = _r_multiples(trades)
    if not values:
        return {
            "iterations": iterations,
            "ending_r_p05": 0.0,
            "ending_r_p50": 0.0,
            "ending_r_p95": 0.0,
            "max_drawdown_r_p50": 0.0,
            "max_drawdown_r_p95": 0.0,
        }

    rng = random.Random(seed)
    ending_values: list[float] = []
    drawdowns: list[float] = []
    for _ in range(iterations):
        sample = values[:]
        rng.shuffle(sample)
        ending_values.append(sum(sample))
        drawdowns.append(_max_drawdown(sample))

    return {
        "iterations": iterations,
        "ending_r_p05": round(_percentile(ending_values, 0.05), 2),
        "ending_r_p50": round(_percentile(ending_values, 0.50), 2),
        "ending_r_p95": round(_percentile(ending_values, 0.95), 2),
        "max_drawdown_r_p50": round(_percentile(drawdowns, 0.50), 2),
        "max_drawdown_r_p95": round(_percentile(drawdowns, 0.95), 2),
    }
