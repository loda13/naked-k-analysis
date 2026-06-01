from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List


@dataclass(frozen=True)
class ResolvedTimeframes:
    timeframes: List[str]
    warnings: List[str] = field(default_factory=list)
    uses_daily_proxy_for_4h: bool = False


def normalize_provider_ticker(ticker: str) -> str:
    code = ticker.strip()
    upper = code.upper()
    lower = code.lower()

    if lower.startswith(("hk", "sh", "sz", "bj", "us")):
        return lower[:2] + code[2:].upper()
    if upper.endswith(".HK"):
        return f"hk{upper.removesuffix('.HK').zfill(5)}"
    if upper.endswith(".SS"):
        return f"sh{upper.removesuffix('.SS')}"
    if upper.endswith(".SZ"):
        return f"sz{upper.removesuffix('.SZ')}"
    if upper.endswith(".BJ"):
        return f"bj{upper.removesuffix('.BJ')}"
    return f"us{upper}"


def classify_market(ticker: str) -> str:
    normalized = normalize_provider_ticker(ticker)
    if normalized.startswith("hk"):
        return "hk"
    if normalized.startswith(("sh", "sz", "bj")):
        return "cn"
    return "us"


def resolve_technical_timeframes(timeframes: Iterable[str] | None) -> ResolvedTimeframes:
    selected = list(timeframes or ["daily", "weekly"])
    warnings: List[str] = []
    uses_daily_proxy = any(tf.lower() in {"4h", "4小时"} for tf in selected)
    if uses_daily_proxy:
        warnings.append("4H数据源暂不可用，当前短线4H分析为日线替代")

    return ResolvedTimeframes(
        timeframes=selected,
        warnings=warnings,
        uses_daily_proxy_for_4h=uses_daily_proxy,
    )
