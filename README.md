# Stock MA Analysis

街哥核心战法股票分析 CLI。项目用 MA/EMA 六线密集度、Vegas、一目云、MACD、RSI、BOLL、AVWAP、FRVP 和斐波那契，为港股 / 美股 / A 股标的生成短期、中期、长期技术分析建议。

当前版本：[v1.6.0](https://github.com/loda13/stock-ma-analysis/releases/tag/v1.6.0)

## 核心能力

- **综合技术顾问**：`stock_advisor.py` 输出总建议、短期 / 中期 / 长期动作、仓位、失效线、支撑压力、触发条件和阻塞因素。
- **街哥技术流**：基于 MA20/60/120 + EMA20/60/120 六线系统，结合回踩 MA20、假突破、假跌破、Vegas 通道、一目云和关键开盘价系统。
- **指标共振解释**：解释 MACD、RSI、BOLL、OBV、AVWAP、FRVP/POC/VAH/VAL、Fib/结构信号。
- **多周期判断**：默认覆盖短期 4H、日线、周线；4H 使用真实 1H K 线聚合，不再用日线代理。
- **结构化证据**：技术依据按趋势、动量、成本区拆分，同时保留短期 / 中期 / 长期评分。
- **数据源审计**：输出技术分析的来源、周期、行数和最新 K 线日期，便于判断数据可信度。
- **数据质量门槛**：中期日线数据过旧或行数不足时，会给出警告并阻断买入 / 小仓试错。
- **过热风控**：高位过热、价值区上方过远时，阻止标准买入并降级为小仓试错。
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
- `data_sources`：技术分析的数据源审计，含 source、interval、rows、latest
- `warnings`：数据源或分析失败提示

## 综合分析逻辑

`stock_advisor.py` 会运行：

1. `ma_analysis.py`：街哥技术流，多周期指标和结构分析。
2. `stock_analysis/advisor.py`：根据街哥核心战法信号生成动作建议。

决策优先级：

- **买入**：整体技术流偏多，且日线方向确认偏多。
- **小仓试错**：技术流偏多但日线买点未确认，或高位过热需要降级处理。
- **观望**：技术流未形成清晰共振，或关键技术数据质量不可信。
- **减仓**：技术趋势偏空。
- **过热阻断**：RSI 高位且价格在 FRVP 价值区上方时标记高位过热，标准买入会降级为小仓试错。
- **数据质量阻断**：短期 / 中期 / 长期会分别检查行数和最新日期；中期日线不可信时，买入和小仓试错都会降级为观望。

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

代码会自动处理常见代码格式转换，例如 `0700.HK` -> `hk00700`。如果本机没有 westock-data，港股仍可通过腾讯 / Yahoo chart 跑技术分析。分钟线数据不足 120 根时，会继续尝试下一个数据源，避免 4H 分析使用不完整数据。

## 测试

```bash
python3 -m unittest discover -v
```

当前覆盖：

- 技术派 advisor 决策
- CLI JSON 输出
- 腾讯 / Yahoo / yfinance 数据源 fallback
- 技术方法论摘要
- 数据源审计、真实 1H 聚合 4H、短中长期分层评分和结构化技术证据
- 数据新鲜度、行数门槛和关键数据质量降级
- 高位过热风控降级

## 免责声明

本项目是研究和交易辅助工具，不构成个性化投资建议。所有输出都应结合个人风险承受能力、持仓周期和独立判断使用。

## License

MIT
