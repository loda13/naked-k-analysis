# Stock MA Analysis

街哥技术流 + 裸 K 股票分析 CLI。项目用 MA/EMA 六线密集度、Vegas、一目云、MACD、RSI、BOLL、AVWAP、FRVP、斐波那契和价格行为结构，为港股 / 美股 / A 股标的生成短期、中期、长期技术分析建议。

当前版本：[v1.3.0](https://github.com/loda13/stock-ma-analysis/releases/tag/v1.3.0)

## 核心能力

- **综合技术顾问**：`stock_advisor.py` 输出总建议、短期 / 中期 / 长期动作、仓位、失效线、支撑压力、触发条件和阻塞因素。
- **街哥技术流**：基于 MA20/60/120 + EMA20/60/120 六线系统，结合回踩 MA20、假突破、假跌破、Vegas 通道、一目云和关键开盘价系统。
- **指标共振解释**：解释 MACD、RSI、BOLL、OBV、AVWAP、FRVP/POC/VAH/VAL、Fib/结构信号。
- **裸 K 辅助确认**：识别趋势结构、BoS、支撑阻力、吞没、锤子线、十字星、Pin Bar、旗形和三角形等形态。
- **多周期判断**：默认覆盖短期 4H、日线、周线；4H 使用真实 1H K 线聚合，不再用日线代理。
- **结构化证据**：技术依据按趋势、动量、成本区拆分，同时保留短期 / 中期 / 长期评分。
- **多数据源兜底**：优先 `westock-data`，再走腾讯 K 线、Yahoo chart JSON，最后用 yfinance。

## 快速开始

```bash
python3 -m pip install -r requirements.txt

# 综合分析，文本输出
python3 stock_advisor.py 0700.HK
python3 stock_advisor.py 9992.HK
python3 stock_advisor.py NVDA

# JSON 输出，适合接入脚本或看板
python3 stock_advisor.py 0700.HK --json
```

输出会包含：

- `overall_action`：总建议，如买入、小仓试错、观望、减仓、卖出
- `short_term_action` / `medium_term_action` / `long_term_action`
- `entry_triggers`：入场、加仓或重新评估的触发条件
- `blocked_by`：阻止新开仓的技术因素
- `invalidation`：失效线
- `upside_zones` / `downside_zones`：上方压力和下方支撑
- `evidence.technical`：街哥技术流依据，含 4H / 日线 / 周线评分，以及趋势、动量、成本区结构化证据
- `evidence.naked_k`：裸 K 依据
- `warnings`：数据源或分析失败提示

## 综合分析逻辑

`stock_advisor.py` 会同时运行：

1. `ma_analysis.py`：街哥技术流，多周期指标和结构分析。
2. `naked_k_analysis.py`：裸 K，价格行为、支撑阻力和形态分析。
3. `stock_analysis/advisor.py`：合并两个方向，生成动作建议。

决策优先级：

- **买入**：整体技术流偏多、日线也偏多，且裸 K 不冲突；如果裸 K 同时偏多，置信度更高。
- **小仓试错**：技术流偏多但日线买点未确认，或技术流中性但裸 K 在支撑 / 结构上给出偏多信号。
- **观望**：技术流和裸 K 没有共振，或技术偏多但裸 K 结构偏空。
- **减仓 / 卖出**：技术趋势偏空；若裸 K 也偏空，直接提高风险等级。

## 技术分析工具

### 双均线密集度

```bash
python3 ma_analysis.py 0700.HK 4h
python3 ma_analysis.py NVDA daily
python3 ma_analysis.py 1810.HK weekly
python3 ma_analysis.py 0700.HK 4h,daily,weekly
```

核心信号：

- 均线密集 + K 线在上方：偏多
- 均线密集 + K 线在下方：偏空
- 回踩 MA20 不破：加仓观察
- 假突破 MA20：风险信号
- 假跌破 MA20 后快速拉回：反向买点观察
- Vegas 通道上方：趋势偏多
- Vegas 通道下方：趋势偏空
- FRVP / POC / VAH / VAL：支撑压力和成本区
- AVWAP：重要高低点锚定成本

### 裸 K 分析

```bash
python3 naked_k_analysis.py NVDA
python3 naked_k_analysis.py 0700.HK -p w -d 240
```

裸 K 分析不依赖指标，主要看：

- 价格结构：HH/HL、LH/LL、BoS
- 支撑 / 阻力：前高前低、多次测试位
- 关键位反应：突破、跌破、受阻、承接
- K 线形态：吞没、Pin Bar、十字星、大阳线、大阴线
- 多 K 线形态：旗形、三角形、孕线等

### 一键日报

```bash
bash ma_daily_report.sh
```

## 数据源

`westock_wrapper.py` 提供与 yfinance 兼容的 `download()` API，按顺序尝试：

1. `westock-data` CLI，可通过 `WESTOCK_DATA_SCRIPT` 指定脚本路径
2. 腾讯 K 线接口：`web.ifzq.gtimg.cn`，备用 `proxy.finance.qq.com`
3. Yahoo chart JSON 直连，绕过 yfinance cookie 预取，支持 1H 数据兜底
4. yfinance 官方库兜底

代码会自动处理常见代码格式转换，例如 `0700.HK` -> `hk00700`。如果本机没有 westock-data，港股仍可通过腾讯 / Yahoo chart 跑技术分析和裸 K。分钟线数据不足 120 根时，会继续尝试下一个数据源，避免 4H 分析使用不完整数据。

## 测试

```bash
python3 -m unittest discover -v
```

当前覆盖：

- 技术派 advisor 决策
- CLI JSON 输出
- 腾讯 / Yahoo / yfinance 数据源 fallback
- 技术方法论摘要
- 裸 K 数据封装
- 真实 1H 聚合 4H、短中长期分层评分和结构化技术证据

## 免责声明

本项目是研究和交易辅助工具，不构成个性化投资建议。所有输出都应结合个人风险承受能力、持仓周期和独立判断使用。

## License

MIT
