from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_ACTION_GROSS_CAPS = {
    "买入": 30.0,
    "小仓试错": 15.0,
    "减仓": 10.0,
    "回避": 0.0,
    "观望": 0.0,
}


@dataclass(frozen=True)
class RiskConfig:
    account_risk_pct: float = 1.0
    max_drawdown_pct: float = 8.0
    consecutive_loss_limit: int = 3
    consecutive_loss_risk_multiplier: float = 0.5
    action_gross_caps: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_ACTION_GROSS_CAPS))


@dataclass(frozen=True)
class PortfolioConfig:
    max_total_gross_pct: float = 80.0
    max_direction_gross_pct: float = 60.0
    max_market_gross_pct: float = 40.0
    max_single_name_gross_pct: float = 30.0
    max_total_account_risk_pct: float = 3.0


@dataclass(frozen=True)
class TradingConfig:
    risk: RiskConfig = field(default_factory=RiskConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)


def _merge_action_caps(overrides: dict[str, Any] | None) -> dict[str, float]:
    caps = dict(DEFAULT_ACTION_GROSS_CAPS)
    if overrides:
        caps.update({str(key): float(value) for key, value in overrides.items()})
    return caps


def build_trading_config(payload: dict[str, Any] | None = None) -> TradingConfig:
    data = payload or {}
    risk_data = dict(data.get("risk") or {})
    portfolio_data = dict(data.get("portfolio") or {})
    action_caps = _merge_action_caps(risk_data.pop("action_gross_caps", None))
    risk = RiskConfig(
        account_risk_pct=float(risk_data.get("account_risk_pct", RiskConfig.account_risk_pct)),
        max_drawdown_pct=float(risk_data.get("max_drawdown_pct", RiskConfig.max_drawdown_pct)),
        consecutive_loss_limit=int(risk_data.get("consecutive_loss_limit", RiskConfig.consecutive_loss_limit)),
        consecutive_loss_risk_multiplier=float(
            risk_data.get("consecutive_loss_risk_multiplier", RiskConfig.consecutive_loss_risk_multiplier)
        ),
        action_gross_caps=action_caps,
    )
    portfolio = PortfolioConfig(
        max_total_gross_pct=float(portfolio_data.get("max_total_gross_pct", PortfolioConfig.max_total_gross_pct)),
        max_direction_gross_pct=float(
            portfolio_data.get("max_direction_gross_pct", PortfolioConfig.max_direction_gross_pct)
        ),
        max_market_gross_pct=float(portfolio_data.get("max_market_gross_pct", PortfolioConfig.max_market_gross_pct)),
        max_single_name_gross_pct=float(
            portfolio_data.get("max_single_name_gross_pct", PortfolioConfig.max_single_name_gross_pct)
        ),
        max_total_account_risk_pct=float(
            portfolio_data.get("max_total_account_risk_pct", PortfolioConfig.max_total_account_risk_pct)
        ),
    )
    return TradingConfig(risk=risk, portfolio=portfolio)


def load_trading_config(path: str | Path | None = None) -> TradingConfig:
    if path is None:
        return build_trading_config()
    config_path = Path(path)
    if not config_path.exists():
        return build_trading_config()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Trading config must be a JSON object")
    return build_trading_config(payload)
