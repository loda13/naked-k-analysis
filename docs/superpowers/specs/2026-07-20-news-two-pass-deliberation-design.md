# 裸 K + 消息面两轮斟酌设计

**日期：** 2026-07-20
**状态：** 已完成口头设计确认，待书面规格确认
**范围：** 为现有裸 K 收盘分析增加可选消息面采集、Anthropic-compatible 两轮大模型斟酌和综合交易结论。

## 1. 目标

系统必须在保留纯裸 K 技术分析的同时，补充可追溯的消息面分析，并输出三层清晰结论：

1. **技术面结论**：由现有确定性 OHLCV/价格结构引擎生成。
2. **消息面结论**：由第一轮大模型严格基于已采集新闻证据生成。
3. **综合结论**：由第二轮大模型斟酌技术面、原始新闻和第一轮结论后生成。

消息面可以把技术面的 `观望`、`减仓` 或 `回避` 升级为 `小仓试错` 或 `买入`，也可以把技术面的 `买入` 或 `小仓试错` 降级为 `观望`、`减仓` 或 `回避`。不使用固定加权公式或固定融合矩阵。

## 2. 非目标与不变边界

- 不恢复已经移除的 MA、EMA、MACD、RSI、BOLL 或多指标评分系统。
- 不让大模型发明 K 线、价格、触发位、止损位、目标位或新闻来源。
- 不把大模型判断写回纯形态检测模块 `naked_k_patterns.py`。
- 不绕过现有账户回撤、盈亏比、仓位上限和组合暴露保护。
- 不要求新的付费新闻 API key。
- 不在代码、报告、JSON、审计日志、测试夹具或设计文档中保存真实 API key。

## 3. 总体架构

单个标的按以下顺序处理：

1. 现有裸 K 引擎生成完整技术计划。
2. 新闻采集器读取无需额外凭证的公开新闻。
3. 新闻归一化、时间过滤和去重。
4. 第一轮大模型只审查消息面，生成结构化消息结论。
5. 第二轮大模型读取技术计划、原始新闻和第一轮结论，生成综合动作。
6. 如果综合方向与原技术方向不同，确定性价格函数按综合方向重建触发位和失效位。
7. 现有风险与组合保护基于综合动作重新计算。
8. Markdown、JSON、journal 和 audit 同时保留技术、消息和综合三层结果。

建议新增三个职责单一的模块：

- `naked_k_news.py`：新闻采集、归一化、去重、时效处理和安全裁剪。
- `naked_k_news_llm.py`：Anthropic-compatible 请求、两轮提示词、响应解析与字段验证。
- `naked_k_synthesis.py`：保存技术快照、应用第二轮动作、按方向重建价格计划并重新执行风险保护。

现有 `naked_k_llm.py` 的 OpenAI-compatible 复盘能力保持兼容，不强行与消息面两轮斟酌混成同一接口实现。

## 4. 新闻采集

### 4.1 数据源

不引入额外凭证，按以下顺序获取：

1. 使用仓库已有依赖 `yfinance` 的 `Search` 新闻结果。
2. 使用 Google News RSS 按公司名和 ticker 搜索，作为补充和降级来源。

任一来源失败不得中断裸 K 主流程。两个来源均失败时，消息面状态为 `unavailable`。

### 4.2 时间范围与数量

- 主窗口：最近 7 个自然日。
- 每个标的最多向模型发送 12 条去重新闻。
- 主窗口没有有效新闻时，可回看最近 30 日，但必须标记 `low_freshness`。
- 超过 30 日的消息不进入当前综合决策。

### 4.3 标准化字段

每条消息至少包含：

```json
{
  "id": "news-01",
  "title": "新闻标题",
  "publisher": "媒体或公告来源",
  "published_at": "2026-07-20T08:00:00+08:00",
  "url": "https://example.com/article",
  "summary": "来源提供的短摘要，可为空",
  "source_provider": "yahoo_finance",
  "freshness": "fresh"
}
```

去重使用规范化标题和规范化 URL。提示词只发送必要的标题、短摘要、媒体、时间和 URL，不抓取或复制整篇受版权保护的文章。

## 5. Anthropic-compatible 配置

### 5.1 环境变量

消息面客户端接受以下变量，系统环境变量优先于 `.env`：

- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_AUTH_TOKEN`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`
- `NAKED_K_NEWS_MODEL`

模型优先级为 `NAKED_K_NEWS_MODEL`、`ANTHROPIC_MODEL`。认证优先读取 `ANTHROPIC_AUTH_TOKEN`，其次读取 `ANTHROPIC_API_KEY`。继续兼容现有 `NAKED_K_LLM_*` / `LLM_*` 配置，但消息面文档优先展示 Anthropic 变量。

### 5.2 端点规则

用户提供的 Base URL 是一个有路径前缀的 New API 网关。不得擅自裁剪到站点根路径：

```text
Base URL: https://one.iflytek.com/api/llm/console/chat
Messages: <Base URL>/v1/messages
Models:   <Base URL>/v1/models
```

无密钥只读探测已确认这两个追加路径进入 New API 鉴权层并返回结构化 `401 Unauthorized`；站点根路径 `/v1/messages` 会被 WAF 拦截，因此实现必须保留 Base URL 的完整路径前缀。

请求头包含：

- `content-type: application/json`
- `anthropic-version: 2023-06-01`
- `x-api-key: <redacted>`
- `Authorization: Bearer <redacted>`

同时发送两种认证头，以兼容 Anthropic SDK 语义与 New API 网关。任何日志与异常都必须先脱敏。

### 5.3 模型发现

- 明确配置模型时直接使用。
- 未配置模型时调用 `<Base URL>/v1/models`。
- 如果只返回一个可用文本聊天模型，自动采用。
- 如果返回多个模型，不猜测“最佳模型”；CLI 输出可用模型 ID，并要求通过环境变量或 `--news-model` 明确选择。

## 6. 第一轮：独立消息面审查

第一轮角色是“消息面审查员”。输入仅包含公司名、ticker、运行时间和标准化新闻，不包含技术动作、价格计划或仓位，避免技术结论对消息判断造成锚定。

输出必须是 JSON 对象：

```json
{
  "status": "ok",
  "direction": "strong_bullish",
  "score": 2,
  "confidence": 86,
  "materiality": "high",
  "horizon": "short_term",
  "summary": "消息面结论",
  "positive_factors": ["利多因素"],
  "negative_factors": ["利空因素"],
  "evidence_ids": ["news-01", "news-03"],
  "uncertainties": ["尚未确认的风险"],
  "data_quality": "sufficient"
}
```

约束：

- `score` 只允许 `-2`、`-1`、`0`、`1`、`2`，用于清晰展示消息强弱，但不参与固定融合公式。
- `confidence` 为 `0..100`。
- `direction` 只允许 `strong_bearish`、`bearish`、`neutral`、`bullish`、`strong_bullish`。
- `materiality` 只允许 `low`、`medium`、`high`。
- `horizon` 只允许 `immediate`、`short_term`、`medium_term`。
- `evidence_ids` 必须全部存在于本轮输入；不存在的引用使第一轮无效。
- 没有足够新闻时必须输出 `data_quality=insufficient`，不得依赖模型训练记忆补新闻。

## 7. 第二轮：综合斟酌

第二轮角色是“投资决策审查委员会”。输入包括：

- 不可变的技术计划快照。
- 标准化原始新闻。
- 第一轮完整消息结论。
- 现有风险上下文与组合约束。

第二轮不使用固定权重、固定加总公式或固定动作矩阵。模型必须显式比较技术面与消息面，解释一致或冲突之处，然后选择最终动作。

输出必须是 JSON 对象：

```json
{
  "status": "ok",
  "technical_view": {
    "action": "观望",
    "summary": "对输入技术结论的准确复述"
  },
  "news_view": {
    "direction": "strong_bullish",
    "summary": "对第一轮结论的准确复述"
  },
  "conflict_analysis": "消息面为何足以或不足以改变技术动作",
  "model_action": "买入",
  "confidence": 78,
  "decision_reasons": ["综合理由"],
  "risk_flags": ["主要风险"],
  "evidence_ids": ["news-01", "news-03"],
  "execution_note": "等待裸K引擎生成的新方向触发条件"
}
```

约束：

- `model_action` 只允许 `买入`、`小仓试错`、`观望`、`减仓`、`回避`。
- `technical_view.action` 必须等于输入的技术动作；否则第二轮无效。
- 第二轮引用的证据必须来自第一轮有效引用或原始新闻列表。
- 大模型可以改变动作，但不能输出或覆盖任何价格字段。
- 第二轮使用低随机性配置，默认 `temperature=0.1`。

## 8. 动作应用与风险保护

`InstrumentReport` 保留不可变 `technical_conclusion`，其中包含原始技术动作、信号状态、触发位、失效位、目标位、盈亏比、仓位和风险计划。

执行层使用以下唯一方向映射：

- `买入`、`小仓试错` → `long`
- `减仓`、`回避` → `bearish_defensive`
- `观望` → `neutral`

`bearish_defensive` 表示降低或避免多头风险，不代表系统自动建立裸空仓。其向下触发位用于确认风险兑现，向上失效位用于确认利空判断失效。

第二轮有效时：

1. `combined_conclusion.model_action` 作为大模型建议进入确定性执行层。
2. 如果 `model_action` 的方向与技术动作方向不同，使用最新已收盘日 K、现有 ATR 缓冲、支撑/压力区和裸 K helper 重新生成对应方向的 `entry_trigger` 与 `stop_loss`：`long` 使用向上突破/向下失效，`bearish_defensive` 使用向下触发/向上失效。
3. `target_price` 只使用有效结构区域；不存在有效结构目标时保持为空，由现有 `1R/2R/3R` 风险路径提供管理参考。
4. 重新计算 `signal_state`、单股风险、目标盈亏比、仓位建议和 `risk_plan`。
5. 重新运行现有盈亏比、账户回撤和组合暴露保护；保护后的动作写入
   `combined_conclusion.final_action`，并成为报告顶层 `action`。
6. 如果风险保护后的 `final_action != model_action`，必须再按 `final_action` 应用
   下述动作转换语义：不同方向时同步触发位、失效位、目标位、仓位和信号状态；
   同方向降级时至少重新计算动作上限、仓位和风险状态。该同步只执行一次，不再次
   调用大模型，也不形成风控循环。

动作转换的价格计划语义固定如下：

- `long → bearish_defensive`：取消原多头待触发计划，重建防守触发/失效位；`减仓` 按仓位上限降低敞口，`回避` 不建立新仓。
- `bearish_defensive → long`：原防守计划只保留在技术快照，重建多头触发/止损位并重新计算仓位。
- 任意方向 `→ neutral`：取消方向性执行，顶层触发/失效位只作观察边界，`target_price` 为空，仓位使用观望上限。
- `neutral → long/bearish_defensive`：按目标方向从最新已收盘日 K 重建计划。
- 同方向内的动作变化（如 `买入 → 小仓试错`、`减仓 → 回避`）：保留价格方向与价位，只重新计算仓位和风险状态。

风险保护可以降低或阻断模型动作，但必须在报告中分开显示：

- `model_action`：第二轮大模型选择。
- `final_action`：经过确定性风险保护后的最终动作。
- `risk_override_reason`：若两者不同，说明具体保护原因。

这不是固定“技术 + 消息”融合规则，而是执行层安全边界。

## 9. 报告与持久化

### 9.1 InstrumentReport 新字段

- `technical_conclusion: dict`
- `news_analysis: dict`
- `combined_conclusion: dict`

`news_analysis` 包含采集状态、新闻列表摘要、第一轮结果、模型和调用状态。`combined_conclusion` 包含第二轮结果、模型动作、最终动作和风险保护说明。

### 9.2 Markdown

每个标的新增以下连续区块：

- `技术面结论`
- `消息面结论`
- `技术与消息冲突/一致性`
- `综合结论`
- `消息来源`

`今日结论` 和组合风险排名使用最终动作，而不是原始技术动作。

### 9.3 JSON、journal 与 audit

- JSON 与 journal 保存三层结构和新闻元数据。
- audit 新增 `news_collected`、`news_assessed`、`decision_deliberated`、`signal_synthesized` 事件。
- audit 只记录 provider、model、状态、新闻数量、最终动作和错误类型，不记录认证头、API key 或完整提示词。

## 10. CLI 行为

新增：

- `--news`：启用公开新闻采集、两轮模型斟酌和综合动作。
- `--news-model MODEL`：覆盖环境变量中的消息分析模型。
- `--news-lookback-days N`：主窗口，默认 `7`。
- `--news-max-items N`：每个标的上限，默认 `12`。

现有 `--llm` 继续代表 OpenAI-compatible 复盘文本增强，避免破坏已有用户。`--news` 可独立使用；两者同时使用时分别执行且互不覆盖。

默认未启用 `--news` 时，所有现有纯裸 K 行为、输出与测试保持不变。

## 11. 失败与降级

- 一个新闻来源失败：使用另一个来源并记录 warning。
- 所有新闻来源失败或无新闻：展示 `消息面不可用/不足`，最终动作使用技术动作。
- 第一轮请求、解析或验证失败：不执行第二轮，最终动作使用技术动作。
- 第一轮成功、第二轮失败：报告仍展示消息结论，但最终动作使用技术动作。
- 第二轮输出非法动作、篡改技术动作或引用不存在证据：视为无效并退回技术动作。
- 重新生成价格计划失败：保留模型结论供阅读，但执行动作退回技术动作。
- 任一消息面故障不得中断其他标的或纯裸 K 报告生成。

## 12. 测试策略

所有信号行为按 TDD 修改，网络调用全部使用注入的 fake/session，不依赖实时外网。

必须覆盖：

1. Yahoo 与 Google RSS 标准化、时间过滤、去重、7 日主窗口和 30 日降级。
2. Base URL 完整路径保留，以及 `/v1/messages`、`/v1/models` 拼接。
3. `ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_API_KEY`、模型配置优先级和脱敏。
4. 第一轮请求不包含技术动作。
5. 第一轮结构化响应、证据 ID 和枚举验证。
6. 第二轮同时包含技术快照、原始新闻和第一轮结果。
7. 第二轮允许把观望升级为买入、把买入降级为回避。
8. 第二轮不能篡改技术快照或注入价格。
9. 动作方向改变后，由确定性 helper 重建触发位、失效位和风险计划。
10. 风险保护能够覆盖模型动作，并保留两者差异说明。
11. 两轮任一失败时的技术结论降级路径。
12. Markdown、JSON、journal 和 audit 的三层输出，以及密钥不泄漏。
13. 未启用 `--news` 时的完整回归测试。

最终验证命令：

```bash
python -m unittest discover -v
```

在用户将轮换后的 key 仅写入本地 `.env` 后，可额外执行一次不打印配置的真实烟雾测试。真实请求不是单元测试通过的前置条件。

## 13. 验收标准

- 报告对每个标的清楚展示技术面、消息面和综合结论。
- 第一轮不接触技术动作；第二轮可自由升级或降级动作。
- 综合过程没有固定权重公式。
- 每项消息判断都有可验证的输入新闻证据。
- 模型不能生成价格；方向变化后的价格计划来自裸 K 确定性函数。
- 消息面失败时仍能稳定生成纯技术报告。
- 真实 API key 不出现在 git diff、输出文件、审计日志和异常消息中。
- 所有自动化测试通过，且用户当前未提交的韩国市场修改得到保留。
