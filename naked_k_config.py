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
class PriceActionEvidenceConfig:
    """Price action evidence detection thresholds."""
    volume_anomaly_threshold: float = 1.5
    sweep_close_position_threshold: float = 0.65
    exhaustion_volume_ratio: float = 0.8


@dataclass(frozen=True)
class TradeFlowConfig:
    """Trade flow provider configuration."""
    enabled: bool = True
    provider: str = "eastmoney_hk"
    timeout_seconds: float = 5.0
    max_retries: int = 1
    persist_raw: bool = True
    require_session_complete: bool = True


@dataclass(frozen=True)
class ShortSellingConfig:
    """Short selling provider configuration."""
    enabled: bool = True
    provider: str = "hkex"


@dataclass(frozen=True)
class SmartMoneyConfig:
    """Dual-evidence smart money configuration."""
    enabled: bool = True
    mode: str = "dual_evidence"
    price_action: PriceActionEvidenceConfig = field(default_factory=PriceActionEvidenceConfig)
    trade_flow: TradeFlowConfig = field(default_factory=TradeFlowConfig)
    short_selling: ShortSellingConfig = field(default_factory=ShortSellingConfig)
    deprecation_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class TradingConfig:
    risk: RiskConfig = field(default_factory=RiskConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    smart_money: SmartMoneyConfig = field(default_factory=SmartMoneyConfig)


def _merge_action_caps(overrides: dict[str, Any] | None) -> dict[str, float]:
    caps = dict(DEFAULT_ACTION_GROSS_CAPS)
    if overrides:
        caps.update({str(key): float(value) for key, value in overrides.items()})
    return caps


def build_trading_config(payload: dict[str, Any] | None = None) -> TradingConfig:
    import warnings

    data = payload or {}
    risk_data = dict(data.get("risk") or {})
    portfolio_data = dict(data.get("portfolio") or {})
    smart_money_data = dict(data.get("smart_money") or {})

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

    # Build smart money config with legacy field migration
    deprecation_warnings_list = []

    # Check for legacy fields
    legacy_volume = smart_money_data.get("volume_anomaly_threshold")
    legacy_sweep = smart_money_data.get("sweep_recovery_threshold")
    legacy_exhaustion = smart_money_data.get("exhaustion_volume_ratio")
    legacy_confluence = smart_money_data.get("confluence_weight")

    has_legacy = any([legacy_volume is not None, legacy_sweep is not None,
                      legacy_exhaustion is not None, legacy_confluence is not None])

    if has_legacy:
        deprecation_warnings_list.append("LEGACY_FIELDS")
        warnings.warn(
            "Legacy smart_money fields (volume_anomaly_threshold, sweep_recovery_threshold, "
            "exhaustion_volume_ratio, confluence_weight) are deprecated. "
            "Use nested price_action/trade_flow/short_selling configuration.",
            DeprecationWarning,
            stacklevel=2
        )

    # Extract nested configs or use legacy mapping
    price_action_data = smart_money_data.get("price_action", {})
    if not price_action_data and has_legacy:
        # Map legacy fields to price_action
        price_action_data = {}
        if legacy_volume is not None:
            price_action_data["volume_anomaly_threshold"] = legacy_volume
        if legacy_sweep is not None:
            price_action_data["sweep_close_position_threshold"] = legacy_sweep
        if legacy_exhaustion is not None:
            price_action_data["exhaustion_volume_ratio"] = legacy_exhaustion

    price_action = PriceActionEvidenceConfig(
        volume_anomaly_threshold=float(
            price_action_data.get("volume_anomaly_threshold", PriceActionEvidenceConfig.volume_anomaly_threshold)
        ),
        sweep_close_position_threshold=float(
            price_action_data.get("sweep_close_position_threshold", PriceActionEvidenceConfig.sweep_close_position_threshold)
        ),
        exhaustion_volume_ratio=float(
            price_action_data.get("exhaustion_volume_ratio", PriceActionEvidenceConfig.exhaustion_volume_ratio)
        ),
    )

    trade_flow_data = smart_money_data.get("trade_flow", {})
    trade_flow_enabled = bool(trade_flow_data.get("enabled", TradeFlowConfig.enabled))
    trade_flow_provider = str(trade_flow_data.get("provider", TradeFlowConfig.provider))
    trade_flow_timeout = float(trade_flow_data.get("timeout_seconds", TradeFlowConfig.timeout_seconds))
    trade_flow_retries = int(trade_flow_data.get("max_retries", TradeFlowConfig.max_retries))

    # Validate
    if trade_flow_timeout <= 0:
        raise ValueError(f"trade_flow.timeout_seconds must be positive, got {trade_flow_timeout}")
    if trade_flow_retries < 0:
        raise ValueError(f"trade_flow.max_retries must be non-negative, got {trade_flow_retries}")

    trade_flow = TradeFlowConfig(
        enabled=trade_flow_enabled,
        provider=trade_flow_provider,
        timeout_seconds=trade_flow_timeout,
        max_retries=trade_flow_retries,
        persist_raw=bool(trade_flow_data.get("persist_raw", TradeFlowConfig.persist_raw)),
        require_session_complete=bool(trade_flow_data.get("require_session_complete", TradeFlowConfig.require_session_complete)),
    )

    short_selling_data = smart_money_data.get("short_selling", {})
    short_selling = ShortSellingConfig(
        enabled=bool(short_selling_data.get("enabled", ShortSellingConfig.enabled)),
        provider=str(short_selling_data.get("provider", ShortSellingConfig.provider)),
    )

    mode = str(smart_money_data.get("mode", SmartMoneyConfig.mode))
    if mode not in ("dual_evidence",):
        raise ValueError(f"Invalid smart_money.mode: {mode}. Expected 'dual_evidence'.")

    smart_money = SmartMoneyConfig(
        enabled=bool(smart_money_data.get("enabled", SmartMoneyConfig.enabled)),
        mode=mode,
        price_action=price_action,
        trade_flow=trade_flow,
        short_selling=short_selling,
        deprecation_warnings=tuple(deprecation_warnings_list),
    )

    return TradingConfig(risk=risk, portfolio=portfolio, smart_money=smart_money)


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
