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


if __name__ == "__main__":
    unittest.main()
