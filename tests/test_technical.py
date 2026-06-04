import json
import unittest
from unittest.mock import patch

from stock_analysis.technical import analyze_technical


class TechnicalWrapperTests(unittest.TestCase):
    def test_analyze_technical_preserves_horizon_scores_without_4h_proxy_warning(self):
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
        self.assertEqual(snapshot.warnings, [])
        self.assertEqual(snapshot.timeframe_scores["short"], 1.0)
        self.assertEqual(snapshot.timeframe_directions["short"], "bullish")

    def test_analyze_technical_appends_jg_methodology_summary(self):
        payload = {
            "ticker": "NVDA",
            "timeframes": [
                {
                    "tf": "日线",
                    "weighted_score": {"score": 0.5},
                    "macd": {"zone": "零轴上", "hist_dir": "红柱", "cross": None},
                    "rsi": 58,
                    "rsi_signal": "偏强",
                    "boll_signal": "接近上轨",
                    "vegas": {"position": "通道上方", "trend": "多头趋势"},
                    "ichimoku": {"cloud_pos": "云上(多头)"},
                    "obv": {"trend": "量价齐升"},
                    "frvp": {"poc": 100.0, "position": "价值区上方"},
                    "supports": [],
                    "resistances": [],
                }
            ],
            "resonance": {"action": "无明显共振，观望"},
        }

        with patch("ma_analysis.analyze") as analyze:
            analyze.side_effect = lambda *args, **kwargs: print(json.dumps(payload, ensure_ascii=False))
            snapshot = analyze_technical("NVDA", timeframes=["daily"])

        self.assertIn("无明显共振，观望", snapshot.summary)
        self.assertIn("MACD零轴上", snapshot.summary)
        self.assertIn("BOLL", snapshot.summary)
        self.assertIn("Vegas", snapshot.summary)
        self.assertIn("FRVP", snapshot.summary)

    def test_analyze_technical_builds_structured_evidence_sections(self):
        payload = {
            "ticker": "NVDA",
            "timeframes": [
                {
                    "tf": "日线",
                    "weighted_score": {"score": 1.0},
                    "arrangement": "多头排列",
                    "macd": {"zone": "零轴上", "hist_dir": "红柱", "cross": None},
                    "rsi": 58,
                    "rsi_signal": "偏强",
                    "boll_signal": "接近上轨",
                    "vegas": {"position": "通道上方", "trend": "多头趋势"},
                    "ichimoku": {"cloud_pos": "云上(多头)"},
                    "avwap_low": 100.0,
                    "frvp": {"poc": 110.0, "position": "价值区上方"},
                    "supports": [],
                    "resistances": [],
                }
            ],
            "resonance": {"action": "日线偏多"},
        }

        with patch("ma_analysis.analyze") as analyze:
            analyze.side_effect = lambda *args, **kwargs: print(json.dumps(payload, ensure_ascii=False))
            snapshot = analyze_technical("NVDA", timeframes=["daily"])

        self.assertIn("Vegas", " ".join(snapshot.evidence_sections["trend"]))
        self.assertIn("MACD", " ".join(snapshot.evidence_sections["momentum"]))
        self.assertIn("FRVP", " ".join(snapshot.evidence_sections["cost"]))
        self.assertIn("100", " ".join(snapshot.evidence_sections["cost"]))
