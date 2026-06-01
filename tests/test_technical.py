import json
import unittest
from unittest.mock import patch

from stock_analysis.technical import analyze_technical


class TechnicalWrapperTests(unittest.TestCase):
    def test_analyze_technical_adds_4h_daily_proxy_warning(self):
        payload = {
            "ticker": "NVDA",
            "timeframes": [
                {
                    "tf": "4小时",
                    "weighted_score": {"score": 1.0},
                    "supports": [{"price": 100.0}],
                    "resistances": [{"price": 120.0}],
                }
            ],
            "resonance": {"action": "短线4H为日线替代"},
        }

        with patch("ma_analysis.analyze") as analyze:
            analyze.side_effect = lambda *args, **kwargs: print(json.dumps(payload, ensure_ascii=False))
            snapshot = analyze_technical("NVDA", timeframes=["4h"])

        self.assertEqual(snapshot.direction, "bullish")
        self.assertIn("4H", " ".join(snapshot.warnings))
        self.assertIn("日线替代", " ".join(snapshot.warnings))
