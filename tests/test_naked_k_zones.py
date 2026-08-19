import unittest

import pandas as pd

import naked_k_trade
import naked_k_zones


class NakedKZoneTests(unittest.TestCase):
    def test_clusters_repeated_lows_into_demand_zone(self):
        frame = pd.DataFrame(
            {
                "Open": [101, 103, 99, 104, 100, 106, 101, 107, 102, 108],
                "High": [104, 105, 103, 106, 104, 108, 105, 109, 106, 110],
                "Low": [99, 101, 95.0, 102, 95.4, 103, 95.2, 104, 96.0, 105],
                "Close": [103, 102, 101, 105, 102, 107, 103, 108, 104, 109],
                "Volume": [1000, 980, 1800, 1000, 1900, 1100, 2000, 1200, 1600, 1300],
            },
            index=pd.date_range("2026-06-01", periods=10, freq="D"),
        )

        zones = naked_k_zones.detect_price_zones(frame, close=109.0, swing_window=1)

        demand = zones["nearest_support"]
        self.assertEqual(demand["kind"], "demand")
        self.assertEqual(demand["touches"], 4)
        self.assertEqual(demand["strength"], "strong")
        self.assertLessEqual(demand["lower"], 95.0)
        self.assertGreaterEqual(demand["upper"], 96.0)
        self.assertIn("zone_id", demand, "需求区必须有稳定的 zone_id")
        self.assertTrue(demand["zone_id"].startswith("zone-"), "zone_id 应以 zone- 开头")

    def test_clusters_repeated_highs_into_supply_zone_and_buy_side_liquidity(self):
        frame = pd.DataFrame(
            {
                "Open": [100, 105, 101, 106, 102, 107, 103, 106, 102, 105],
                "High": [104, 111.0, 105, 111.4, 106, 111.2, 107, 110.8, 106, 108],
                "Low": [98, 102, 99, 103, 100, 104, 101, 103, 99, 101],
                "Close": [103, 104, 104, 105, 105, 106, 106, 104, 103, 104],
                "Volume": [1000, 1700, 1000, 1800, 1000, 1750, 1000, 1600, 1000, 1000],
            },
            index=pd.date_range("2026-06-01", periods=10, freq="D"),
        )

        zones = naked_k_zones.detect_price_zones(frame, close=104.0, swing_window=1)

        supply = zones["nearest_resistance"]
        self.assertEqual(supply["kind"], "supply")
        self.assertEqual(supply["touches"], 4)
        self.assertEqual(supply["strength"], "strong")
        self.assertGreaterEqual(supply["lower"], 110.8)
        self.assertLessEqual(supply["upper"], 111.4)
        self.assertIn("zone_id", supply, "供给区必须有稳定的 zone_id")
        self.assertEqual(zones["liquidity_pools"][0]["kind"], "buy_side_liquidity")
        self.assertIn("pool_id", zones["liquidity_pools"][0], "流动性池必须有稳定的 pool_id")

    def test_detects_high_volume_node_zone(self):
        frame = pd.DataFrame(
            {
                "Open": [98, 99, 100, 101, 102, 103, 104, 105],
                "High": [101, 102, 103, 104, 105, 106, 107, 108],
                "Low": [97, 98, 99, 100, 101, 102, 103, 104],
                "Close": [100, 101, 102, 103, 104, 105, 106, 107],
                "Volume": [1000, 1100, 5000, 5200, 5100, 1200, 1000, 900],
            },
            index=pd.date_range("2026-06-01", periods=8, freq="D"),
        )

        zones = naked_k_zones.detect_price_zones(frame, close=107.0, bins=4)

        volume_zone = zones["volume_zones"][0]
        self.assertEqual(volume_zone["kind"], "volume_node")
        self.assertEqual(volume_zone["strength"], "strong")
        self.assertLessEqual(volume_zone["lower"], 103.0)
        self.assertGreaterEqual(volume_zone["upper"], 101.0)

    def test_detects_volume_profile_poc_and_value_area(self):
        frame = pd.DataFrame(
            {
                "Open": [98, 99, 100, 101, 102, 103, 104, 105, 106, 107],
                "High": [101, 102, 103, 104, 105, 106, 107, 108, 109, 110],
                "Low": [97, 98, 99, 100, 101, 102, 103, 104, 105, 106],
                "Close": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
                "Volume": [1000, 1000, 5200, 5400, 5300, 1300, 1200, 1100, 900, 800],
            },
            index=pd.date_range("2026-06-01", periods=10, freq="D"),
        )

        zones = naked_k_zones.detect_price_zones(frame, close=109.0, bins=5)

        profile = zones["volume_profile"]
        self.assertEqual(profile["poc"]["kind"], "point_of_control")
        self.assertGreaterEqual(profile["poc"]["volume_share"], 0.4)
        self.assertLessEqual(profile["value_area"]["lower"], profile["poc"]["midpoint"])
        self.assertGreaterEqual(profile["value_area"]["upper"], profile["poc"]["midpoint"])
        self.assertGreaterEqual(profile["value_area"]["volume_share"], 0.7)
        self.assertEqual(len(profile["buckets"]), 5)

    def test_detects_anchored_vwap_from_latest_structural_swing(self):
        frame = pd.DataFrame(
            {
                "Open": [103, 101, 98, 100, 102, 104, 105],
                "High": [104, 102, 100, 103, 105, 107, 108],
                "Low": [101, 99, 94, 98, 100, 102, 104],
                "Close": [102, 100, 99, 102, 104, 106, 107],
                "Volume": [1000, 1100, 2000, 1600, 1700, 1800, 1900],
            },
            index=pd.date_range("2026-06-01", periods=7, freq="D"),
        )

        zones = naked_k_zones.detect_price_zones(frame, close=107.0, swing_window=1)

        anchored = zones["anchored_vwap"]
        self.assertEqual(anchored["kind"], "anchored_vwap")
        self.assertEqual(anchored["anchor_type"], "swing_low")
        self.assertEqual(anchored["anchor_date"], "2026-06-03")
        self.assertGreater(anchored["value"], 100.0)
        self.assertEqual(anchored["side"], "below")

    def test_price_zone_summary_includes_poc_and_anchored_vwap(self):
        summary = naked_k_trade.format_price_zones_summary(
            {
                "nearest_support": None,
                "nearest_resistance": None,
                "liquidity_pools": [],
                "volume_zones": [],
                "volume_profile": {
                    "poc": {"midpoint": 102.5, "lower": 101.0, "upper": 104.0},
                    "value_area": {"lower": 99.0, "upper": 106.0, "volume_share": 0.72},
                },
                "anchored_vwap": {"value": 103.4, "anchor_type": "swing_low", "side": "below"},
            }
        )

        self.assertIn("POC", summary)
        self.assertIn("价值区域", summary)
        self.assertIn("Anchored VWAP", summary)


if __name__ == "__main__":
    unittest.main()
