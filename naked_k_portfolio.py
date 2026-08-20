from __future__ import annotations

from typing import Any

import naked_k_config


def classify_market(ticker: str) -> str:
    symbol = ticker.upper()
    if symbol.endswith(".HK"):
        return "hk"
    if symbol.endswith((".SS", ".SZ", ".BJ")):
        return "cn"
    if symbol.endswith((".KS", ".KQ")):
        return "kr"
    if symbol in {"BTC-USD", "ETH-USD", "SOL-USD"}:
        return "crypto"
    return "us"


# Single market -> IANA zone map for the whole repo. Lives here beside
# classify_market because this module imports only naked_k_config, so both the
# data layer and the CLI can reach it without a cycle. Crypto uses UTC because
# its 24/7 bars have no exchange-local session.
_MARKET_TIMEZONES = {
    "cn": "Asia/Shanghai",
    "crypto": "UTC",
    "hk": "Asia/Hong_Kong",
    "kr": "Asia/Seoul",
    "us": "America/New_York",
}
_DEFAULT_TIMEZONE = "Asia/Shanghai"


def market_timezone_name(market: str) -> str:
    """IANA zone name for a market, defaulting to the mainland session."""
    return _MARKET_TIMEZONES.get(market, _DEFAULT_TIMEZONE)


def _value(item: Any, field: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(field, default)
    return getattr(item, field, default)


def _risk_plan(report: Any) -> dict[str, Any]:
    value = _value(report, "risk_plan", {})
    return value if isinstance(value, dict) else {}


def _direction_bucket(direction: str) -> str:
    # Defensive plans represent residual long exposure being reduced or avoided;
    # they are not naked shorts and therefore still consume the long-side cap.
    return "long" if direction == "bearish_defensive" else direction


def evaluate_portfolio_exposure(
    reports: list[Any],
    config: naked_k_config.PortfolioConfig | None = None,
) -> dict[str, Any]:
    limits = config or naked_k_config.PortfolioConfig()
    positions: list[dict[str, Any]] = []
    for report in reports:
        risk_plan = _risk_plan(report)
        gross_pct = round(float(risk_plan.get("suggested_gross_pct", 0.0) or 0.0), 2)
        account_risk_pct = round(float(risk_plan.get("effective_account_risk_pct", 0.0) or 0.0), 2)
        # 只有实际开仓（gross_pct > 0）时才计入组合风险
        # 防守计划（gross=0, risk>0）不应计入组合暴露
        if gross_pct <= 0:
            continue
        ticker = str(_value(report, "ticker", ""))
        direction = _direction_bucket(str(risk_plan.get("direction", "none")))
        positions.append(
            {
                "ticker": ticker,
                "action": str(_value(report, "action", "")),
                "direction": direction,
                "market": classify_market(ticker),
                "gross_pct": gross_pct,
                "account_risk_pct": account_risk_pct,
            }
        )

    total_gross = round(sum(position["gross_pct"] for position in positions), 2)
    total_account_risk = round(sum(position["account_risk_pct"] for position in positions), 2)
    direction_gross: dict[str, float] = {}
    market_gross: dict[str, float] = {}
    single_name_gross: dict[str, float] = {}
    for position in positions:
        direction = position["direction"]
        market = position["market"]
        ticker = position["ticker"]
        direction_gross[direction] = round(direction_gross.get(direction, 0.0) + position["gross_pct"], 2)
        market_gross[market] = round(market_gross.get(market, 0.0) + position["gross_pct"], 2)
        single_name_gross[ticker] = round(single_name_gross.get(ticker, 0.0) + position["gross_pct"], 2)

    guardrails: list[str] = []
    if total_gross > limits.max_total_gross_pct:
        guardrails.append("总仓位暴露超限")
    if total_account_risk > limits.max_total_account_risk_pct:
        guardrails.append("账户风险暴露超限")
    for direction, gross_pct in direction_gross.items():
        if direction == "long" and gross_pct > limits.max_direction_gross_pct:
            guardrails.append("多头方向暴露超限")
        elif direction == "short" and gross_pct > limits.max_direction_gross_pct:
            guardrails.append("空头方向暴露超限")
    for market, gross_pct in market_gross.items():
        if gross_pct > limits.max_market_gross_pct:
            guardrails.append(f"{market}市场暴露超限")
    for ticker, gross_pct in single_name_gross.items():
        if gross_pct > limits.max_single_name_gross_pct:
            guardrails.append(f"{ticker}单标的暴露超限")

    return {
        "status": "over_limit" if guardrails else "within_limits",
        "total_gross_pct": total_gross,
        "total_account_risk_pct": total_account_risk,
        "direction_gross_pct": direction_gross,
        "market_gross_pct": market_gross,
        "single_name_gross_pct": single_name_gross,
        "positions": positions,
        "limits": {
            "max_total_gross_pct": limits.max_total_gross_pct,
            "max_direction_gross_pct": limits.max_direction_gross_pct,
            "max_market_gross_pct": limits.max_market_gross_pct,
            "max_single_name_gross_pct": limits.max_single_name_gross_pct,
            "max_total_account_risk_pct": limits.max_total_account_risk_pct,
        },
        "guardrails": guardrails,
    }


def format_portfolio_exposure(exposure: dict[str, Any]) -> str:
    if not exposure:
        return "暂无"
    status = "超限" if exposure.get("status") == "over_limit" else "正常"
    guardrails = exposure.get("guardrails") or []
    guardrail_text = "、".join(str(item) for item in guardrails) if guardrails else "无"
    return (
        f"{status}；总仓位 {exposure.get('total_gross_pct', 0)}%；"
        f"账户风险 {exposure.get('total_account_risk_pct', 0)}%；"
        f"保护：{guardrail_text}"
    )
