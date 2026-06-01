# Stock MA Analysis

Wall Street Skill 股票综合分析 CLI。项目把 WSS 研究缓存、市场泡沫/风险、财报 IV、街哥核心技术指标、双均线密集度和裸 K 结构合并起来，为港股 / 美股 / A 股标的生成短期、中期、长期分析建议。

当前版本：[v1.1.0](https://github.com/loda13/stock-ma-analysis/releases/tag/v1.1.0)

## 核心能力

- **综合股票顾问**：`stock_advisor.py` 输出总建议、短期 / 中期 / 长期动作、仓位、失效线、支撑压力、触发条件和阻塞因素。
- **WSS 研究接入**：读取 Wall Street Skill 派生缓存，纳入研究评级、分数、证据等级、催化、风险、护城河、财务质量、行业地位和估值胜率。
- **市场风险门禁**：把泡沫阶段、市场防守/破裂状态、板块过热和财报 IV 风险加入决策，避免只看技术形态追高。
- **街哥核心指标解释**：解释 MACD、RSI、BOLL、Vegas、一目云、OBV、AVWAP、FRVP/POC/VAH/VAL、Fib/假突破/假跌破等信号。
- **裸 K 辅助分析**：保留纯价格行为判断，识别趋势结构、支撑阻力、吞没、锤子线、十字星、Pin Bar 等形态。
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

- `overall_action`：总建议，如买入、持有、观望、减仓、回避
- `short_term_action` / `medium_term_action` / `long_term_action`
- `entry_triggers`：入场、加仓或重新评估的触发条件
- `blocked_by`：阻止新开仓的因素
- `invalidation`：失效线
- `upside_zones` / `downside_zones`：上方压力和下方支撑
- `evidence`：WSS、市场、技术、裸 K、财报依据
- `warnings`：缓存缺失、缓存过期、4H 数据代理等提示

## Wall Street Skill 缓存

WSS 研究 / 泡沫风险 / 财报缓存默认读取 `data/cache/wss/`。缓存只保存派生字段，不保存原始 HTML、账号、密码或 Cookie。

推荐方式是从浏览器导出的 WSS 页面 HTML 生成缓存：

```bash
python3 stock_advisor.py NVDA --refresh-wss-cache --wss-html-dir /path/to/wss-html
```

也可以用环境变量里的登录 Cookie 在线刷新：

```bash
export WSS_COOKIE='...'
python3 stock_advisor.py NVDA --refresh-wss-cache
```

HTML 文件名规则：

- 包含 `market` / `risk` / `bubble` / `泡沫`：写入 `market_risk.json`
- 包含 `earning` / `财报`：写入 `earnings.json`
- 其他 `.html`：按研究页解析写入 `research.json`

## 技术分析工具

### 双均线密集度

```bash
python3 ma_analysis.py 0700.HK 4h
python3 ma_analysis.py NVDA daily
python3 ma_analysis.py 1810.HK weekly
python3 ma_analysis.py 0700.HK 4h,daily,weekly
```

基于 MA20/60/120 + EMA20/60/120 六线系统，识别均线密集、价格相对均线位置、VWAP、MACD、RSI、布林带、斐波那契、量价关系、K 线形态、Vegas 通道、一目云、AVWAP 和筹码分布。

### 裸 K 分析

```bash
python3 naked_k_analysis.py NVDA
python3 naked_k_analysis.py 0700.HK -p w -d 240
```

裸 K 分析不依赖指标，主要看价格结构、前高前低、关键支撑阻力和 K 线反应。

### 一键日报

```bash
bash ma_daily_report.sh
```

## 数据源

`westock_wrapper.py` 提供与 yfinance 兼容的 `download()` API，按顺序尝试：

1. `westock-data` CLI，可通过 `WESTOCK_DATA_SCRIPT` 指定脚本路径
2. 腾讯 K 线接口：`web.ifzq.gtimg.cn`，备用 `proxy.finance.qq.com`
3. Yahoo chart JSON 直连，绕过 yfinance cookie 预取
4. yfinance 官方库兜底

代码会自动处理常见代码格式转换，例如 `0700.HK` -> `hk00700`。如果本机没有 westock-data，港股仍可通过腾讯 / Yahoo chart 跑技术分析和裸 K。

## 决策框架

- **长期**：优先看 WSS 研究质量、商业验证、护城河、行业地位、估值胜率和市场阶段。
- **中期**：看日线 / 周线趋势、Vegas / 一目云 / FRVP 成本区和支撑压力。
- **短期**：看 4H / 日线节奏、MACD/RSI/BOLL、裸 K 形态和明确失效线。
- **风控**：缺少 WSS 研究缓存、市场破裂、财报临近且 IV 高、缓存过期都会降低或阻断新开仓。

## 测试

```bash
python3 -m unittest discover -v
```

当前覆盖：

- advisor 决策
- CLI JSON 输出
- WSS 缓存加载和过期警告
- WSS HTML 派生缓存刷新
- 腾讯 / Yahoo / yfinance 数据源 fallback
- 技术方法论摘要
- 裸 K 数据封装

## 安全与隐私

- 不提交 WSS 账号、密码、Cookie 或原始 HTML。
- `data/cache/wss/` 仅用于本地派生缓存。
- 缓存刷新只写研究、市场、财报等结构化派生字段。

## 免责声明

本项目是研究和交易辅助工具，不构成个性化投资建议。所有输出都应结合个人风险承受能力、持仓周期和独立判断使用。

## License

MIT
