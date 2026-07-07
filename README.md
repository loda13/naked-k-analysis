# Naked K Analysis

裸 K 分析 CLI。项目只专注于 K 线本身：实体、影线、收盘位置、前高/前低、结构性突破/假突破、孕线、吞没、Pin Bar、十字星、确认 K、止损触发和复盘日志。

当前版本：[v3.0.0](https://github.com/loda13/naked-k-analysis/releases/tag/v3.0.0)

## 核心能力

- **裸 K 收盘计划**：用日线 / 周线 K 线生成动作、触发位、失效位、第一目标和目标盈亏比。
- **读线结构化**：输出最新 K 线实体强弱、上下影线、收盘位置、前高/前低突破或失败、趋势结构、回撤深度、波动扩张/压缩和高低点节奏。
- **市场结构识别**：识别 swing high/low、HH/HL、LH/LL、BOS 和 CHoCH，把单根 K 线放回结构背景中解释。
- **市场状态识别**：区分趋势市场、震荡市场、高波动市场和低波动压缩阶段，作为后续交易剧本的上层过滤。
- **交易剧本分类**：把 BOS 延续、CHoCH 反转、假突破反打、压缩等待扩张等市场行为归类为可复盘 setup。
- **多周期交易框架**：月线定义长期方向，周线定义主要结构，日线寻找交易机会，1H 只做入场触发/失效确认。
- **上下文化 K 线行为**：Pin Bar、孕线、吞没和流动性扫单会结合位置、结构、量能、波动、影线质量和确认条件解释，不再机械输出形态标签。
- **关键价格区域**：用 swing 聚类识别供需区、支撑/压力区、上下方流动性池、POC、价值区域、Anchored VWAP 和成交密集区，不再只依赖单一水平线。
- **量价确认**：识别放量突破、放量跌破、下破收回、上破失败和缩量突破待确认，帮助区分确认 K 与假突破压力。
- **标准形态识别**：覆盖看涨/看跌吸收、Pin Bar、十字星、锤子线、射击之星、早晨星、黄昏星、孕线。
- **确认 K 触发**：多头先突破信号 K 高点，空头先跌破信号 K 低点，避免只凭单根形态追价。
- **ATR 自适应缓冲**：触发位和止损位最低缓冲 0.2%，高波动股票自动放宽。
- **结构化风险计划**：输出单笔风险、账户风险预算、建议仓位、1R/2R/3R 目标、最大回撤保护和连续亏损降风险状态。
- **参数配置层**：账户风险、回撤阈值、连续亏损保护、动作仓位上限和组合暴露上限可通过 JSON 配置覆盖。
- **组合风险暴露**：汇总总仓位、方向暴露、市场暴露、单标的暴露和账户风险暴露，并在超限时输出 guardrails。
- **事件回测底座**：逐根 K 线推进，用信号日前历史生成计划，用下一根 K 线验证触发 / 止损 / 目标；提供 Walk Forward、R 倍数绩效和 Monte Carlo 风险重排。
- **市场周期验证**：回测结果按趋势、震荡、高波动、低波动压缩和熊市分桶，输出各周期绩效、缺失周期和鲁棒性风险。
- **交易员式简报**：把市场状态、多空力量、关键价格区域、可能路径、交易计划和风险点组织成复盘语言，避免“某指标金叉”式信号输出。
- **AI 交易助手**：基于确定性引擎 JSON 做解释、复盘、失败归因和历史样本胜率校准；AI 不允许改写动作、触发位、止损位、目标位或风控计划。
- **OpenAI-compatible LLM 增强**：可选调用 `/chat/completions` 生成交易复盘文本；默认关闭，失败不影响裸 K 主计划。
- **1H 盘中确认**：盘中只做触发 / 失效预警，不覆盖日线和周线主计划。
- **复盘日志**：每次运行写入 `reports/naked_k_journal.jsonl`，下一次会复盘上一根 K 的触发和失效情况。
- **结构化运行审计**：每次 CLI 运行写入 JSONL 审计事件，记录数据加载、计划生成、组合风险、运行完成和失败原因。
- **多数据源兜底**：优先 `westock-data`，再走腾讯 K 线、Yahoo chart JSON，最后用 yfinance。

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
```

## 报告字段

- `action`：`买入`、`小仓试错`、`观望`、`减仓`、`回避`
- `signal_state`：`planned_long`、`planned_short`、`watching`
- `price_action`：裸 K 解读，包括 K 线标签、结构信号、趋势结构、回撤深度、波动状态、量价状态、风险提示和收盘位置
- `entry_trigger`：突破 / 跌破信号 K 极值后的触发位
- `stop_loss`：信号失效位
- `target_price`：第一目标位，优先使用最近结构压力 / 支撑
- `risk_per_share`：单股风险
- `reward_to_risk`：第一目标对应的目标盈亏比
- `position_size`：按 1% 账户风险预算和动作上限反推的仓位上限
- `intraday_status`：1H 盘中状态，只做触发 / 失效预警
- `market_structure`：swing 结构、HH/HL 或 LH/LL 序列、BOS / CHoCH 事件和最近结构高低点
- `market_regime`：趋势 / 震荡 / 高波动 / 低波动压缩状态、方向和最新波幅比
- `timeframe_context`：多周期框架，包括月线长期方向、周线主要结构、日线机会、1H 触发状态和周期一致性过滤
- `trade_setup`：交易剧本，包括 setup 名称、方向、质量、置信分、市场行为解释、确认条件和失效逻辑
- `price_zones`：关键价格区域，包括供需区、最近支撑/压力、流动性池和成交密集区
- `candle_context`：上下文化 K 线行为，包括行为类型、方向、位置、影线质量、收盘质量、量能背景、波动背景、结构背景、质量分和确认条件
- `risk_plan`：结构化风险计划，包括单笔风险、账户风险、建议仓位、R 目标、风控保护状态
- `trader_brief`：交易员式复盘，包括市场状态、多空力量、关键区域、可能路径、交易计划和风险点
- `ai_assistant`：AI 助手输入和输出边界，包括确定性引擎计划、市场上下文、历史样本校准、失败归因和禁止 AI 改写信号的规则
- `review`：上一条计划在当前 K 线中的触发、失效和错误类型

## 裸 K 逻辑

月线决定长期方向，周线决定主要结构，日线寻找交易机会，1H 只做入场触发 / 失效确认。

多周期框架：

- 月线不直接给入场信号，只回答长期方向是否支持当前交易计划。
- 周线负责判断主结构和大级别风险，避免日线信号逆着主要结构硬做。
- 日线负责识别 BOS、CHoCH、假突破、压缩扩张和交易机会。
- 1H 只验证触发位和失效位，不覆盖日线 / 周线计划。
- 当日线机会与月线 / 周线方向冲突时，系统标记为 `conflict`，优先降仓或等待重新确认。

市场结构：

- 先识别局部 swing high / swing low，再判断 HH/HL、LH/LL、扩张震荡或收敛震荡。
- 收盘突破前一个结构高点记为多头 BOS；下降结构中向上突破记为多头 CHoCH。
- 收盘跌破前一个结构低点记为空头 BOS；上升结构中向下跌破记为空头 CHoCH。
- CHoCH 只代表结构转换，不直接等同于趋势反转，需要后续回踩和小周期触发确认。

市场状态：

- 结构 HH/HL 或 LH/LL 且波动正常时，归类为趋势市场。
- 最新波幅显著放大时，归类为高波动市场，优先控制仓位和滑点。
- 最新波幅低于近期均值时，归类为低波动压缩，等待扩张方向。
- 结构未确认时，归类为震荡市场，优先关注区间边界和假突破。

交易剧本：

- 多头 BOS 趋势延续：HH/HL 结构中收盘突破结构高点，等待回踩不破突破位或小周期重新转强。
- 多头 CHoCH 反转试错：下降结构被向上打断，只代表结构转换，需要小周期 HL 和回踩确认。
- 上方流动性扫过失败：上破前高后收回，结合派发压力或放量失败，优先按假突破反打处理。
- 压缩后等待扩张：低波动收敛阶段不提前押方向，等待扩张 K 收盘和量价确认。

关键价格区域：

- 局部 swing low 聚类形成需求 / 支撑区，局部 swing high 聚类形成供给 / 压力区。
- 多次触碰的等高区域标记为上方买方流动性池，等低区域标记为下方卖方流动性池。
- 成交量按典型价格分箱，输出 POC 成交控制点、70% 价值区域和最近成交密集区，用作价格接受区域参考。
- Anchored VWAP 从最近结构 swing low / swing high 锚定，判断价格相对机构平均成本区的位置。
- 旧字段 `support` / `resistance` 继续保留，但优先使用最近供需区中点回填。

上下文化 K 线行为：

- Pin Bar、吞没、孕线、十字和流动性扫单会统一转成结构化 `candle_context`。
- 每个行为对象包含 `location`、`volume_context`、`volatility_context`、`structure_context`、`quality_score`、`interpretation` 和 `confirmation`。
- 孕线默认按压缩处理，需要等待母线高低点被收盘突破，不直接当作方向信号。
- 下破前低收回会被识别为 `liquidity_sweep`，只有结合支撑/流动性区、放量吸收和结构转换时才提高质量分。

价格行为上下文：

- 最近 K 线判断实体强弱、上下影线、收盘位置和前高 / 前低关系。
- 最近 5 根 K 线判断上升结构、下降结构或横盘结构。
- 最近波段判断回撤区间，包括浅回撤、健康回撤、深回撤观察和趋势破坏。
- 最新波幅与近 5 根平均波幅对比，识别突破扩张、跌破扩张、宽幅震荡和波幅压缩。
- 放量时优先判断量价确认、下破收回、上破失败和派发压力；缩量突破只作为待确认信号。

多头计划：

- 日线出现看涨形态，或收盘突破前 N 日高点。
- 周线偏多时可给 `买入`，周线未确认时降为 `小仓试错`。
- 触发位使用信号 K 高点加 ATR 缓冲。
- 失效位使用信号 K 低点减 ATR 缓冲。

空头 / 回避计划：

- 日线出现看跌形态，或上破前高失败、收盘跌破前 N 日低点。
- 周线偏空或中性时优先 `回避`，周线偏多时用 `减仓` 处理风险。
- 触发位使用信号 K 低点减 ATR 缓冲。
- 失效位使用信号 K 高点加 ATR 缓冲。

观察计划：

- 十字星、孕线、波幅收敛或区间内震荡时，不提前给方向。
- 等待下一根 K 线突破母线高低点或关键结构位。

风险计划：

- 多头和空头计划统一换算为 1R / 2R / 3R 价格路径。
- 建议仓位由账户风险预算除以单笔价格风险得出，再受动作上限约束。
- 当前回撤达到最大回撤阈值时，风险计划进入 `blocked`，暂停新仓。
- 连续亏损达到保护阈值时，风险计划进入 `reduced`，账户风险预算减半。

参数配置：

```json
{
  "risk": {
    "account_risk_pct": 0.8,
    "max_drawdown_pct": 6.0,
    "consecutive_loss_limit": 2,
    "consecutive_loss_risk_multiplier": 0.25,
    "action_gross_caps": {
      "买入": 20.0,
      "小仓试错": 8.0,
      "减仓": 5.0,
      "回避": 0.0,
      "观望": 0.0
    }
  },
  "portfolio": {
    "max_total_gross_pct": 60.0,
    "max_direction_gross_pct": 45.0,
    "max_market_gross_pct": 35.0,
    "max_single_name_gross_pct": 25.0,
    "max_total_account_risk_pct": 2.5
  }
}
```

组合暴露：

- 报告末尾输出组合风险摘要，包括总仓位、账户风险和超限保护项。
- 市场暴露按 ticker 自动归类为 `hk`、`cn`、`us` 或 `crypto`。
- 超过总仓位、方向、市场、单标的或账户风险上限时，状态进入 `over_limit`。

运行审计：

- `run_started` / `run_completed` 记录一次分析任务的起止、标的数量和生成计划数。
- `data_loaded` 记录每个 ticker、周期、数据源、行数和最新 K 线时间。
- `data_unavailable` 记录月线或 1H 增强数据缺失原因，不中断主计划。
- `plan_generated` 记录动作、信号状态、交易剧本、风险状态和周期一致性。
- `portfolio_exposure` 记录组合风险暴露；超限时事件级别为 `warning`。

回测底座：

- Walk Forward 窗口严格保证训练段结束时间早于测试段开始时间。
- 事件回测只把信号日前的历史窗口传给计划器，再用下一根 K 线执行，避免同一根 K 线既生成信号又结算。
- 未触发计划进入 `skipped`，不计入交易绩效；已完成交易统一换算为 R 倍数。
- 绩效以 R 倍数为核心，输出胜率、Profit Factor、平均 R、最大回撤、Recovery Factor 和 Sharpe Ratio。
- Monte Carlo 只重排已完成交易的 R 序列，用来观察收益和回撤分布，不生成未来信号。
- `cycle_validation` 会按市场周期分桶输出各周期指标、缺失周期和 `fragile` 鲁棒性标记，避免只看总收益掩盖某类市场失效。

交易员简报：

- 不输出“MACD 金叉 / RSI 超买超卖”这类指标信号。
- 使用价格行为、结构事件、供需区、量价状态和风险计划组织语言。
- 交易计划固定包含当前机会、胜率估计、盈亏比、建议仓位、失效位置和风险等级。
- 可能路径同时描述延续、失败和未触发三种情况，避免单一路径预测。

AI 交易助手：

- AI 输入来自确定性引擎的结构化 JSON，包括计划、结构、周期、区域、风险、K 线行为和交易员简报。
- `signal_boundary` 明确禁止 AI 改写 `action`、`entry_trigger`、`stop_loss`、`target_price` 和 `risk_plan`。
- `calibrated_edge` 只使用历史 R 倍数样本校准胜率；样本不足时不输出概率化胜率。
- `failure_attribution` 把假突破、未触发、周期冲突和上下文风险转成复盘归因。

LLM 增强：

```bash
# .env 已在 .gitignore 中忽略，可把本地 LLM 配置放这里
LLM_BASE_URL="https://ark.cn-beijing.volces.com/api/coding/v3"
LLM_MODEL="glm-5.2"
LLM_API_KEY="<your-api-key>"
LLM_MAX_TOKENS=3000

python naked_k_analysis.py --llm
```

- 兼容 OpenAI `/chat/completions` 协议，程序会自动拼接 `/chat/completions`。
- 也支持 `NAKED_K_LLM_BASE_URL`、`NAKED_K_LLM_MODEL`、`NAKED_K_LLM_API_KEY`。
- 默认读取本地 `.env`，同时仍支持系统环境变量；系统环境变量优先于 `.env`。
- 可用 `--llm-base-url` 和 `--llm-model` 覆盖环境变量；API key 只从 `.env` 或系统环境变量读取，不提供 CLI 参数，避免 shell history 泄露。
- LLM 调用结果写入 `ai_assistant.llm_commentary`；如果调用失败，只记录错误状态，不阻断主报告。
- audit 和 JSON 输出只记录 provider/model/status，不记录 API key。

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

## 免责声明

本项目是研究和交易辅助工具，不构成个性化投资建议。所有输出都应结合个人风险承受能力、持仓周期和独立判断使用。

## License

MIT
