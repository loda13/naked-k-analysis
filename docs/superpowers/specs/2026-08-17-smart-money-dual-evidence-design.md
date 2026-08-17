# 主力动作双证据识别设计

**日期**：2026-08-17
**状态**：设计方向已确认，独立复核通过，待用户审阅
**首期市场**：港股
**首期标的**：0700.HK、1810.HK、9992.HK

## 1. 背景

当前 `naked_k_smart_money.py` 只使用 OHLCV、供需区和价格结构，通过人工规则输出“主力抄底/派发概率”。这套实现存在三个根本问题：

1. OHLCV 只能观察成交和价格结果，不能识别交易者身份；
2. 当前 `probability` 是规则强度分，不是历史样本校准后的概率；
3. 当前代码没有大单、超大单、主动买卖方向、卖空或托管持仓数据。

用户需要的不是一个模糊的“主力概率”，而是两类证据相互验证：

- **成交行为证据**：成交量、大额/超大额逐笔成交、上涨/下跌 tick 集中度、卖空等；
- **价格行为证据**：吸收抛压、扫流动性后收回、放量突破、缩量回踩、强势 K 线组合等。

本设计将“主力识别”重新定义为：**对专业资金可能留下的可观测行为进行确定性、可审计的代理判断，不声称识别真实机构身份。**

## 2. 目标

### 2.1 功能目标

1. 优先复用项目已有行情源；缺失部分只接免费公开数据。
2. 建立独立的逐笔成交代理层和 K 线行为证据层。
3. 两层同向时输出“符合主力进场/撤退迹象”；单层出现时明确降级。
4. 保留原始数据、字段定义、时间和来源，保证每个结论可复核。
5. 数据源失败时退化为纯裸 K，不影响原报告生成。
6. 在完成样本外验证前，主力证据不改变 `action`、触发位、止损位或仓位。

### 2.2 非目标

- 不识别具体机构、券商或最终受益人；
- 不把券商托管变化等同于机构买卖；
- 不重新引入 MA、MACD、RSI、BOLL 等指标体系；
- 不使用付费 Level 2、FullTick 或历史全盘数据作为首期依赖；
- 不把供应商的“主力净流入”标签直接当事实；
- 不把 trade print 称为原始订单，也不在缺少 bid/ask 时声称识别真实 aggressor side；
- 不在尚未校准时输出“主力概率 XX%”。

## 3. 方案选择

### 3.1 方案 A：仅使用现有 OHLCV

优点是零新增数据依赖、完全符合当前裸 K 架构。缺点是无法满足大单、超大单和主动买卖方向需求，只能输出“吸收样/派发样价格行为”。

**结论**：保留为降级路径，不作为完整方案。

### 3.2 方案 B：免费逐笔成交 + 现有 OHLCV + 官方辅助数据

成交代理层使用东方财富公开港股逐笔成交接口；价格层继续使用 Tencent/Yahoo/westock OHLCV；HKEX 当日卖空成交作为辅助证据。数据缺失时按层降级。

2026-08-17 的只读探测已确认东方财富接口能返回三只首期港股的当日逐笔记录：

| 标的 | 当日逐笔条数 |
|---|---:|
| 0700.HK | 27,647 |
| 1810.HK | 21,133 |
| 9992.HK | 8,188 |

优点是免费、覆盖当前标的，并能计算单笔成交金额和成交集中度。缺点是接口未正式文档化、历史逐笔覆盖没有保证、没有订单簿或真实主动方向。

**结论**：采用本方案。

### 3.3 方案 C：HKEX FullTick / Level 2

数据定义最完整，但属于收费和授权数据，超出首期约束。

**结论**：仅预留 provider 接口，不实施。

## 4. 总体架构

```text
现有 OHLCV providers                    免费公开 flow providers
Tencent / Yahoo / westock              Eastmoney trade prints
              |                         HKEX short-selling
              v                                  |
      price_action_evidence                       v
              |                          trade_flow_evidence
              +---------------+------------------+
                              v
                    dual_evidence_fusion
                              |
              +---------------+----------------+
              v                                v
       report / journal                    structured audit
```

三层职责严格分开：

1. **Provider 层**只获取、校验和标准化原始成交数据；
2. **Evidence 层**只描述观察到的资金或价格行为；
3. **Fusion 层**只判断两组证据是否一致，不修改交易计划。

## 5. 数据源设计

### 5.1 项目现有数据源

`westock_wrapper.py` 的回退链为 westock-data CLI、Tencent K 线、Yahoo Chart JSON、yfinance。它们只向主流程暴露 OHLCV，不能生成大单分类。

项目已安装 AkShare，但当前只用于东方财富新闻。AkShare 的个股资金流和大单接口主要覆盖沪深北市场，港股首期不复用这些接口。

### 5.2 东方财富港股逐笔成交

新增只读 provider，例如 `naked_k_flow_eastmoney.py`。首期探测使用：

- URL：`https://push2.eastmoney.com/api/qt/stock/details/get`；
- `secid=116.XXXXX`；
- `fields1=f1,f2,f3,f4,f5`；
- `fields2=f51,f52,f53,f54,f55`；
- `pos=-0&iscca=1&invt=2&fltt=2`。

2026-08-17 20:00 后的探测返回 `full=1`，并覆盖三只首期标的。接口未正式文档化，实施时必须提交去敏 raw fixture、请求参数指纹、响应 SHA-256 和字段探针，不能只依赖这次人工探测。

接口返回的是 trade prints，不是订单。可确认的原始语义仅限成交时间、成交价格、成交数量和供应商代码。供应商代码未完成独立验证前只保留原值。

设计要求：

- 港股代码映射为 `116.XXXXX`；
- 保存原始响应和规范化后的不可变快照；
- 快照路径为 `reports/market_data/trade_flow/YYYY-MM-DD/<ticker>/<retrieved_at>-<sha256>.raw.json.gz`，其中 `retrieved_at` 使用文件系统安全的 UTC 基本格式 `YYYYMMDDTHHMMSSffffffZ`；
- 同目录 manifest 使用 append-only JSONL，临时文件写完后原子 rename；另设可覆盖的 `latest.json` 指针；
- 记录 `retrieved_at`、`session_date`、时区和响应摘要；
- 记录 `schema_version`、currency、price/volume unit、request fingerprint、source sequence、覆盖起止时间和质量统计；
- 对字段数、价格、数量、时间顺序、合法重复行、截断、`full` 标志和交易日进行验证；
- provider 没有 trade ID 时，`source_row_id` 使用响应内 ordinal 与 occurrence index，不能按相同行内容去重；
- 供应商方向代码未完成语义验证前，仅存为 `side_raw`；
- 无 bid/ask 时只计算 `tick_direction=uptick|downtick|zero_tick|unknown`，永不命名为主动买/卖；
- 开盘前、连续交易和连续交易结束后的窗口分别统计；在没有经过验证的 trade-type 字段时，16:00 后只能称为 `post_continuous_window`，不能断言每笔都是 CAS 成交；
- 远端失败、schema 变化或数据不完整时返回结构化状态，不抛出导致报告失败的异常。

免费接口的历史可用性没有保证，因此系统从首次上线起按交易日保存快照。不能用当前接口补造过去不存在的逐笔历史。

### 5.2.1 港股交易时点

新增可注入的 `MarketSession`/交易日历边界，主流程不得继续把 16:00 简单视为完整收盘：

- 正常交易日保守到 16:10 才允许 `session_complete=true`；
- 半日市保守到 12:10；
- 当前时钟、交易日历或特殊停市状态无法确认时返回 `PARTIAL`；
- 16:00、16:09、16:10、周五周线和半日市必须有边界测试；
- 依赖完整当日分布的证据统一 `tradable_at=next_session_open`。

交易日历通过接口注入，测试使用固定 calendar fixture；生产适配器必须显式给出正常日、半日市、休市和未知状态，planner 不自行猜测。

### 5.3 HKEX 辅助数据

首期接入 HKEX 当日卖空成交，形成独立 `ShortSellingSnapshot`：

- `ticker`、`counter_currency`、`session_date`；
- `short_shares`、`short_turnover`；
- `total_turnover` 及其 provider；
- `short_turnover_ratio`；
- `eligible_state=reported_nonzero|not_reported|unsupported|unknown`；
- `retrieved_at`、`available_at`、`status`、`source_url` 和 `snapshot_id`。

总成交额优先使用东方财富逐笔 `sum(price * volume)`；同源 quote amount 存在且定义、币种可比时做容差核对，两者偏差超过 2% 时返回 `DEFINITION_MISMATCH`。quote amount 不存在时记录 `reconciliation=NOT_COMPUTABLE`，不凭空判 mismatch。人民币柜台和港币柜台分别计算，不能混币种。

`short_pressure` 只有在累计至少 20 个完整历史交易日后才可计算：当日卖空占比达到过去 20 日（不含当日）的 90% 分位时标记为高压。历史不足时只展示原始占比和 `BOOTSTRAP/NOT_COMPUTABLE`。即使达到阈值，首期也固定 `direction=neutral`，只做背景风险提示，不能单独生成 bearish/bullish 方向。

HKEX 当日报告中存在该 ticker 且数值大于零时为 `reported_nonzero`。报告缺行时首期一律为 `not_reported/NOT_COMPUTABLE`：单靠当日报告不能区分“designated security 但零卖空”与“不在适用名单”。`not_reported` 不得转换为零，首期不产生“可卖空但当日为零”的资格状态。

卖空数据不能直接证明机构做空，也不能与普通 downtick 成交简单相加；其 `available_at` 以实际页面成功抓取时间为准，最早用于下一交易日。

CCASS 持仓搜索可作为后续慢变量：

- 只描述结算参与者或托管席位变化；
- 明确结算滞后；
- 不推断最终受益人；
- 不与当日逐笔流量混成同一个分数。

### 5.4 数据状态

每个 provider 必须返回以下状态之一：

- `OK`：字段、日期、覆盖和完整性通过；
- `PARTIAL`：可使用但覆盖不完整；
- `STALE`：不是目标交易日或超过允许时效；
- `UNAVAILABLE`：接口不可达或该市场不支持；
- `DEFINITION_MISMATCH`：字段定义或单位无法确认；
- `INVALID`：数据违反基本约束。

缺失不能按零处理。`UNAVAILABLE` 表示未知，不表示没有大单。

## 6. 标准化数据契约

首期使用 versioned dataclass，并由序列化测试锁定 JSON schema。以下字段均为必填；未知数值使用 `null`，同时由状态字段解释，不能静默填零。

### 6.1 TradeFlowSnapshot

| 字段 | 类型 | 约束 |
|---|---|---|
| `schema_version` | string | 首期固定 `trade-flow.v1` |
| `ticker/market` | string | 规范化 ticker 与 `hk` |
| `session_date/timezone` | string | ISO date；`Asia/Hong_Kong` |
| `provider/source_url` | string | provider ID 与脱敏 URL |
| `request_fingerprint` | string | 规范化参数 SHA-256 |
| `status` | enum | 第 5.4 节状态 |
| `retrieved_at/coverage_start/coverage_end` | datetime | 有时区 ISO-8601 |
| `session_complete` | bool | 由 `MarketSession` 判定 |
| `currency/price_unit/volume_unit` | string | 首期必须明确为 HKD、每股价格和股数，否则 mismatch |
| `trade_count` | int | 非负 |
| `total_volume/total_notional` | number|null | 由规范化逐笔求和 |
| `classified_notional_coverage` | number | `[0,1]` |
| `raw_snapshot_id/normalized_snapshot_id` | string | `sha256:<64 hex>` |
| `limitations` | list[string] | 可为空 |

### 6.2 TradePrint

| 字段 | 类型 | 约束 |
|---|---|---|
| `source_ordinal` | int | 原响应顺序，不能因内容重复删除 |
| `occurrence_index` | int | 同内容重复的出现序号 |
| `trade_time` | datetime | 与 session date 合成的有时区时间 |
| `price/volume/notional` | number | 全部大于零；`notional=price*volume` |
| `session_phase` | enum | `pre_open|continuous|post_continuous_window|unknown` |
| `side_raw` | string|null | 原值，不解释身份 |
| `tick_direction` | enum | `uptick|downtick|zero_tick|unknown` |
| `classification_method` | enum | 首期固定 `tick_rule` |
| `source_row_id` | string | `source_ordinal:occurrence_index` |

tick rule：价格高于上一笔为 uptick，低于上一笔为 downtick；同价继承最近一次非零 tick 方向并保留 `zero_tick=true` 辅助字段；没有先前非零方向时为 unknown。

同一秒、同一价格、同一数量的记录即使内容完全相同，也可能是合法的多笔成交。规范化过程按 `source_ordinal` 全量保留，只用 `occurrence_index` 构造稳定身份，不按内容去重。

### 6.3 Evidence

所有证据统一包含：

- `evidence_id`；
- `family`：`trade_tape`、`short_selling`、`custody` 或 `price_action`；
- `kind`；
- `direction`：`bullish`、`bearish` 或 `neutral`；
- `observed_at`、`available_at`、`expires_at`；
- `inputs`、`thresholds` 和 `limitations`；
- `confirmation` 与 `invalidation`。

另加：

- `schema_version=evidence.v1`；
- `lineage_ids`：全部输入 snapshot/evidence ID；
- `dependency_group`：`trade_tape`、`short_selling`、`price_response` 或 `custody`；
- `target_session`、`tradable_at`；
- `validation_status=UNVALIDATED`；
- `quality=VALID|BOOTSTRAP|PARTIAL|STALE|UNAVAILABLE|DEFINITION_MISMATCH|INVALID`。

### 6.4 LayerResult

每一层先归一为完整状态，再进入融合：

| 字段 | 允许值 |
|---|---|
| `availability` | `available|partial|stale|unavailable|invalid` |
| `direction` | `bullish|bearish|neutral|conflict|unknown` |
| `lifecycle` | `observed|pending_confirmation|confirmed|invalidated|expired|not_computable` |
| `quality` | `VALID|BOOTSTRAP|PARTIAL|STALE|UNAVAILABLE|DEFINITION_MISMATCH|INVALID` |
| `as_of/valid_from/expires_at` | 有时区 datetime |
| `target_session` | ISO date |
| `evidence_ids/lineage_ids/limitations` | list[string] |

provider 到 layer 的映射固定如下：`OK` 且覆盖门槛通过映射为 `available/VALID`；`PARTIAL` 映射为 `partial/PARTIAL`；`STALE` 映射为 `stale/STALE`；`UNAVAILABLE` 映射为 `unavailable/UNAVAILABLE`；`DEFINITION_MISMATCH` 映射为 `invalid/DEFINITION_MISMATCH`；`INVALID` 映射为 `invalid/INVALID`。历史不足但当日 bootstrap 门槛通过时为 `available/BOOTSTRAP`；统计分母为零或样本不足时为 `lifecycle=not_computable`、`direction=unknown`。

每个 LayerResult 在融合前必须唯一归一为以下 `participation_state`，按表中从上到下的优先级匹配：

| 条件 | `participation_state` |
|---|---|
| `lifecycle=invalidated|expired` | `INACTIVE` |
| availability/quality 为 stale、unavailable、invalid、`STALE`、`UNAVAILABLE`、`DEFINITION_MISMATCH` 或 `INVALID` | `UNKNOWN` |
| `lifecycle=not_computable` | `UNKNOWN` |
| `availability=partial`、`quality=BOOTSTRAP|PARTIAL` 或 `lifecycle=pending_confirmation` | `PROVISIONAL`，原 direction 仅用于展示 |
| available + VALID + confirmed + direction=conflict | `FORMAL_CONFLICT` |
| available + VALID + confirmed + direction=bullish | `FORMAL_BULLISH` |
| available + VALID + confirmed + direction=bearish | `FORMAL_BEARISH` |
| available + VALID + lifecycle=observed|confirmed + direction=neutral | `FORMAL_NEUTRAL` |
| 其余组合 | `UNKNOWN` |

报告阶段映射固定为：`observed=观察`、`pending_confirmation=待确认`、`confirmed=已确认`、`invalidated=已失效`、`expired=已过期`、`not_computable=不可计算`。

## 7. 逐笔成交代理层

### 7.1 大额和超大额成交定义

不同股票、交易时段和市场不能使用统一港元门槛。分类应以单笔成交金额在自身历史分布中的位置为主：

- `large`：过去 20 个完整交易日、相同 `session_phase` 单笔成交金额的 99% 分位；
- `extra_large`：同一历史窗口的 99.9% 分位；
- 阈值按标的和 `session_phase` 分开计算；
- 20 日窗口和初始分位数均标记为 `provisional`，必须通过后续事件研究决定保留或调整。

分位数使用 nearest-rank：对升序样本 `x[1..n]`，`q_p=x[ceil(p*n)]`。当日 `notional>=q_p` 即归类；阈值窗口严格排除当日，且 20 个历史 session 必须全部 `OK/session_complete`。任何一日单位或币种不可比时整组历史阈值 `NOT_COMPUTABLE`。

在累计足够历史前，若连续交易阶段至少有 1,000 条逐笔记录，可用当日分布的 99%/99.9% 分位做 `BOOTSTRAP` 分类；否则返回 `NOT_COMPUTABLE`。`BOOTSTRAP` 证据不得与成熟历史阈值混为一谈。

所有依赖完整当日成交分布的证据在收盘后才 `available_at`，最早只能用于下一交易日计划；盘中不得回填成已经知道全天分位数的信号。

### 7.2 确定性统计和信号

只对 `session_phase=continuous`、价格和数量有效的逐笔计算方向性统计。设：

- `T`：连续交易总成交金额；
- `LU/LD`：large 且 uptick/downtick 的成交金额；
- `EU/ED`：extra-large 且 uptick/downtick 的成交金额；
- `C`：有 tick direction 的成交金额覆盖率；
- `large_share=(LU+LD)/T`；
- `large_imbalance=(LU-LD)/(LU+LD)`；
- `extra_imbalance=(EU-ED)/(EU+ED)`。

`trade_count`、large/extra-large print count 均只统计 continuous phase；方向性 print count 只统计 `tick_direction` 已知的记录。`T=0`、`LU+LD=0` 或 `EU+ED=0` 时对应比率为 `null/NOT_COMPUTABLE`，不能填零。

首期 provisional 规则如下：

| Evidence kind | 精确触发规则 | 最小覆盖 | `available_at` | 失效/过期 |
|---|---|---|---|---|
| `large_uptick_print_concentration` | `large_share>=10%` 且 `large_imbalance>=0.20` | `trade_count>=1000`、`C>=90%`、large prints `>=10` | 完整收盘后 | 三个交易日或价格失效位触发 |
| `large_downtick_print_concentration` | `large_share>=10%` 且 `large_imbalance<=-0.20` | 同上 | 完整收盘后 | 同上 |
| `extra_large_uptick_cluster` | extra-large prints `>=3` 且 `extra_imbalance>=0.30` | `C>=90%` | 完整收盘后 | 三个交易日 |
| `extra_large_downtick_cluster` | extra-large prints `>=3` 且 `extra_imbalance<=-0.30` | 同上 | 完整收盘后 | 三个交易日 |
| `post_continuous_concentration` | post-continuous-window notional / 全日 notional `>=15%` | session complete | 完整收盘后 | 仅描述当日，不给方向 |
| `short_pressure` | 第 5.3 节的 20 日历史分位规则；固定 neutral | 20 个完整历史日 | 实际抓取后 | 下一次完整卖空数据到达 |

以上阈值全部输出在 `thresholds`，并标记 `provisional`。事件研究未通过前只表示成交在上涨/下跌 tick 上的集中，不叫主动买入、主动卖出或机构下单。

若同层 bullish 和 bearish 规则同时触发，`LayerResult.direction=conflict`；如果均未触发且数据完整，方向为 `neutral`；覆盖不足为 `lifecycle=not_computable`，不能写成 neutral。

### 7.3 防止重复计分

大额成交集中、超大额成交集中和成交量异常都来自同一成交 tape。它们只能在 `trade_tape` 家族内形成一个 LayerResult，不能作为多份独立确认相加。

## 8. K 线行为证据层

该层继续保持纯 OHLCV、价格区域和市场结构，不引入技术指标。

### 8.1 做多迹象

所有 baseline 只用信号 K 之前的 20 个完整日线：

- `volume_baseline=median(Volume[t-20:t])`；
- `range_baseline=median((High-Low)[t-20:t])`；
- `relative_volume=Volume[t]/volume_baseline`；
- `close_position=(Close-Low)/(High-Low)`；零振幅时为 0.5；
- `prior_low=min(Low[t-20:t])`，`prior_high=max(High[t-20:t])`；
- 距离需求/供给区不超过 `0.25*range_baseline` 才算位于有效位置。

位置判断固定为：需求区 `[zone_low, zone_high]` 与信号 K `[Low, High]` 相交，或 `0<=Low-zone_high<=0.25*range_baseline`；sell-side liquidity 价位 `L` 要求 `Low<=L` 且 `Close>=L`。做空严格镜像：供给区相交或 `0<=zone_low-High<=0.25*range_baseline`；buy-side liquidity 要求 `High>=L` 且 `Close<=L`。没有可追溯 zone/pool ID 时位置条件不成立。

首期 provisional 规则：

| Evidence kind | 精确规则 | 确认与失效 | 可用时间 |
|---|---|---|---|
| `bullish_absorption_like` | 位于需求区或 sell-side liquidity；`relative_volume>=1.5`；`close_position>=0.65`；`Close >= previous_close-0.25*range_baseline` | 五日内收盘突破信号 K 高点确认；跌破信号 K 低点失效 | 信号 K 收盘为 pending；确认 K 收盘后 confirmed |
| `bullish_sweep_reclaim` | `Low<prior_low` 且 `Close>=prior_low` 且 `close_position>=0.65` | 五日内收盘突破信号 K 高点确认；再收盘跌破信号 K 低点失效 | 同上 |
| `selling_exhaustion_like` | `Low<=prior_low`；`relative_volume<=0.8`；`close_position>=0.50`；最近 5 日收盘跌幅绝对值不大于前 5 日跌幅的 50% | 突破信号 K 高点确认；跌破信号 K 低点失效 | 同上 |
| `low_volume_test` | 在已确认 absorption/sweep 后五日内；`relative_volume<=0.8`；`Low` 不破原失效位；`close_position>=0.50` | 下一根收盘高于 test K 高点确认；跌破原失效位失败 | test K 后一根收盘 |
| `markup_confirmation` | 已存在 pending bullish evidence；五日内 `Close>signal_high`，且收盘位于当日振幅上部 35% | `Close<signal_low` 失效 | 突破 K 收盘后 |
| `strong_bullish_sequence` | 现有锤头、看涨吞没或早晨之星发生在有效需求位置 | 五日内收盘突破 pattern high；跌破 pattern low 失效 | 确认 K 收盘后 |

20 日样本、区域或基准不足时返回 `NOT_COMPUTABLE`。pending 形态可以展示，但不能参与正式双层对齐。

其中 selling exhaustion 的跌幅定义固定为：`prior_decline=max(0, Close[t-10]-Close[t-5])`，`recent_decline=max(0, Close[t-5]-Close[t])`；要求 `prior_decline>0` 且 `recent_decline<=0.5*prior_decline`。所有价格比较均使用未四舍五入的原始值，报告展示时才格式化。

### 8.2 做空迹象

对上述条件做严格镜像：需求改供给、低点改高点、`close_position>=0.65` 改为 `<=0.35`、向下推进改为向上推进，输出 `bearish_absorption_like`、`bearish_sweep_reclaim`、`buying_exhaustion_like`、`low_volume_retest` 和 `markdown_confirmation`。镜像规则共用同一函数和 golden fixtures，禁止另写一套方向不一致的阈值。

### 8.3 必须修正的现有逻辑

- 成交量基线只使用 `t-1` 及更早数据，排除当前异常 K；
- “低位吸筹”必须位于需求区、sell-side liquidity 或下跌/区间结构中；
- 高位放量整理不能命名为吸筹；
- `daily_zones` 必须真正参与多周期重叠判断；
- 多空证据相同不能默认判空，应输出 `conflict`；
- 每个需要后续 K 线确认的形态都分别记录 `signal_at` 和 `available_at`；
- 最后两根尚未获得未来确认的 K 线只能标记 `pending_confirmation`；
- 数据样本不足时输出 `NOT_COMPUTABLE`，不能输出“无明显信号”。

### 8.4 跨层依赖

OHLCV Volume 与逐笔成交来自同一批成交，不构成统计独立双源。价格层只有在同时包含位置、收回、收盘位置或结构突破等 `price_response` 证据时，才可与 `trade_tape` 做跨层印证；单纯“日线放量 + 大额逐笔集中”仍算一个依赖组。

报告用“跨层印证”，不用“独立双证据”。

## 9. 双层融合

融合不做简单加权求和。先按第 6.4 节把两层各自归一成唯一 participation state，再按以下优先级融合：

1. 任一层为 `FORMAL_CONFLICT`，输出 `conflict`；
2. 否则任一层为 `PROVISIONAL`，输出 `provisional`，并保留原方向、pending/bootstrap/partial 原因；因此 valid directional × pending 也是 provisional，partial conflict 也只是 provisional；
3. 其余状态按下方完整矩阵映射。

| trade-flow \ price-action | FORMAL_BULLISH | FORMAL_BEARISH | FORMAL_NEUTRAL | UNKNOWN / INACTIVE |
|---|---|---|---|---|
| `FORMAL_BULLISH` | `aligned_bullish` | `conflict` | `flow_only` | `flow_only` |
| `FORMAL_BEARISH` | `conflict` | `aligned_bearish` | `flow_only` | `flow_only` |
| `FORMAL_NEUTRAL` | `price_action_only` | `price_action_only` | `neutral` | `unavailable` |
| `UNKNOWN / INACTIVE` | `price_action_only` | `price_action_only` | `unavailable` | `unavailable` |

所以 valid directional × not-computable 会保留为对应 single-layer；neutral × unknown 固定为 unavailable；invalidated/expired 不会被解释成反向证据。

两个 formal direction 只有在证据有效区间于同一 `decision_time` 重叠，且 `target_session` 相差不超过三个交易日时才算时点对齐；若不对齐，降为 `provisional/time_misaligned`。trade-flow 证据默认从下一交易日开盘有效至第三个交易日收盘；price-action 证据从确认后下一交易时点有效至第十个交易日收盘或失效位触发，以先到者为准。

`STALE/INVALID/DEFINITION_MISMATCH` 不得覆盖另一个有效单层结论；它只让自身成为 unknown，并写入 limitations。层内同时出现多空证据时必须先返回 conflict，不能在融合层用平均分抵消。

`aligned_bullish` 可以显示为“大额成交代理与 K 线响应同时符合专业资金进场迹象”，但必须同时列出：

- 观察到的具体行为；
- 可能的替代解释；
- 确认条件；
- 失效位；
- 数据新鲜度和来源。

在通过经济有效性验收前，所有状态均为 `ADVISORY_ONLY`，不能改变仓位。

## 10. 报告与审计

### 10.1 Markdown 报告

新增独立章节：

```text
主力动作代理判断
- 大额成交代理：...
- K线行为证据：...
- 双层关系：一致 / 冲突 / 单层 / 不可用
- 当前阶段：观察 / 待确认 / 已确认 / 已失效 / 已过期 / 不可计算
- 确认条件：...
- 失效条件：...
- 数据限制：...
```

### 10.2 Journal

写入：

- `trade_flow_evidence`；
- `price_action_evidence`；
- `smart_money_fusion`；
- 原始 snapshot ID；
- provider 状态和口径。

### 10.3 Audit

新增有序事件：

1. `trade_flow_collection_started`；
2. `trade_flow_collected` 或 `trade_flow_degraded`；
3. `price_action_evidence_generated`；
4. `smart_money_fused`；
5. `plan_generated`；
6. `smart_money_execution_invariance_checked`。

审计中不得写入大体积逐笔原文，只记录 snapshot ID、统计摘要和校验结果。

每个 ticker 必须有 collection started 与 collected/degraded 的 terminal 配对。report、journal、audit 均携带同一个 `run_id`、`snapshot_id`、`price_evidence_id` 和 `fusion_id`，并满足以下机器不变量：

- fusion 的 direction/status/as_of/source IDs 三种产物完全一致；
- smart-money 注入前后的 `action`、`signal_state`、`risk_plan`、`suggested_gross_pct` 和组合 exposure deep-equal；
- 任一 terminal 缺失、ID 无法解析或 snapshot digest 不匹配，验收失败。

### 10.4 Orchestration 边界

`run_analysis()` 负责：调用 provider、原子保存 snapshot、构造纯数据输入、生成 evidence、融合并写审计。`build_trade_plan()` 和 evidence 函数保持纯计算，禁止网络 I/O。

执行顺序固定为：

```text
data_loaded
-> trade_flow_collection_started
-> trade_flow_collected | trade_flow_degraded
-> price_action_evidence_generated
-> smart_money_fused
-> plan_generated
-> smart_money_execution_invariance_checked
-> journal/report serialization
```

即使 trade-flow 降级，也必须产生 terminal event 和可解析的 `LayerResult`。

### 10.5 配置、兼容和回放

配置升级为 versioned `smart_money` 段：

```json
{
  "smart_money": {
    "enabled": true,
    "mode": "dual_evidence",
    "trade_flow": {
      "enabled": true,
      "provider": "eastmoney_hk",
      "timeout_seconds": 5,
      "max_retries": 1,
      "persist_raw": true,
      "require_session_complete": true
    },
    "short_selling": {
      "enabled": true,
      "provider": "hkex"
    }
  }
}
```

- `smart_money.enabled=false` 时不得发起任何新增网络请求，也不得写 market-data snapshot；
- `trade_flow.enabled=false` 时只运行 price-action 层；
- 非港股首期直接返回 `UNAVAILABLE/unsupported_market`，不得错误调用港股 provider；
- `--offline` 或显式 `replay_snapshot_id` 只读取已验证快照，不访问网络；相同 snapshot 与配置必须生成相同 evidence/fusion ID；
- 旧 `volume_anomaly_threshold`、`sweep_recovery_threshold`、`exhaustion_volume_ratio` 仅在一个兼容版本内映射到 price-action provisional 阈值并产生 deprecation warning；
- 旧 `confluence_weight` 不再参与计算，读取到时产生 deprecation warning，下一 schema major 删除；
- `probability` 从 report、brief、JSON、journal 和 audit 的新 schema 全部移除。首期不提供 `heuristic_score`、`strength_score` 或任何替代数字，只输出触发规则、原始统计、状态和 `validation_status=UNVALIDATED`；
- 旧 journal 只读兼容：历史 `probability` 原样保留在 legacy payload，不转换成新 evidence，也不参与新报告；
- `CLAUDE.md`、`README.md`、`RELEASE_NOTES*` 和 `docs/superpowers/smart-money-user-guide.md` 中的旧概率/机构识别表述必须在 Phase 0 同步纠偏。

## 11. 错误处理和降级

- 东方财富失败：保留 `price_action_only`；
- HKEX 卖空数据失败：只缺少辅助证据，不使成交代理层归零；
- 逐笔数量异常少、交易日错误或 session 未完成：标记 `PARTIAL/STALE`；
- 成交单位或方向代码无法验证：标记 `DEFINITION_MISMATCH`；
- OHLCV 与逐笔收盘价、成交量严重不一致：标记 adjustment/definition conflict，不融合；
- 任一远端响应不得包含凭据，日志只保留脱敏 URL 和摘要；
- 所有 provider 设置短超时和有限重试；失败不得阻塞基础裸 K 报告。
- 快照先写同目录临时文件，完成 SHA-256 和 schema 校验后原子 rename；manifest 只追加，不覆盖历史记录；digest 不符时拒绝回放并返回 `INVALID`。
- `.gitignore` 必须覆盖 `reports/market_data/**` 和临时文件；只有经过人工去敏、固定 schema 的 `tests/fixtures/**` 可以进入版本库。

## 12. 测试策略

### 12.1 单元测试

- 港股代码映射；
- 正常、空、截断、乱序和 schema 变化响应；
- 正常日、半日市、休市、未知日历；16:00、16:09、16:10、12:00、12:09、12:10 边界；
- 开盘前、连续交易和 post-continuous window 分段；手工成交类型存在/不存在两种 fixture；
- 大单分位分类和 bootstrap 状态；
- tick rule 的上涨、下跌、同价与未知方向；
- 同秒同价同量合法重复成交保留，分页/截断不得重复或漏记；
- HKD、股数、成交额单位以及人民币柜台隔离；
- 卖空 numerator/denominator、reported/non-reported、历史不足和 90% 分位边界；
- 高位放量不得标成吸筹；
- 需求区吸收、扫低收回、缩量测试和突破确认；
- 多空同分必须 conflict；
- `UNAVAILABLE` 不得按零处理；
- VALID、BOOTSTRAP、PARTIAL、STALE、UNAVAILABLE、DEFINITION_MISMATCH、INVALID、全部 lifecycle 与 LayerResult/Fusion 的完整状态矩阵；
- `enabled=false` 和 `--offline` 的 zero-network 断言；非港股 zero-request 断言；
- 同日多次运行的 snapshot/manifest/latest lineage；snapshot tamper 必须拒绝；
- 旧 journal/schema 只读兼容、旧配置 deprecation 和默认标的回归；
- 新 schema 的所有表面均不存在 `probability`；
- report/journal/audit 端到端传播。

### 12.2 数据契约测试

保存去敏后的 provider fixture，确保：

- fixture 注明探测 URL、规范化参数、抓取时间和原始 SHA-256；
- 远端字段变化会被显式发现；
- 单位、时区和交易日不被静默猜测；
- 相同 raw snapshot 生成相同证据；
- 多次运行不会重复累计同一逐笔数据；
- raw 与 normalized 的成交笔数、成交量、成交额分别核对；若 quote amount 存在，成交额偏差不超过 2%。

### 12.3 实盘冒烟测试

对 0700.HK、1810.HK、9992.HK 验证：

- 固定 fixture 三只全部通过；在交付验收时至少一次真实联网 smoke 的三只 provider 状态均为 `OK`，不能以全部降级代替成功；
- 当日逐笔与日线日期一致；
- provider 返回笔数/总量/总额与不可变快照一致；
- 原始快照、journal 和 audit lineage 完整；
- 任何单层证据都不会改变现有交易计划。

## 13. 经济有效性验证

代码正确不等于信号有效。Phase 4 是独立的资格升级工作，不是首期 provider 交付的隐含承诺。由于免费接口不保证历史逐笔，逐笔层从上线后积累快照，禁止用当前截面补造历史。正式称为“专业资金迹象”前，必须做 point-in-time event study。

### 13.1 防止未来函数

- 事件记录 `signal_at`、`available_at` 和最早可交易时间；
- 使用两根后续 K 确认的形态，最早只能在确认完成后的下一交易时点使用；
- 周/月线必须从当时可见的 daily prefix 重采样；
- 阈值只能在训练窗拟合，测试窗冻结；
- 标签最长观察 20 个交易日，窗口边界执行 purge/embargo。

### 13.2 固定研究协议

- 标的池：有完整逐笔快照、未停牌且港币柜台定义可比的港股；每只股票独立按时间排序；
- 事件去重：同一 ticker、同一方向在五个交易日内重复出现，只保留最早可交易事件；反向事件单独保留；
- 入场基准：`tradable_at` 后首个正常交易日开盘价；无法取得开盘价则该事件 `NOT_COMPUTABLE`；
- benchmark：恒生指数 `^HSI`；缺失时相关超额收益为 `NOT_COMPUTABLE`，不得用零替代；
- 5/10/20 日收益：从入场基准到对应第 N 个交易日收盘的个股收益减恒指同期收益；
- 风险尺度：`1R=median(High-Low, prior 20 complete sessions)`；precision 的正例定义为十日内先触及顺向 `+1R` 而非反向 `-1R`；同日两侧都触及时，若无 point-in-time 1H 数据则按失败处理；
- matched baseline：同 ticker、同自然年、同方向结构、入场前 20 日振幅四分位相同且前后五日无 smart-money 事件的日期；一对一选择时间距离最近者；无匹配则该 lift `NOT_COMPUTABLE`；
- walk-forward：至少 3 年训练、6 个月验证、6 个月测试，之后每 6 个月滚动；测试前后各 embargo 20 个交易日，跨边界标签 purge；历史不足时不启动资格升级；
- 阈值只在训练窗选择，验证窗只做一次选择确认，测试窗完全冻结；
- 置信区间按 ticker-month block bootstrap 10,000 次；多 kind 同时检验使用 Benjamini-Hochberg FDR 5%。

收益统一转为方向调整值：`directional_excess=s*(stock_return-benchmark_return)`，bullish 的 `s=+1`，bearish 的 `s=-1`。matched baseline 的“同方向结构”指入场前一日现有 market-structure 模块输出的规范化状态完全相同；候选日沿用待匹配事件方向计算假想结果，不从未来价格反推方向。

### 13.3 指标

- 5/10/20 日 benchmark-adjusted return；
- MFE、MAE 和 p95 adverse excursion；
- precision、coverage、false-positive rate；
- 相对 matched baseline 的 lift；
- block-bootstrap 95% 置信区间和样本数；
- A 层、B 层和 A∩B 的 ablation。

其中 A 为 trade-flow layer，B 为包含位置/收回/结构的 price-response layer；A 与 B 不宣称统计独立。coverage 的分母是研究期内满足基础数据可用性的 ticker-session，precision 的分母是可计算且给出方向的独立事件。

### 13.4 升级门槛

在以下条件满足前保持 `UNVALIDATED / ADVISORY_ONLY`：

- 至少 200 个独立样本外事件；这是升级判定门槛，不是首期交付时保证能够凑齐的样本量；
- 每个方向至少 30 个事件；
- 连续三个测试窗结果方向一致；
- 相对匹配基线的 precision lift 至少 5 个百分点，且置信区间下界大于零；
- 双层证据相对最强单层仍有增量；
- 10 日超额收益置信区间下界大于零。

门槛未通过时只输出观察事实、原始统计和离散状态，不输出数值强度或校准概率。未来若验证通过并需要经验概率，必须另行升级 schema 和设计校准协议。

## 14. 实施阶段

### Phase 0：语义纠偏

- 删除 `probability`，首期不设置替代数值分；
- 报告去掉“主力抄底概率”措辞；
- 标记 `validation_status=UNVALIDATED` 和 `ADVISORY_ONLY`；
- 修复当前未来确认时间和误导性命名。
- 同步修订 README、用户指南、release notes 和配置说明，保证所有用户可见表面口径一致。

### Phase 1：免费成交代理层

- 定义 provider protocol 和数据契约；
- 实现东方财富港股逐笔 provider；
- 实现原始快照、质量状态和降级；
- 接入 HKEX 当日卖空辅助数据。

### Phase 2：K 线证据升级

- 使用真实区域、流动性池和市场结构；
- 实现 absorption、sweep/reclaim、test、markup/markdown；
- 统一 `signal_at/available_at/invalidation`。

### Phase 3：融合与报告

- 实现第 9 节完整融合状态机；
- 写入 Markdown、journal 和 audit；
- 保持交易计划不受影响。

### Phase 4：事件研究与资格升级

- 从上线日起积累逐笔快照；
- 扩展到更广港股池做 walk-forward；
- 达到验收门槛后再讨论是否允许影响动作或仓位。

## 15. 验收标准

首期功能完成时必须同时满足：

1. 不配置新凭据即可运行；
2. 三只首期港股均有明确的 provider 结果或结构化降级；
3. 成交代理和 K 线证据分开存储、分开展示；
4. 输出不包含未经校准的“概率”；
5. 单层缺失不会被当作零或反向证据；
6. post-continuous-window 的大额逐笔不污染连续交易判断；
7. 每个证据均有时间、来源、确认和失效字段；
8. 远端接口失败不影响基础裸 K 报告；
9. 报告、journal、audit 的结论和 lineage 一致；
10. 全部现有测试和新增测试通过；
11. 固定 fixture 三只通过，且交付验收至少完成一次三只均为 `OK` 的真实联网 smoke；
12. `enabled=false`、offline replay 和非港股路径均有 zero-network 测试；
13. snapshot 使用内容摘要身份、append-only manifest、原子写和 tamper 检测；
14. smart-money 注入前后第 10.3 节执行字段 deep-equal；
15. `reports/market_data/**` 不进入版本库，测试 fixture 除外。

## 16. 已确认决策

- 优先复用项目内现有源；
- 缺失时只接免费公开数据；
- 首期优先港股和当前三只标的；
- 采用东方财富逐笔成交作为成交代理主源；
- 采用现有 OHLCV 作为价格行为主源；
- HKEX 卖空/CCASS 只作为分开的辅助证据，不宣称统计独立；
- 不输出未经验证的数值规则分，更不包装成真实主力概率；
- 未完成样本外验证前不改变交易执行字段。
