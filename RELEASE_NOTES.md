# v3.1.0 - 韩国市场与消息面安全加固

## 概述

本版本新增韩国市场（KOSPI / KOSDAQ）数据支持和时区处理，并对可选的消息面两轮斟酌功能进行了三轮安全加固，关闭零宽字符/形近字/leetspeak 混淆绕过指令注入隔离的向量，确保未经量化支持的动作变化不会进入报告。

## 新增

- 新增韩国市场支持：`.KS`（KOSPI）和 `.KQ`（KOSDAQ）ticker 转换，数据源 fallback 覆盖腾讯 K 线和 yfinance 韩股接口，时区处理使用 `Asia/Seoul`。
- 新增消息面两轮斟酌混淆检测：零宽字符（ZWSP/ZWJ/BOM/soft-hyphen）、格式字符（Cf）和非空白控制字符（Cc）剥离，百分号编码走私检测（每轮 decode 后重新剥离和折叠），组合附加符号（NFKD + 丢弃 Mn）和西里尔/希腊形近字折叠为小写 Latin 骨架，leetspeak 数字还原（0→o/1→l/3→e/4→a/5→s/7→t，豁免 2/6/8/9 以保护 B2B/H2O/Q2/5G），以及混合脚本结构检测（Latin 与非 Latin 非 CJK 字母混合的 token 失败关闭，CJK 豁免）。
- 新增规范化命题指纹（material-proposition fingerprint）：对交叉佐证门的两条 claim 规范化后取 Blake2b 指纹，确保两条真实但彼此无关的新闻不能拼成增仓依据。

## 变更

- 更新消息面安全边界文档：README 核心能力列表、消息面两轮斟酌章节、测试覆盖列表和文件结构列表全面反映零宽/形近字/leetspeak 混淆检测、交叉佐证门和实际敞口门。
- 扩展单元测试覆盖：韩国市场 ticker 转换和 Asia/Seoul 时区处理（`test_westock_wrapper.py`、`test_naked_k_analysis.py`、`test_naked_k_portfolio.py`），零宽字符/百分号编码走私/组合附加符号/西里尔希腊形近字/混合脚本/leetspeak 混淆检测（`test_naked_k_news_llm.py`），以及规范化命题指纹（`test_naked_k_synthesis.py`）。

## 安全

- 关闭消息面指令注入隔离的三类绕过向量：(1) 零宽/格式/控制字符与百分号编码走私，(2) 组合附加符号和西里尔/希腊形近字替换，(3) leetspeak 数字替换和混合脚本结构混淆。所有混淆检测仅作用于指令识别路径（`is_instruction_like_evidence`），证据接地和规范化命题指纹路径（`_normalized_evidence_text`）保持不变，避免破坏引用摘录的逐字匹配。
- 规范化命题指纹确保交叉佐证门比较的是两条新闻表达的**同一命题**，而非两条彼此无关但都真实的新闻（例如"营收增长"与"股价上涨"不能互相佐证同一风险变化）。
- 独立评审验证：三轮 TDD 修复后，由独立评审 agent 对所有目标向量（零宽/编码走私、形近字、混合脚本、leetspeak）逐一探测，最终结论为 CLEAR（无残留绕过，quarantine 边界完整）。

# v3.0.0 - Professional Naked K + AI Trading Assistant

## Summary

This release upgrades the project from a rule-based naked K CLI into a professional trading-assistance system centered on price action, market structure, multi-timeframe context, risk planning, backtesting, and AI-assisted review. The deterministic engine remains the source of truth; AI can explain and challenge the plan, but it cannot change trading signals.

## Added

- Added a market structure engine for swing high/low detection, HH/HL and LH/LL sequences, BOS, CHoCH, and market regime classification.
- Added a multi-timeframe framework: monthly direction, weekly structure, daily opportunity, and 1H trigger/invalidations.
- Added context-aware candle behavior objects for Pin Bar, inside bar, engulfing, liquidity sweep, failed breakout, long-wick rejection, and compression behavior.
- Added professional price zones: supply/demand zones, liquidity pools, volume profile POC/value area, high-volume nodes, and anchored VWAP.
- Added trade setup playbooks for BOS continuation, CHoCH reversal, failed breakout reversal, and compression expansion watch states.
- Added structured risk planning with account risk, position caps, 1R/2R/3R targets, maximum drawdown protection, consecutive-loss protection, and portfolio exposure guardrails.
- Added an event-driven backtest base with next-bar execution, walk-forward windows, R-multiple metrics, Monte Carlo reshuffling, and market-cycle validation.
- Added an AI trading assistant payload with strict signal boundaries, historical edge calibration, failure attribution, and trader-style journal notes.
- Added an OpenAI-compatible LLM adapter for optional `/chat/completions` review output, including local `.env` loading, Markdown fenced JSON parsing, and nonfatal error handling.
- Added structured JSONL audit events for data loading, plan generation, LLM commentary, portfolio exposure, and run completion.

## Changed

- Refactored the previous monolithic analysis flow into focused modules for planning, structure, zones, context, risk, portfolio, backtesting, auditing, LLM integration, and reporting.
- Updated the report language from simple pattern labels to market-behavior explanations, including buyer/seller pressure, failed breakout context, liquidity behavior, and multi-path trade planning.
- Expanded README documentation to cover the new architecture, CLI options, report fields, risk model, backtesting model, AI assistant, and LLM configuration.
- Expanded unit coverage from the original naked K tests to the full V1/V2 workflow, including structure, multi-timeframe analysis, zones, risk, portfolio, backtest, AI, LLM, and audit behavior.

## Security

- API keys are read only from ignored local `.env` files or environment variables; no CLI flag accepts a key.
- `.env` remains ignored by Git and is not part of the release.
- LLM config redaction and error sanitization prevent API keys from appearing in JSON output, audit logs, or failure messages.

# v2.1.0 - Naked K Context Enhancements

## Summary

This release deepens the naked K reading layer without bringing indicators back. The report now explains trend structure, pullback depth, volatility state, and volume-price confirmation inside the existing price-action context.

## Added

- Added short-window trend structure classification for upward, downward, and sideways price action.
- Added pullback context based on the latest close against the prior swing high/low range.
- Added volatility state classification for breakout expansion, breakdown expansion, wide-range chop, normal range, and compression.
- Added volume-pressure labels for volume-confirmed breakouts, breakdowns, failed breakouts, downside reclaim, and low-volume breakout warnings.
- Expanded report summaries so trend, pullback, volatility, and volume-pressure details appear in the naked K interpretation.

## Changed

- Updated the trade-plan improvement note to describe enhanced naked K context instead of only shadow, close-position, and prior high/low reading.
- Extended unit coverage for trend confirmation, bullish pullback depth, and volume-pressure reporting.

# v2.0.0 - Naked K Focus

## Summary

This release converts the project from a mixed technical-indicator advisor into `naked-k-analysis`, a focused naked candlestick analysis CLI.

## Changed

- Renamed the product direction to Naked K Analysis / 裸 K 分析.
- Made `naked_k_analysis.py` the primary and only analysis entry point.
- Extracted candlestick pattern detection into `naked_k_patterns.py`.
- Kept market data fallback in `westock_wrapper.py`.
- Rewrote README and developer notes around naked K analysis only.

## Removed

- Removed the old multi-indicator advisor.
- Removed the old MA/EMA, MACD, RSI, BOLL, value-zone, and score-based analysis modules.
- Removed legacy CLI and tests tied to the indicator advisor.

## Current Coverage

- Naked K pattern detection.
- Price-action structure reading.
- Trigger, invalidation, target, R/R, and position sizing.
- 1H intraday confirmation.
- Journal review and same-bar deduplication.
- Market data fallback through westock-data, Tencent, Yahoo chart, and yfinance.
