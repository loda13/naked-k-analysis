# Naked K Analysis

裸 K 分析 CLI。项目只专注于 K 线本身：实体、影线、收盘位置、前高/前低、结构性突破/假突破、孕线、吞没、Pin Bar、十字星、确认 K、止损触发和复盘日志。

当前版本：[v2.0.0](https://github.com/loda13/naked-k-analysis/releases/tag/v2.0.0)

## 核心能力

- **裸 K 收盘计划**：用日线 / 周线 K 线生成动作、触发位、失效位、第一目标和目标盈亏比。
- **读线结构化**：输出最新 K 线实体强弱、上下影线、收盘位置、前高/前低突破或失败、波幅收敛和高低点节奏。
- **标准形态识别**：覆盖看涨/看跌吸收、Pin Bar、十字星、锤子线、射击之星、早晨星、黄昏星、孕线。
- **确认 K 触发**：多头先突破信号 K 高点，空头先跌破信号 K 低点，避免只凭单根形态追价。
- **ATR 自适应缓冲**：触发位和止损位最低缓冲 0.2%，高波动股票自动放宽。
- **1H 盘中确认**：盘中只做触发 / 失效预警，不覆盖日线和周线主计划。
- **复盘日志**：每次运行写入 `reports/naked_k_journal.jsonl`，下一次会复盘上一根 K 的触发和失效情况。
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

可以用参数改输出路径：

```bash
python naked_k_analysis.py --report-path reports/today.md --journal-path reports/journal.jsonl
```

## 报告字段

- `action`：`买入`、`小仓试错`、`观望`、`减仓`、`回避`
- `signal_state`：`planned_long`、`planned_short`、`watching`
- `price_action`：裸 K 解读，包括 K 线标签、结构信号、风险提示、收盘位置和量能状态
- `entry_trigger`：突破 / 跌破信号 K 极值后的触发位
- `stop_loss`：信号失效位
- `target_price`：第一目标位，优先使用最近结构压力 / 支撑
- `risk_per_share`：单股风险
- `reward_to_risk`：第一目标对应的目标盈亏比
- `position_size`：按 1% 账户风险预算和动作上限反推的仓位上限
- `intraday_status`：1H 盘中状态，只做触发 / 失效预警
- `review`：上一条计划在当前 K 线中的触发、失效和错误类型

## 裸 K 逻辑

日线决定触发，周线决定背景过滤。

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

## 盘中状态

- `接近触发`：最新有效 1H 价格距离触发位 1% 以内
- `盘中确认`：最近有效 1H 收盘站上多头触发位，或跌破空头触发位
- `盘中突破未确认` / `盘中跌破未确认`：盘中触碰触发位，但 1H 收盘未确认
- `接近失效位`：盘中价格接近止损 / 失效位
- `盘中数据未确认`：最新 1H K 线成交量为 0，等待有效 K 线

## 文件结构

- `naked_k_analysis.py`：CLI、交易计划、报告、日志和复盘逻辑
- `naked_k_patterns.py`：纯 K 线形态检测
- `westock_wrapper.py`：市场数据获取和 ticker 转换
- `tests/test_naked_k_analysis.py`：裸 K 计划和报告测试
- `tests/test_naked_k_patterns.py`：K 线形态测试
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
- ATR 缓冲、触发位、失效位、第一目标和 R/R
- 1H 盘中确认和零成交量过滤
- 未收盘日线 / 周线过滤
- 复盘日志去重和上一计划复盘
- 腾讯 / Yahoo / yfinance 数据源 fallback

## 免责声明

本项目是研究和交易辅助工具，不构成个性化投资建议。所有输出都应结合个人风险承受能力、持仓周期和独立判断使用。

## License

MIT
