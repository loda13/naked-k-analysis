from __future__ import annotations

import json
from dataclasses import asdict

from .models import Advice


def advice_to_json(advice: Advice) -> str:
    return json.dumps(asdict(advice), ensure_ascii=False, indent=2)


def _plain_action(advice: Advice) -> str:
    if advice.overall_action == "买入":
        return f"可以买，但按{advice.position_guidance}执行。"
    if advice.overall_action == "小仓试错":
        return "只适合小仓试错，不要重仓。"
    if advice.overall_action == "持有":
        return "已有仓位可以继续拿着，先不要加仓。"
    if advice.overall_action == "观望":
        return "暂时不买，空仓等确认。"
    if advice.overall_action == "减仓":
        return "先降低仓位，控制回撤。"
    if advice.overall_action == "卖出":
        return "风险偏高，优先退出或大幅降仓。"
    return f"{advice.overall_action}，仓位按{advice.position_guidance}处理。"


def _render_plain_conclusion(advice: Advice) -> list[str]:
    lines = ["结果摘要:"]
    if advice.current_price is not None:
        lines.append(f"- 当前价: {advice.current_price:g}。")
    lines.append(f"- 结论: {_plain_action(advice)}")
    if advice.blocked_by:
        lines.append("- 原因: " + "；".join(advice.blocked_by) + "。")
    elif advice.timeframe_state:
        lines.append(f"- 原因: {advice.timeframe_state}。")
    else:
        lines.append(f"- 原因: 当前综合信号指向{advice.overall_action}。")

    if advice.entry_triggers:
        lines.append("- 再观察条件: " + "；".join(advice.entry_triggers) + "。")
    if advice.invalidation and "暂无" not in advice.invalidation:
        lines.append(f"- 风险线: {advice.invalidation}，跌破或接近这里要先控制风险。")
    return lines


def render_text_report(advice: Advice) -> str:
    lines = [
        f"📊 {advice.ticker} 街哥核心战法分析",
        "",
        *_render_plain_conclusion(advice),
        "",
        f"总建议: {advice.overall_action} | 置信度: {advice.confidence} | 仓位: {advice.position_guidance}",
    ]
    if advice.current_price is not None:
        lines.append(f"当前价: {advice.current_price:g}")
    lines.extend(
        [
            f"短期: {advice.short_term_action}",
            f"中期: {advice.medium_term_action}",
            f"长期: {advice.long_term_action}",
            f"失效线: {advice.invalidation}",
        ]
    )
    if advice.timeframe_state:
        lines.append(f"多周期状态: {advice.timeframe_state}")
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
        "technical": "街哥核心战法",
    }
    for key, items in advice.evidence.items():
        if not items:
            continue
        lines.append(f"- {labels.get(key, key)}: " + "；".join(items))

    if advice.data_sources:
        lines.append("")
        lines.append("数据源:")
        technical_sources = advice.data_sources.get("technical") or {}
        if isinstance(technical_sources, dict):
            for horizon, source in technical_sources.items():
                if isinstance(source, dict):
                    lines.append(
                        f"- 技术 {horizon}: {source.get('source', 'unknown')} "
                        f"{source.get('interval', '')} rows={source.get('rows', '')} latest={source.get('latest', '')}"
                    )

    if advice.warnings:
        lines.append("")
        lines.append("警告:")
        for warning in advice.warnings:
            lines.append(f"- {warning}")

    lines.append("")
    lines.append("免责声明: 这是分析辅助，不构成个性化投资建议。")
    return "\n".join(lines)
