"""Validated strategy assumptions and independent account risk limits."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_ACTION_GROSS_CAPS = {'买入': 30.0, '小仓试错': 15.0, '减仓': 0.0, '回避': 0.0, '观望': 0.0}


def number(value: Any, name: str, minimum: float = 0, maximum: float = 100) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be a number')
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be finite and in [{minimum}, {maximum}]')
    return float(value)


@dataclass(frozen=True)
class RiskConfig:
    account_risk_pct: float = 1.0
    max_drawdown_pct: float = 8.0
    consecutive_loss_limit: int = 3
    consecutive_loss_risk_multiplier: float = 0.5
    action_gross_caps: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_ACTION_GROSS_CAPS))

    def __post_init__(self):
        number(self.account_risk_pct, 'account_risk_pct')
        number(self.max_drawdown_pct, 'max_drawdown_pct', 0.01)
        if type(self.consecutive_loss_limit) is not int or self.consecutive_loss_limit < 1:
            raise ValueError('consecutive_loss_limit must be a positive integer')
        number(self.consecutive_loss_risk_multiplier, 'consecutive_loss_risk_multiplier', 0, 1)
        if not isinstance(self.action_gross_caps, dict) or set(self.action_gross_caps) - set(DEFAULT_ACTION_GROSS_CAPS):
            raise ValueError('invalid action_gross_caps')
        for action, cap in self.action_gross_caps.items():
            number(cap, f'action_gross_caps.{action}')


@dataclass(frozen=True)
class PortfolioConfig:
    max_total_gross_pct: float = 80.0
    max_direction_gross_pct: float = 60.0
    max_market_gross_pct: float = 40.0
    max_single_name_gross_pct: float = 30.0
    max_total_account_risk_pct: float = 3.0

    def __post_init__(self):
        for item in fields(self):
            number(getattr(self, item.name), item.name)


@dataclass(frozen=True)
class DualMAConfig:
    # These numerical definitions are engineering choices, not video quotations.
    cluster_width_pct: float = 1.0
    cluster_min_bars: int = 3
    confirmation_bars: int = 2
    setup_max_bars: int = 20
    stop_buffer_pct: float = 0.1
    max_entry_gap_r: float = 0.5
    exit_method: str = 'fixed_r'
    take_profit_r: float = 3.0
    min_reward_risk: float = 3.0
    fibonacci_ratio: float = 1.618
    fibonacci_anchors: dict[str, dict[str, str]] = field(default_factory=dict)

    def __post_init__(self):
        number(self.cluster_width_pct, 'cluster_width_pct', .001, 20)
        number(self.stop_buffer_pct, 'stop_buffer_pct', 0, 10)
        number(self.max_entry_gap_r, 'max_entry_gap_r', 0, 10)
        number(self.take_profit_r, 'take_profit_r', 1, 100)
        number(self.min_reward_risk, 'min_reward_risk', 1, 100)
        for key in ('cluster_min_bars', 'confirmation_bars', 'setup_max_bars'):
            if type(getattr(self, key)) is not int or not 1 <= getattr(self, key) <= 250:
                raise ValueError(f'{key} must be an integer in [1, 250]')
        if not isinstance(self.exit_method, str) or self.exit_method not in {'fixed_r', 'previous_cluster', 'fibonacci'}:
            raise ValueError('exit_method must be fixed_r, previous_cluster or fibonacci')
        if self.take_profit_r < self.min_reward_risk:
            raise ValueError('take_profit_r must be at least min_reward_risk')
        if self.fibonacci_ratio not in (1.618, 2.618, 3.618, 4.236):
            raise ValueError('unsupported fibonacci_ratio')
        if not isinstance(self.fibonacci_anchors, dict):
            raise ValueError('fibonacci_anchors must be a ticker-keyed object')
        for ticker, anchor in self.fibonacci_anchors.items():
            if not isinstance(ticker, str) or not ticker or ticker != ticker.strip().upper():
                raise ValueError('fibonacci anchor tickers must be normalized uppercase symbols')
            if not isinstance(anchor, dict) or set(anchor) != {'high_date', 'low_date'}:
                raise ValueError('fibonacci anchors require high_date and low_date')
            try:
                high, low = date.fromisoformat(anchor['high_date']), date.fromisoformat(anchor['low_date'])
            except (ValueError, TypeError):
                raise ValueError('fibonacci anchor dates must be YYYY-MM-DD') from None
            if high >= low:
                raise ValueError('fibonacci high_date must precede low_date')


@dataclass(frozen=True)
class TradingConfig:
    risk: RiskConfig = field(default_factory=RiskConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    strategy: DualMAConfig = field(default_factory=DualMAConfig)


def build_trading_config(payload: dict[str, Any] | None = None) -> TradingConfig:
    data = {} if payload is None else payload
    if not isinstance(data, dict):
        raise ValueError('config must be a JSON object')
    if 'smart_money' in data:
        raise ValueError('smart_money 已移除；请按 config.example.json 迁移配置')
    if set(data) - {'risk', 'portfolio', 'strategy'}:
        raise ValueError('unknown config fields')
    sections = []
    for key, cls in [('risk', RiskConfig), ('portfolio', PortfolioConfig), ('strategy', DualMAConfig)]:
        values = data.get(key, {})
        if not isinstance(values, dict) or set(values) - {f.name for f in fields(cls)}:
            raise ValueError(f'invalid {key} configuration fields')
        values = dict(values)
        if key == 'risk' and 'action_gross_caps' in values:
            caps = values['action_gross_caps']
            if not isinstance(caps, dict):
                raise ValueError('action_gross_caps must be an object')
            values['action_gross_caps'] = {**DEFAULT_ACTION_GROSS_CAPS, **caps}
        sections.append(cls(**values))
    return TradingConfig(*sections)


def load_trading_config(path: str | Path | None = None) -> TradingConfig:
    return build_trading_config(json.loads(Path(path).read_text(encoding='utf-8')) if path else None)
