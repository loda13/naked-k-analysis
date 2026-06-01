import json
import tempfile
import unittest
from pathlib import Path

from stock_analysis.wss_refresh import refresh_cache_from_html_dir


RESEARCH_HTML = """
<html><body>
<h1>半导体研究 2026-06-01</h1>
<table>
<tr><th>排名</th><th>Ticker</th><th>分数</th><th>证据</th><th>评级</th><th>行业</th><th>业务纯度</th><th>催化</th><th>风险</th></tr>
<tr><td>6</td><td>AVGO</td><td>79</td><td>A</td><td>核心买入名单</td><td>半导体</td><td>中</td><td>AI ASIC / 网络交换芯片</td><td>估值高</td></tr>
<tr><td>14</td><td>NVDA</td><td>74</td><td>B+</td><td>观察名单</td><td>半导体</td><td>高</td><td>AI数据中心收入 / 软件生态</td><td>出口限制 / 估值高</td></tr>
</table>
</body></html>
"""

MARKET_HTML = """
<html><body>
<h1>AI泡沫周期监控 2026-06-01</h1>
<p>市场状态: 警戒观察</p>
<p>泡沫阶段: 1999 叙事和估值同步加速</p>
<p>过热板块: SOX, HBM, AI 存储</p>
<table>
<tr><th>名称</th><th>状态</th><th>当前值</th><th>触发线</th></tr>
<tr><td>QQQ 防守线</td><td>watch</td><td>738.31</td><td>&lt; 720</td></tr>
<tr><td>VIX 破裂线</td><td>supportive</td><td>15.32</td><td>&gt; 20</td></tr>
</table>
</body></html>
"""

EARNINGS_HTML = """
<html><body>
<h1>美股财报日 2026-06-01</h1>
<table>
<tr><th>Ticker</th><th>日期</th><th>时间</th><th>EPS预期</th><th>收入预期</th><th>IV隐含波动</th></tr>
<tr><td>NVDA</td><td>2026-06-10</td><td>盘后</td><td>--</td><td>--</td><td>6.5%</td></tr>
</table>
</body></html>
"""


class WssRefreshTests(unittest.TestCase):
    def test_refresh_cache_from_html_dir_writes_derived_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html_dir = root / "html"
            cache_dir = root / "cache"
            html_dir.mkdir()
            (html_dir / "research_semiconductor.html").write_text(RESEARCH_HTML, encoding="utf-8")
            (html_dir / "market_risk.html").write_text(MARKET_HTML, encoding="utf-8")
            (html_dir / "earnings.html").write_text(EARNINGS_HTML, encoding="utf-8")

            result = refresh_cache_from_html_dir(html_dir, cache_dir)

            self.assertEqual(result["research_count"], 2)
            self.assertEqual(result["market_rules_count"], 2)
            self.assertEqual(result["earnings_count"], 1)

            research = json.loads((cache_dir / "research.json").read_text(encoding="utf-8"))
            market = json.loads((cache_dir / "market_risk.json").read_text(encoding="utf-8"))
            earnings = json.loads((cache_dir / "earnings.json").read_text(encoding="utf-8"))

            self.assertEqual(research["tickers"]["NVDA"]["score"], 74)
            self.assertEqual(research["tickers"]["AVGO"]["rank"], 6)
            self.assertEqual(research["tickers"]["NVDA"]["catalysts"], ["AI数据中心收入", "软件生态"])
            self.assertEqual(market["market_state"], "警戒观察")
            self.assertEqual(market["sector_overheats"], ["SOX", "HBM", "AI 存储"])
            self.assertEqual(earnings["events"]["NVDA"]["implied_move"], 6.5)

    def test_refresh_cache_does_not_store_raw_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html_dir = root / "html"
            cache_dir = root / "cache"
            html_dir.mkdir()
            (html_dir / "research.html").write_text(RESEARCH_HTML, encoding="utf-8")

            refresh_cache_from_html_dir(html_dir, cache_dir)

            serialized = "\n".join(path.read_text(encoding="utf-8") for path in cache_dir.glob("*.json"))
            self.assertNotIn("<table>", serialized)
            self.assertNotIn("<html>", serialized)
