import json
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

import naked_k_config


class NakedKConfigTests(unittest.TestCase):
    def test_loads_trading_config_from_json_with_nested_risk_and_portfolio_limits(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "naked_k_config.json"
            path.write_text(
                json.dumps(
                    {
                        "risk": {
                            "account_risk_pct": 0.5,
                            "max_drawdown_pct": 5.0,
                            "consecutive_loss_limit": 2,
                            "consecutive_loss_risk_multiplier": 0.25,
                            "action_gross_caps": {"买入": 20.0, "小仓试错": 8.0},
                        },
                        "portfolio": {
                            "max_total_gross_pct": 45.0,
                            "max_direction_gross_pct": 35.0,
                            "max_market_gross_pct": 25.0,
                            "max_total_account_risk_pct": 2.0,
                        },
                    }
                ),
                encoding="utf-8",
            )

            config = naked_k_config.load_trading_config(path)

        self.assertEqual(config.risk.account_risk_pct, 0.5)
        self.assertEqual(config.risk.max_drawdown_pct, 5.0)
        self.assertEqual(config.risk.consecutive_loss_limit, 2)
        self.assertEqual(config.risk.consecutive_loss_risk_multiplier, 0.25)
        self.assertEqual(config.risk.action_gross_caps["买入"], 20.0)
        self.assertEqual(config.portfolio.max_total_gross_pct, 45.0)
        self.assertEqual(config.portfolio.max_market_gross_pct, 25.0)


    def test_loads_nested_smart_money_config(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "smart_money_config.json"
            path.write_text(
                json.dumps(
                    {
                        "smart_money": {
                            "enabled": True,
                            "mode": "dual_evidence",
                            "price_action": {
                                "volume_anomaly_threshold": 2.0,
                                "sweep_close_position_threshold": 0.7,
                                "exhaustion_volume_ratio": 0.85,
                            },
                            "trade_flow": {
                                "enabled": True,
                                "provider": "eastmoney_hk",
                                "timeout_seconds": 6.0,
                                "max_retries": 2,
                            },
                            "short_selling": {
                                "enabled": False,
                                "provider": "hkex",
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            config = naked_k_config.load_trading_config(path)

        self.assertEqual(config.smart_money.enabled, True)
        self.assertEqual(config.smart_money.mode, "dual_evidence")
        self.assertEqual(config.smart_money.price_action.volume_anomaly_threshold, 2.0)
        self.assertEqual(config.smart_money.price_action.sweep_close_position_threshold, 0.7)
        self.assertEqual(config.smart_money.price_action.exhaustion_volume_ratio, 0.85)
        self.assertEqual(config.smart_money.trade_flow.enabled, True)
        self.assertEqual(config.smart_money.trade_flow.provider, "eastmoney_hk")
        self.assertEqual(config.smart_money.trade_flow.timeout_seconds, 6.0)
        self.assertEqual(config.smart_money.trade_flow.max_retries, 2)
        self.assertEqual(config.smart_money.short_selling.enabled, False)

    def test_legacy_smart_money_fields_map_to_price_action_with_warnings(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "legacy_config.json"
            path.write_text(
                json.dumps(
                    {
                        "smart_money": {
                            "volume_anomaly_threshold": 1.8,
                            "sweep_recovery_threshold": 0.6,
                            "exhaustion_volume_ratio": 0.75,
                            "confluence_weight": 0.5,
                        }
                    }
                ),
                encoding="utf-8",
            )

            import warnings
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                config = naked_k_config.load_trading_config(path)
                # Should have DeprecationWarning
                self.assertTrue(any(issubclass(warning.category, DeprecationWarning) for warning in w))

        self.assertEqual(config.smart_money.price_action.volume_anomaly_threshold, 1.8)
        self.assertEqual(config.smart_money.price_action.sweep_close_position_threshold, 0.6)
        self.assertEqual(config.smart_money.price_action.exhaustion_volume_ratio, 0.75)
        self.assertTrue(len(config.smart_money.deprecation_warnings) > 0)

    def test_invalid_smart_money_mode_raises_value_error(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad_mode.json"
            path.write_text(
                json.dumps({"smart_money": {"mode": "invalid_mode"}}),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                naked_k_config.load_trading_config(path)

    def test_negative_max_retries_raises_value_error(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad_retries.json"
            path.write_text(
                json.dumps({"smart_money": {"trade_flow": {"max_retries": -1}}}),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                naked_k_config.load_trading_config(path)


if __name__ == "__main__":
    unittest.main()
