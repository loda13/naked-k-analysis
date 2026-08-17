# Naked K Analysis

裸 K 分析 CLI。纯价格结构驱动的交易计划生成器：从 OHLCV 和市场结构中识别 BOS/CHoCH、供需区、流动性扫单、**主力资金行为**，生成触发位、止损、目标和风险计划，可选叠加多源公开新闻的两轮消息面综合。不使用任何技术指标（无 MA/EMA/MACD/RSI/BOLL）。

当前版本：[v3.4.0](https://github.com/loda13/naked-k-analysis/releases/tag/v3.4.0)

## 核心能力

### 技术面：纯价格结构分析

- **市场结构识别**：识别 swing high/low、HH/HL/LH/LL 序列、BOS（突破延续）和 CHoCH（结构转换），把单根 K 线放回结构背景中解释。
- **关键价格区域**：用 swing 聚类识别供需区、支撑/压力、流动性池（买方/卖方扫单区）、POC、价值区域和 Anchored VWAP，不依赖单一水平线。
- **主力资金行为** ⭐ NEW：识别机构/大资金的吸筹、扫单、卖压衰竭等行为模式，输出概率评分（如"主力抄底概率 92%"）。纯 OHLCV 分析，无外部数据依赖。默认启用，可配置关闭。
- **上下文化形态**：Pin Bar、吞没、孕线、十字星会结合位置、结构、量能、波动和影线质量解释，不机械输出形态标签。
- **交易剧本分类**：BOS 延续、CHoCH 反转、假突破反打、压缩等待扩张等市场行为归类为可复盘 setup。
- **多周期框架**：月线定方向，周线定结构，日线找机会，1H 做触发/失效确认；周期冲突时降仓或等待。
- **触发与止损**：多头突破信号 K 高点触发、跌破低点失效；空头反之。ATR 自适应缓冲（最低 0.2%），高波动自动放宽。
- **风险计划**：输出 1R/2R/3R 目标、建议仓位、账户风险预算、最大回撤保护和连续亏损降风险状态。
- **组合风险暴露**：汇总总仓位、方向暴露、市场暴露、单标的暴露和账户风险，超限时输出 guardrails。

### 消息面：多源公开新闻 + 两轮综合（可选）

- **多源采集**：Yahoo Finance + Google News RSS（默认）+ Finnhub 专业财经（SeekingAlpha/Benzinga，可选）+ SEC EDGAR 重大事件文件（8-K/6-K，60 天窗口）+ AkShare 中文财经（东方财富，可选）+ 新浪 7x24 滚动（分钟级，可选）。
- **智能过滤**：相关性评分、质量权重（Finnhub 3.0x、SEC 5.0x、AkShare 2.0x、Sina 2.0x、Google 1.0x、Yahoo 0.5x）、单词边界匹配、市场流水表标题门。
- **两轮斟酌**（`--news`）：第一轮独立审查新闻（不见技术动作），第二轮综合技术快照与消息给出建议；每条 claim 必须引用证据 ID 并逐字摘录。
- **安全边界**：零宽/形近字/leetspeak 混淆检测隔离指令注入；增仓需交叉佐证门（≥2 个不同发布方、规范化命题指纹相同）；价格字段（触发/止损/目标）由确定性代码重建，模型不可改写。
- **降级保护**：单源失败不中断，全源不可用时回退纯技术；新闻不足标记为 insufficient 并跳过第二轮；异常时保留错误状态，不伪装成模型判断。

### 回测与验证

- **事件回测**：逐根 K 线推进，用信号日前历史生成计划，下一根验证触发/止损/目标；Walk Forward、R 倍数绩效、Monte Carlo 重排。
- **市场周期验证**：按趋势/震荡/高波动/低波动/熊市分桶，输出各周期绩效、缺失周期和鲁棒性风险。
- **复盘日志**：每次运行写入 `reports/naked_k_journal.jsonl`，下次复盘上一根 K 的触发/失效情况。

### 数据与市场

- **多数据源兜底**：westock-data CLI → 腾讯 K 线 → Yahoo chart JSON → yfinance，自动降级。
- **多市场支持**：港股 `.HK`、A 股 `.SS`/`.SZ`、北交所 `.BJ`、美股、韩股 `.KS`/`.KQ`。

## 安装

```bash
python -m pip install -r requirements.txt
```

依赖包括 `pandas`、`numpy`、`requests`、`yfinance`。如果本机配置了 `westock-data`，程序会优先使用它；否则自动尝试腾讯、Yahoo chart 和 yfinance。

## 使用

```bash
python naked_k_analysis.py
python naked_k_analysis.py --json
```

默认股票池：

- 腾讯：`0700.HK`
- 小米：`1810.HK`
- PDD：`PDD`
- 泡泡玛特：`9992.HK`

输出文件：

- 最新 Markdown 报告：`reports/naked_k_latest.md`
- 复盘日志：`reports/naked_k_journal.jsonl`
- 运行审计：`reports/naked_k_audit.jsonl`

可以用参数改输出路径：

```bash
python naked_k_analysis.py --report-path reports/today.md --journal-path reports/journal.jsonl
python naked_k_analysis.py --config-path config/naked_k.json
python naked_k_analysis.py --audit-path reports/audit.jsonl
python naked_k_analysis.py --llm
python naked_k_analysis.py --news
```

## 消息面两轮斟酌（可选）

`--news` 默认关闭。启用后，程序在纯裸 K 计划之外，收集多源公开新闻并生成可追溯的消息面和综合结论。

```bash
# 启用公开新闻和两轮综合斟酌
python naked_k_analysis.py --news

# 可选地覆盖模型、主窗口和每个标的的去重新闻上限
python naked_k_analysis.py --news --news-model your-selected-model-id \
  --news-lookback-days 7 --news-max-items 12
```

`--news` 与现有 `--llm` 相互独立：`--llm` 是 OpenAI-compatible 的交易复盘文本增强（写入 `ai_assistant.llm_commentary`）；`--news` 使用 Anthropic-compatible 的两轮消息面流程（写入 `news_analysis` 和 `combined_conclusion`）。两者可单独使用或同时使用，彼此不覆盖。

### 新闻来源

**无需配置（默认启用）**：
- **Yahoo Finance Search** + **Google News RSS**

**推荐配置（可选）**：
- **SEC EDGAR 重大事件文件**：8-K（美国本土发行人）和 6-K（外国私人发行人/中概 ADR），覆盖财报、并购、高管变动等。质量权重 5.0x，60 天窗口（8-K/6-K 是事件驱动的，围绕财报成簇出现、中间空几十天）。同日多份 filing 标题带 accession 后缀区分（`#122766` / `#122765`）。无 API key，自动跳过非美股。
- **Finnhub 专业财经新闻**：SeekingAlpha、Benzinga 等专业财经来源，相关新闻比例从 0% 提升至 71%（小米 1810.HK 实测）。质量权重 3.0x，30 天窗口。需免费 API key（60 calls/分钟，本项目每天仅 4 次调用），未配置时自动降级。
- **AkShare 中文财经新闻**：东方财富个股新闻，补上港股/A 股中文覆盖。质量权重 2.0x，30 天窗口。可选依赖（`pip install akshare`），未安装时自动降级。**必须命中标题才保留**（东方财富会混入全市场资金流水表，正文列出每个 ticker）。
- **新浪 7x24 滚动新闻**：分钟级市场消息，最快来源。质量权重 2.0x，实际窗口约 24 小时（endpoint 返回最近 2000 条全市场记录）。**headline-only 归因**（标题命中才归属该 ticker，正文命中不算）。

### 智能过滤与质量排序

- **相关性评分**：标题匹配 3.0 分/次，正文匹配 1.0 分/次；短 ASCII 关键词（≤3 字符）用单词边界匹配防止误报（`”mi”` 不匹配 `”million”`），CJK 用子串匹配（`小米` / `腾讯` 无单词边界）。
- **质量权重**：Finnhub 3.0x、SEC 5.0x、AkShare 2.0x、Sina 2.0x、Google 1.0x、Yahoo 0.5x。最终得分 = 相关性 × 质量权重。
- **市场流水表标题门**：AkShare 设 `requires_title_match`（其正文包含每个 ticker，仅靠正文分无法拦截）；Finnhub/SEC/Sina 设 `bypasses_gate`（已在上游按 symbol 筛选）。
- **去重与排序**：标题归一化（NFKC、小写、去标点）+ URL 规范化，按最终得分和时效排序后去重，保留前 12 条。

### 两轮与价格边界

**第一轮**（独立消息面审查）：只接收公司、ticker、运行时间和规范化新闻，**不接收**技术动作、触发价、止损、目标或仓位。输出结构化消息面结论，每条 claim 必须引用证据 ID。

**第二轮**（技术与消息综合）：审阅不可变的技术快照、原始新闻、第一轮结论和风险上下文，给出动作建议、一致/冲突解释和引用证据。可建议升级或降级动作，但**不能提供或改写价格字段**。

**安全边界**：
- **指令注入隔离**：零宽字符、形近字、leetspeak 混淆检测；新闻 ID/标题/摘要/媒体/时间/URL 任一字段被判定为指令式内容时在第一轮前隔离，不进入任一轮 prompt；第一轮输出若包含同类内容也会隔离。`news_analysis.quarantine` 只记录安全的状态、数量和证据 ID。
- **交叉佐证门**（增仓时）：必须 ≥2 个不同发布方（规范化后主域名不同）+ 规范化命题指纹相同（两条彼此无关的真实新闻不能拼成增仓依据）。不满足时保留技术动作，`override_reason_code` / `evidence_gate` 记录机器可读原因。
- **价格字段边界**：`entry_trigger`、`stop_loss`、`target_price`、仓位、R/R、风险计划由确定性代码生成和同步；`减仓` 残余仓位钳制为不高于技术基线。报告分别保留 `model_action`（模型建议）与 `final_action`（风控后）。

### 报告与安全降级

成功时 Markdown 显示：`技术面结论` → `消息面结论` → `技术与消息冲突/一致性` → `综合结论` → `消息来源`。

JSON 与 journal 同时保存 `technical_conclusion`、`news_analysis` 和 `combined_conclusion`。

**降级保护**：
- 单源失败：采集器使用其他来源，保留来源错误状态。
- 全源不可用或无有效新闻：跳过消息判断，保留安全状态/错误类型，回退纯技术。
- 新闻不足：标记 insufficient 并跳过第二轮，不伪装成模型判断。
- 某标的异常：保留错误状态，该标的回退技术动作，其他标的正常输出。

### Finnhub 快速配置（5 分钟）

1. 注册免费账号：https://finnhub.io/register
2. 获取 API Key
3. 添加到 `.env`：`FINNHUB_API_KEY=your_api_key_here`

**免费额度**：60 calls/分钟（本项目每天仅 4 次调用，完全在免费额度内）。  
**无 API Key 时**：自动降级到 Yahoo + Google + SEC，不会报错。  
**详细文档**：`FINNHUB_QUICKSTART.md`、`FINNHUB_SETUP.md`、`NEWS_OPTIMIZATION_SUMMARY.md`。

### AkShare 安装（可选）

```bash
python -m pip install akshare
```

未安装时自动降级为空列表，报告仍输出纯技术结论。

**实现要点**：
- **ticker 必须补零到 5 位**：`01810` 返回小米回购公告；`1810` 会匹配到”利润暴增1810%”无关标题。
- **时间戳按北京时间解析**：东方财富返回朴素本地时间，当作 UTC 处理会产生 8 小时误差。
- **窗口在客户端过滤**：接口忽略日期参数，固定返回约 10 条，不过滤会让数月前旧闻漏进报告。

### Anthropic-compatible 本地配置

只在 `.env`（被 `.gitignore` 忽略）或系统环境变量中保存配置。安全占位示例：

```dotenv
ANTHROPIC_BASE_URL=”https://one.iflytek.com/api/llm/console/chat”
ANTHROPIC_AUTH_TOKEN=”replace-me-with-a-rotated-local-token”
NAKED_K_NEWS_MODEL=”replace-me-with-one-model-id”
```

配置优先级（进程环境整体覆盖 `.env`，同一来源内按顺序选择）：
- Base URL：`ANTHROPIC_BASE_URL` → `NAKED_K_NEWS_BASE_URL` → `NAKED_K_LLM_BASE_URL` → `LLM_BASE_URL`
- 认证：`ANTHROPIC_AUTH_TOKEN` → `ANTHROPIC_API_KEY` → `NAKED_K_NEWS_API_KEY` → `NAKED_K_LLM_API_KEY` → `LLM_API_KEY`
- 模型：CLI `--news-model` 覆盖所有环境来源；否则依次为 `NAKED_K_NEWS_MODEL` → `ANTHROPIC_MODEL` → `NAKED_K_LLM_MODEL` → `LLM_MODEL`

未明确设置模型时，程序从 `/v1/models` 发现模型，排除 embedding/rerank/图像/音频/审核专用 ID。多个候选或能力含糊时不猜测，列出经脱敏的候选 ID 要求显式选择。

日志、audit、JSON 和异常只记录脱敏后的 provider/model/安全 endpoint origin/状态，不记录认证 token。

## 报告字段

**技术面核心**：
- `action`：`买入`、`小仓试错`、`观望`、`减仓`、`回避`
- `entry_trigger` / `stop_loss` / `target_price`：触发位、失效位、第一目标（R/R 计算基础）
- `market_structure`：swing 结构、HH/HL 或 LH/LL 序列、BOS/CHoCH 事件、最近结构高低点
- `market_regime`：趋势/震荡/高波动/低波动压缩状态、方向、最新波幅比
- `price_zones`：供需区、最近支撑/压力、流动性池、成交密集区
- `trade_setup`：交易剧本（BOS 延续、CHoCH 反转、假突破反打、压缩等待扩张等）
- `timeframe_context`：月线方向、周线结构、日线机会、1H 触发、周期一致性
- `candle_context`：上下文化 K 线行为（位置、影线质量、收盘质量、量能背景、结构背景、质量分、确认条件）
- `risk_plan`：单笔风险、账户风险、建议仓位、1R/2R/3R 目标、风控保护状态
- `trader_brief`：交易员式复盘（市场状态、多空力量、关键区域、可能路径、交易计划、风险点）

**消息面与综合（`--news` 启用时）**：
- `technical_conclusion`：不可变纯技术计划快照
- `news_analysis`：公开新闻采集状态、第一轮消息面结论、证据和安全调用状态
- `combined_conclusion`：第二轮模型建议、结构化证据 claims、冲突分析、`model_action`（模型建议）、证据安全门、`final_action`（风控后）、机器可读覆盖原因

**复盘与审计**：
- `review`：上一条计划在当前 K 线中的触发、失效和错误类型（`reports/naked_k_journal.jsonl`）
- `intraday_status`：1H 盘中状态（接近触发、盘中确认、接近失效位等）
- 运行审计：`run_started` / `data_loaded` / `plan_generated` / `portfolio_exposure` / `run_completed`（`reports/naked_k_audit.jsonl`）

## 裸 K 逻辑

**多周期框架**：月线定方向，周线定结构，日线找机会，1H 做触发/失效确认。日线机会与月线/周线方向冲突时标记 `conflict`，优先降仓或等待。

**市场结构**：
- 识别局部 swing high/low，判断 HH/HL、LH/LL、扩张震荡或收敛震荡。
- 收盘突破前结构高点 → 多头 BOS；下降结构中向上突破 → 多头 CHoCH。
- 收盘跌破前结构低点 → 空头 BOS；上升结构中向下跌破 → 空头 CHoCH。
- CHoCH 只代表结构转换，需后续回踩和小周期触发确认。

**市场状态**：
- HH/HL 或 LH/LL 且波动正常 → 趋势市场
- 波幅显著放大 → 高波动市场（控制仓位和滑点）
- 波幅低于近期均值 → 低波动压缩（等待扩张方向）
- 结构未确认 → 震荡市场（关注区间边界和假突破）

**交易剧本**：
- **多头 BOS 趋势延续**：HH/HL 结构中收盘突破结构高点，等待回踩不破突破位或小周期重新转强。
- **多头 CHoCH 反转试错**：下降结构被向上打断，需小周期 HL 和回踩确认。
- **上方流动性扫过失败**：上破前高后收回，结合派发压力或放量失败，按假突破反打处理。
- **压缩后等待扩张**：低波动收敛阶段不押方向，等待扩张 K 收盘和量价确认。

**关键价格区域**：
- 局部 swing low 聚类 → 需求/支撑区；swing high 聚类 → 供给/压力区。
- 多次触碰等高区域 → 上方买方流动性池；等低区域 → 下方卖方流动性池。
- 成交量按典型价格分箱，输出 POC 成交控制点、70% 价值区域和成交密集区。
- Anchored VWAP 从最近结构 swing 锚定，判断价格相对机构平均成本区位置。

**上下文化 K 线行为**：
- Pin Bar、吞没、孕线、十字、流动性扫单统一转成结构化 `candle_context`。
- 每个行为包含 `location`、`volume_context`、`volatility_context`、`structure_context`、`quality_score`、`interpretation`、`confirmation`。
- 孕线按压缩处理，需等待母线高低点被收盘突破，不直接当作方向信号。
- 下破前低收回识别为 `liquidity_sweep`，只有结合支撑/流动性区、放量吸收和结构转换时才提高质量分。

**价格行为上下文**：
- 最近 K 线：实体强弱、上下影线、收盘位置、前高/前低关系。
- 最近 5 根 K 线：上升/下降/横盘结构。
- 最近波段：回撤区间（浅回撤、健康回撤、深回撤观察、趋势破坏）。
- 最新波幅 vs 近 5 根平均：突破扩张、跌破扩张、宽幅震荡、波幅压缩。
- 放量：量价确认、下破收回、上破失败、派发压力；缩量突破 → 待确认信号。

**多头计划**：
- 日线看涨形态或收盘突破前 N 日高点。
- 周线偏多 → `买入`；周线未确认 → `小仓试错`。
- 触发位 = 信号 K 高点 + ATR 缓冲；失效位 = 信号 K 低点 - ATR 缓冲。

**空头/回避计划**：
- 日线看跌形态、上破前高失败或收盘跌破前 N 日低点。
- 周线偏空或中性 → `回避`；周线偏多 → `减仓`。
- 触发位 = 信号 K 低点 - ATR 缓冲；失效位 = 信号 K 高点 + ATR 缓冲。

**观察计划**：
- 十字星、孕线、波幅收敛或区间内震荡时不给方向。
- 等待下一根 K 线突破母线高低点或关键结构位。

**风险计划**：
- 多头和空头统一换算为 1R/2R/3R 价格路径。
- 建议仓位 = 账户风险预算 ÷ 单笔价格风险，再受动作上限约束。
- 回撤达最大阈值 → `blocked`（暂停新仓）；连续亏损达保护阈值 → `reduced`（账户风险预算减半）。

**参数配置**（JSON 可覆盖）：
```json
{
  “risk”: {
    “account_risk_pct”: 0.8,
    “max_drawdown_pct”: 6.0,
    “consecutive_loss_limit”: 2,
    “action_gross_caps”: {“买入”: 20.0, “小仓试错”: 8.0, “减仓”: 5.0}
  },
  “portfolio”: {
    “max_total_gross_pct”: 60.0,
    “max_direction_gross_pct”: 45.0,
    “max_market_gross_pct”: 35.0,
    “max_single_name_gross_pct”: 25.0,
    “max_total_account_risk_pct”: 2.5
  }
}
```

**组合暴露**：
- 报告末尾输出总仓位、账户风险和超限保护项。
- 市场暴露自动归类为 `hk`、`cn`、`us` 或 `crypto`。
- 超过总仓位、方向、市场、单标的或账户风险上限时 → `over_limit`。

## 盘中状态

- `接近触发`：最新有效 1H 价格距离触发位 1% 以内
- `盘中确认`：最近有效 1H 收盘站上多头触发位，或跌破空头触发位
- `盘中突破未确认` / `盘中跌破未确认`：盘中触碰触发位，但 1H 收盘未确认
- `接近失效位`：盘中价格接近止损 / 失效位
- `盘中数据未确认`：最新 1H K 线成交量为 0，等待有效 K 线

## 文件结构

- `naked_k_analysis.py`：CLI、报告、复盘日志和运行审计入口
- `naked_k_ai.py`：AI 交易助手边界、结构化 payload、历史样本校准和失败归因
- `naked_k_llm.py`：OpenAI-compatible LLM adapter、环境变量配置、请求构造、响应解析和密钥脱敏
- `naked_k_news.py`：公开新闻采集（yfinance Search / Google News RSS）、归一化去重和时效窗口
- `naked_k_news_finnhub.py`：Finnhub 专业财经新闻采集器（v3.2.0 新增）
- `naked_k_news_akshare.py`：AkShare 中文财经新闻采集器（东方财富个股新闻，可选依赖，v3.3.0 新增）
- `naked_k_news_enhanced.py`：多数据源智能合并、相关性评分、质量权重系统（v3.2.0 新增）
- `naked_k_news_llm.py`：两轮消息面斟酌、Anthropic Messages adapter、零宽/形近字/leetspeak 混淆检测、指令注入隔离和结构化证据引用校验
- `naked_k_synthesis.py`：消息与技术综合、交叉佐证门、规范化命题指纹、实际敞口比较和价格字段边界保护
- `naked_k_audit.py`：结构化 JSONL 审计日志，用于追踪数据加载、计划生成、组合风险和运行异常
- `naked_k_planner.py`：交易计划编排，把价格行为、结构、剧本、区域和风险计划组合成 `InstrumentReport`
- `naked_k_config.py`：交易参数配置，包含风险参数、动作仓位上限和组合暴露限制
- `naked_k_context.py`：上下文化 K 线行为，把形态、位置、结构、量能和确认条件组合成行为对象
- `naked_k_portfolio.py`：组合风险暴露评估，汇总总仓位、方向、市场、单标的和账户风险
- `naked_k_trade.py`：纯裸 K 交易工具，包括触发/失效位、ATR 缓冲、价格行为上下文、周线背景、报表摘要和上一计划复盘
- `naked_k_timeframes.py`：多周期框架，输出月线方向、周线结构、日线机会、1H 触发和周期一致性过滤
- `naked_k_backtest.py`：事件回测和评估底座，提供逐根 K 线执行、Walk Forward 窗口、R 倍数绩效指标和 Monte Carlo 风险重排
- `naked_k_interpreter.py`：交易员式解释层，生成市场状态、多空力量、路径、计划和风险点简报
- `naked_k_patterns.py`：纯 K 线形态检测
- `naked_k_structure.py`：市场结构、BOS / CHoCH 和 market regime 检测
- `naked_k_setups.py`：交易剧本分类，把结构 / 状态 / 量价组合成可复盘 setup
- `naked_k_zones.py`：供需区、流动性池和成交密集区检测
- `naked_k_risk.py`：结构化风险计划、R 目标、仓位上限和风险保护
- `westock_wrapper.py`：市场数据获取和 ticker 转换
- `tests/test_naked_k_analysis.py`：裸 K 计划和报告测试
- `tests/test_naked_k_ai.py`：AI 助手信号边界、样本校准和失败归因测试
- `tests/test_naked_k_llm.py`：OpenAI-compatible LLM adapter、密钥脱敏和请求解析测试
- `tests/test_naked_k_news.py`：公开新闻采集、归一化去重和时效窗口测试
- `tests/test_naked_k_news_finnhub.py`：Finnhub API 连接、数据格式和降级测试（v3.2.0 新增）
- `tests/test_naked_k_news_akshare.py`：AkShare ticker 补零、北京时间转换、窗口过滤和可选依赖降级测试（v3.3.0 新增）
- `tests/test_naked_k_news_enhanced.py`：多源合并、相关性评分、质量权重、单词边界匹配和 AkShare 标题门测试（v3.2.0 新增）
- `tests/test_naked_k_news_llm.py`：两轮消息面斟酌、零宽/形近字/leetspeak 混淆检测、指令注入隔离和证据引用校验测试
- `tests/test_naked_k_synthesis.py`：消息与技术综合、交叉佐证门、规范化命题指纹和实际敞口门测试
- `tests/test_naked_k_audit.py`：结构化运行审计 JSONL 测试
- `tests/test_naked_k_config.py`：JSON 参数配置测试
- `tests/test_naked_k_context.py`：上下文化 K 线行为测试
- `tests/test_naked_k_portfolio.py`：组合暴露和超限 guardrails 测试
- `tests/test_naked_k_planner.py`：交易计划编排和 CLI 兼容入口测试
- `tests/test_naked_k_timeframes.py`：多周期框架和周期冲突过滤测试
- `tests/test_naked_k_backtest.py`：Walk Forward、R 倍数绩效和 Monte Carlo 测试
- `tests/test_naked_k_interpreter.py`：交易员简报和非指标化输出测试
- `tests/test_naked_k_patterns.py`：K 线形态测试
- `tests/test_naked_k_structure.py`：市场结构和 market regime 测试
- `tests/test_naked_k_setups.py`：交易剧本分类测试
- `tests/test_naked_k_zones.py`：关键价格区域测试
- `tests/test_naked_k_risk.py`：风险计划和保护规则测试
- `tests/test_westock_wrapper.py`：数据源 fallback 测试

## 数据源

`westock_wrapper.py` 提供与 `yfinance.download()` 兼容的 `download()` API，按顺序尝试：

1. `westock-data` CLI，可通过 `WESTOCK_DATA_SCRIPT` 指定脚本路径
2. 腾讯 K 线接口：`web.ifzq.gtimg.cn`，备用 `proxy.finance.qq.com`
3. Yahoo chart JSON，绕过 yfinance cookie 预取，支持 1H 数据兜底
4. yfinance 官方库

常见 ticker 会自动转换：

- 港股：`0700.HK` -> `hk00700`
- A 股：`600703.SS` -> `sh600703`、`001391.SZ` -> `sz001391`
- 美股：`NVDA` -> `usNVDA`
- 韩股：`005930.KS` -> `kr005930`、`035720.KQ` -> `kr035720`

## 测试

```bash
python -m unittest discover -v
```

当前测试覆盖：

- 裸 K 形态识别
- 结构性突破、假突破、下破收回
- HH/HL、LH/LL、BOS、CHoCH 和 market regime
- BOS 延续、CHoCH 反转、假突破反打和压缩等待扩张 setup
- 月线 / 周线 / 日线 / 1H 多周期框架和周期冲突过滤
- 供需区、上下方流动性池和成交密集区
- POC、价值区域、Anchored VWAP 和上下文化 K 线行为对象
- 趋势结构、回撤深度、波动扩张/压缩和量价确认
- ATR 缓冲、触发位、失效位、第一目标和 R/R
- 结构化风险计划、1R/2R/3R 目标、最大回撤保护和连续亏损降风险
- JSON 参数配置和组合风险暴露限制
- 结构化运行审计事件和 CLI 编排层审计写入
- 事件回测、Walk Forward 聚合、R 倍数绩效指标和 Monte Carlo 风险重排
- 市场周期分桶验证、缺失周期覆盖和鲁棒性风险标记
- 交易员简报、路径推演和非指标化输出
- AI 助手边界、历史样本胜率校准和失败归因
- OpenAI-compatible LLM 请求构造、响应解析、错误脱敏和 CLI 编排接入
- 1H 盘中确认和零成交量过滤
- 未收盘日线 / 周线过滤
- 复盘日志去重和上一计划复盘
- 腾讯 / Yahoo / yfinance 数据源 fallback
- 韩国市场 ticker 转换和 Asia/Seoul 时区处理
- 消息面两轮斟酌、新闻采集、证据引用校验和安全降级
- 零宽字符 / 形近字 / leetspeak 混淆检测与指令注入隔离
- 交叉佐证门、规范化命题指纹和实际敞口门

## 免责声明

本项目是研究和交易辅助工具，不构成个性化投资建议。所有输出都应结合个人风险承受能力、持仓周期和独立判断使用。

## License

MIT — 见 [LICENSE](LICENSE)。

依赖均为宽松许可（pandas / numpy BSD-3-Clause，requests / yfinance Apache-2.0，可选 akshare MIT），与 MIT 分发无冲突。
