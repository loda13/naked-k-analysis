import unittest

from stock_analysis.models import Advice
from stock_analysis.report import render_text_report


class ReportRenderingTests(unittest.TestCase):
    def test_text_report_starts_with_plain_language_conclusion(self):
        advice = Advice(
            ticker="0700.HK",
            overall_action="观望",
            short_term_action="观望",
            medium_term_action="等待日线确认",
            long_term_action="长期观察",
            confidence="中",
            position_guidance="空仓等待",
            current_price=465.0,
            invalidation="暂无明确失效线",
            upside_zones=["480.6"],
            downside_zones=["420.4"],
            evidence={"technical": ["技术方向: neutral"]},
            warnings=[],
            entry_triggers=["等待重新站上480.6并获得日线确认"],
            blocked_by=["街哥技术信号未形成共振"],
            timeframe_state="周线中性，日线买点确认，等待4H触发",
        )

        report = render_text_report(advice)

        self.assertIn("结果摘要:", report)
        self.assertIn("当前价: 465。", report)
        self.assertIn("结论: 暂时不买，空仓等确认。", report)
        self.assertIn("原因: 街哥技术信号未形成共振。", report)
        self.assertIn("再观察条件: 等待重新站上480.6并获得日线确认。", report)
        self.assertIn("总建议: 观望", report)
        self.assertIn("依据:", report)
        self.assertNotIn("裸K", report)
