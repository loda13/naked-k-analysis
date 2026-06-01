from __future__ import annotations

import json
from dataclasses import asdict

from .models import Advice


def advice_to_json(advice: Advice) -> str:
    return json.dumps(asdict(advice), ensure_ascii=False, indent=2)


def render_text_report(advice: Advice) -> str:
    lines = [
        f"📊 {advice.ticker} Wall Street Skill 综合分析",
        "",
        f"总建议: {advice.overall_action} | 置信度: {advice.confidence} | 仓位: {advice.position_guidance}",
        f"短期: {advice.short_term_action}",
        f"中期: {advice.medium_term_action}",
        f"长期: {advice.long_term_action}",
        f"失效线: {advice.invalidation}",
    ]
    if advice.upside_zones:
        lines.append("上方压力/目标: " + " / ".join(advice.upside_zones))
    if advice.downside_zones:
        lines.append("下方支撑/风险: " + " / ".join(advice.downside_zones))
    if advice.entry_triggers:
        lines.append("触发条件: " + "；".join(advice.entry_triggers))
    if advice.blocked_by:
        lines.append("阻塞因素: " + "；".join(advice.blocked_by))

    lines.append("")
    lines.append("依据:")
    labels = {
        "market": "市场",
        "research": "研究",
        "technical": "技术",
        "naked_k": "裸K",
        "earnings": "财报",
    }
    for key, items in advice.evidence.items():
        if not items:
            continue
        lines.append(f"- {labels.get(key, key)}: " + "；".join(items))

    if advice.warnings:
        lines.append("")
        lines.append("警告:")
        for warning in advice.warnings:
            lines.append(f"- {warning}")

    lines.append("")
    lines.append("免责声明: 这是分析辅助，不构成个性化投资建议。")
    return "\n".join(lines)
