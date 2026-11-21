# 股票与 ETF 日线研究

> **免责声明：本项目及其生成的报告仅供学习、研究与技术交流，不是投资建议，不构成任何买卖建议或收益承诺。投资决策请独立判断，风险自行承担。**

输入标的代码，生成中文文字报告。报告用 **MA/EMA 20、60、120** 制定数周至数月的条件交易计划，再用十条交易理念核对趋势、成交量、换手率、市场环境和持仓纪律。每个标的单独显示符合的条件、观察值和数据缺口。

```bash
python naked_k_analysis.py 600000.SS 0700.HK QQQ
```

当前版本 **v5.1.0**。交易规则为 `bige-dual-ma-v1`，十项观察为 `market-principles-v1`。周线、4 小时、1 小时、黄金分割、支撑压力、33 项技术指标及离线回测均可继续使用。策略收益尚待样本外验证。

[v5.1.0 发布说明](docs/releases/v5.1.0.md) · [十项判断口径与数据示例](docs/market-principles.md) · [双均线规则与原始来源](docs/dual-ma-system.md) · [变更记录](CHANGELOG.md)

## 如何读十项判断

- **看量价和趋势。** 日量比使用当前已收盘日成交量除以前五日均量。报告区分明显缩量创新高、放量突破当日、随后缩量回踩守位以及突破失败，同时显示收盘与 MA5、MA20 的位置。
- **看形态走到了哪一步。** “倍阳缩倍阴”先找倍量上涨阳线，再检查次日是否出现半量阴线、第三根是否小实体整理。跌破首根低点会标出失效。早盘急跌是否收复、尾段是否急涨，另取同一交易日的完整分时。
- **看持仓纪律。** 同日账户快照可核对单笔亏损超过 5%、曾盈利至少 15% 后回落至 10%，以及组合内有多少只持仓、哪些弱势持仓应优先复核。只输入股票代码时，账户状态显示未知。
- **看需要额外证据的条件。** 腾讯 A 股收盘快照可提供当日换手率和触板状态。盘中市场广度、板块排名和资金方向、历史连板数及炸板记录可从有日期和来源的资料补充。核对结果写入 `items[].principles`，交易动作与风险预算沿用双均线计划。

## 核心规则

1. **六线齐备**：至少120根已收盘日K；不足时不降级到旧的EMA20/50策略。
2. **密集区开仓**：六线带宽默认≤1%，连续3根识别密集；冻结突破前边界，连续2根收盘站上上沿后产生一次多头候选。
3. **首次回踩开仓**：突破密集区并离开20均线带后，仅第一次触碰、收盘守住且六线多头排列时产生候选。失败后的第二次回踩不会被重新标成第一次。
4. **止损对应开仓依据**：密集区开仓用原密集区下沿保护；回踩开仓用20均线带下沿保护。默认向下缓冲0.1%，回踩保护位仅收紧。
5. **预先选定退出方式**：默认固定3R；也支持历史密集区目标和显式高低点锚定的斐波那契目标。目标缺失或盈亏比不足则不生成新仓。
6. **下一开盘复核**：实际开盘仍需在形态边界之上；最高接受信号收盘上方0.5R。按实际成交价重算风险，不按过时价格假设成交。
7. **账户预算约束**：保留回撤、连续亏损及组合上限；实际账户未知保持未知。股票只做多头/现金，空头形态仅作防守观察。

1%/3根/2根/0.1%/0.5R及20根形态有效期均是可审计的工程参数，未做收益优化；完整边界见[规则文档](docs/dual-ma-system.md)。MA/EMA排列不会单独触发买入，R倍数也不是盈利预测。

## 报告

报告先展示双均线交易计划，随后列出十项理念判断、多周期核对及回撤位置。技术指标与文字形态放在附录，新闻按需附上日期、来源和标题。

| 报告部分 | 回答的问题 |
| --- | --- |
| 双均线交易计划 | 当前是什么趋势？有无合格开仓形态？止损与退出依据是什么？ |
| 交易理念核对 | 量价、均线、换手、题材或持仓纪律有哪些条件符合？还缺哪项资料？ |
| 多周期核对 | 周线、日线、4小时、1小时支持同一方向，还是存在分歧或方向未明？ |
| 起涨点与回撤 | 选的是哪一段上涨？当前回吐多少涨幅？均线和历史区域是否邻近？ |
| 独立黄金分割点判断 | 日线和周线最近较大上涨、下跌阶段的0.618各在哪里？参考价在其上方还是下方？ |
| 数据与账户边界 | 哪些K线已收盘？复权能否比较？真实持仓和风险是否已知？ |
| 观察附录 | 其他指标与文字形态提供哪些补充线索？ |

回撤锚点默认为可见周线样本最高点及此前最低点，明确标为待研究者核对的候选，不能保证就是作者会选的上一轮上涨。报告区分“回吐上涨幅度”和“从高点下跌幅度”，列出各回撤位附近的均线和已确认历史水平区，并披露端点、公式、复权和时间检查。临近均线并不证明支撑有效，程序核对也不等于收益验证。

CLI自动检查数据与计算；独立行情源核验、波段尺度选择和局部波段解释仍需研究者复核。没有合格形态时明确输出等待，不根据回撤档位补造买点。回撤观察中的自动低点→高点，与配置中用于新高扩展退出的显式高点→后续低点是两组不同锚点。

新增独立的**黄金分割点判断**，分别列出日线/周线的最近上涨段与下跌段，共四项。上涨段的0.618是 `H−0.618×(H−L)`，表示从高点回吐61.8%涨幅；下跌段的0.618是 `L＋0.618×(H−L)`，表示从低点收复61.8%跌幅。报告同时列出起止日期和价格、阶段涨跌幅、参考价与0.618的距离、确认时间及起点失效情况。

选段默认使用最近252根日K/156根周K，涨跌幅至少10%，端点至少相隔20根日K/8根周K，局部极值前后各5根日K/2根周K确认；优先最新合格终点，再选最近合格起点，段内不能越过所选高低点。样本边界的端点标为待确认，缺少合格阶段时明确留空。选段阈值采用项目的工程定义。结果保存在 `verification.golden_section`（`golden-section-v1`），随JSON和journal输出；复权不可比时分别使用各周期自身收盘。

旧EMA50/200、ADX、ATR、20日通道、结构支撑压力、成交量、VWAP及新闻都不能改变双均线主线。新闻只保留来源/日期/标题，采集失败不影响技术报告。辅助观察定义见[技术观察文档](docs/technical-observations.md)。

## 使用

```bash
git clone https://github.com/loda13/naked-k-analysis.git
cd naked-k-analysis
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python naked_k_analysis.py 0700.HK
python naked_k_analysis.py 1810.HK
python naked_k_analysis.py 0700.HK 1810.HK RKLB --json
python naked_k_analysis.py 0700.HK --config-path config.example.json --news
python -m unittest discover -v
```

本版本使用Python 3.14验证，依赖见 `requirements.txt`。标的使用明确代码，例如腾讯 `0700.HK`、小米 `1810.HK`、泡泡玛特 `9992.HK`、美股/ETF `RKLB PDD SMH QQQ VOO`、三星电子 `005930.KS`、SK海力士 `000660.KS`；它们是输入示例，不是推荐股票池。

必须显式提供ticker，没有内置股票池。行情按 westock-data CLI → 腾讯K线 → Yahoo chart → yfinance 降级。默认取3年日K、5年周K及1年小时K；只用已收盘日K决策，其他周期缺数据时保留主线报告。股票4小时从当地开盘起分组，不跨夜，尾盘可较短；缺尾盘、未核验的时间格线或复权口径不能伪装成完整跨周期确认。未接入完整交易所日历，普通工作日开盘窗口过后会保守暂停旧候选。

韩股小时数据缺少尾盘时，1小时标为不完整、4小时不可用；A股午休格线或未知小时来源未核验时不强行聚合。数据缺口会影响均线和跨周期解释，报告会列出限制。

独立保存一次运行：

```bash
mkdir -p reports/dual-ma
python naked_k_analysis.py 0700.HK --json \
  --report-path reports/dual-ma/report.md \
  --journal-path reports/dual-ma/journal.jsonl \
  --audit-path reports/dual-ma/audit.jsonl > reports/dual-ma/payload.json
```

不指定路径时仍使用 `reports/naked_k_latest.md`、`reports/naked_k_journal.jsonl`、`reports/naked_k_audit.jsonl`。研究输出保留在 `reports/`，日志追加，不删除旧schema记录。

## 配置与持仓

`strategy` 控制工程阈值和退出方式，`risk`/`portfolio` 保留原有风险边界。例如固定5R：

```json
{"strategy": {"exit_method": "fixed_r", "take_profit_r": 5}}
```

三种 `exit_method` 为 `fixed_r`、`previous_cluster`、`fibonacci`。斐波那契必须按ticker提供历史高点日与后续低点日，不能自动猜锚点；示例与校验要求见[规则文档](docs/dual-ma-system.md#配置示例)。当前每笔在一个选定目标全量退出，不实现分批止盈或滚仓。

可复制 [account.example.json](account.example.json) 填写实际数据：

```bash
python naked_k_analysis.py 0700.HK --account-path account.json
```

账户快照要求对应行情日期；缺失为 `unknown`，过期/未来快照暂停新仓。仓位百分比按账户权益计，当前只支持无杠杆多头。可选 `entry_setup` 记录原来的 `cluster_breakout` 或 `first_pullback_20`；可选 `target_price` 记录实际交易计划目标。缺少原依据时不把新信号套到旧持仓上。快照仍有仓位但收盘已触及原止损/目标时，提示核实订单，不虚构成交。

每个持仓可选填 `pnl_pct` 和 `peak_pnl_pct`，分别为相对本笔成本的当前收盘盈亏百分数和持仓期最高收盘盈亏百分数。例如 `10` 表示盈利 10%。最高值须覆盖当前值。同一笔交易应使用一致成本口径。

补充市场数据使用按大写标的代码索引的 JSON。复制示例后，将日期、来源、标的和数值替换为实际记录，只保留已知字段。补充资料过期或晚于日 K 时会显示日期差异。

```bash
python naked_k_analysis.py 600000.SS --context-path context.json --account-path account.json --json
```

[补充资料示例](context.example.json) · [字段口径及逐项判定](docs/market-principles.md)

仓位按风险金额除以入场与止损距离推算，再受组合上限限制；预算不是实际暴露，不自动转换整手订单。

## 回测与验证

```bash
python naked_k_backtest.py 0700.HK --csv daily.csv \
  --commission-bps 10 --slippage-bps 10 \
  --config config.example.json --output reports/backtest.json
```

CSV列为 `Date,Open,High,Low,Close,Volume`，升序、完整已收盘；生产预热最低120根，至少121根才能评估一个执行日。费用、滑点均为单边基点，上述10基点只是命令示例。`--benchmark-csv` 可传入 `Date,Close` 外部基准。

回测与计划共用相同信号和配置。使用下一开盘、实际跳空、日内止损/止盈、显式费用和不利滑点；同日双触价而无法判断顺序时先止损，开盘已触价按开盘先处理。期末未平仓按市值记录。EMA50/200仅作比较策略，起点评估缺少EMA200时标记不可计算。

`run_walk_forward_event_backtest` 使用冻结参数、非重叠测试段和独立账户重置；`train_size`最低120。拼接各窗口收益不是连续持仓账户业绩。人工斐波那契锚点必须披露选择方法与可能的事后选择偏差。

当前版本的离线测试和三市场 CLI 核对记录见发布说明。双均线的原始教学出自以太坊教授幣哥，来源、时间点和项目量化约定收录在规则文档中。[发布验证](docs/releases/v5.1.0.md) · [规则与来源](docs/dual-ma-system.md)

## 从 v4.1.0 / technical-trend-v2 迁移

- 默认交易规则整体替换为 `bige-dual-ma-v1`，不保留旧策略作为隐含过滤器；旧设计和发布文档保留为历史。
- 不再使用55根预热、短历史替代规则、EMA50退出或前20日突破入场。当前至少120根；仍不保证产生交易机会。
- JSON/journal/audit 使用新规则版本；回测schema升级为 `2.0`。保留历史日志，不得跨规则拼接业绩。
- 新增 `trend.setup`、`setup_state`、`cluster`、`historical_clusters`、`exit_plan` 和完整 `strategy.parameters`。`breakout`改指密集区事件，`exit_signal`不再表示通用卖出；实际退出取决于原持仓的止损类型/目标。
- 原配置仅含 `risk`/`portfolio`仍可读取，但会采用新的默认双均线规则。旧账户快照仍可读取，可逐步补充原开仓依据和目标。
- `technical-observations-v1`计算定义保持独立；展示移至附录。CLI名称、行情回退、新闻事实和审计链路保留。
- 新增只读 `verification` 字段，版本 `dual-ma-verification-v1`，包含多周期状态、大波段候选锚点、回撤位置与复核限制；随JSON和journal保存，audit记录验证版本与状态。
