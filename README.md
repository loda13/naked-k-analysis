# 📊 Stock MA Analysis

街哥（JG）双均线密集度 + 裸K形态分析系统。多时间级别（4h / 日线 / 周线）信号扫描，覆盖港股 / 美股 / A股。

## 功能

### 双均线密集度分析 (`ma_analysis.py`)

基于 MA20/60/120 + EMA20/60/120 六线系统，集成街哥课堂 8 大核心技术：

**核心指标**
- **均线密集度** — 极度密集(<2%) / 较为密集(<4%) / 未密集
- **VWAP** — 成交量加权均价（价格强弱判断）
- **MACD** — DIF/DEA/HIST + 零轴博弈 + 顶底背离检测
- **RSI(14)** — 超买(>70) / 超卖(<30)
- **布林带(20,2)** — 上中下轨 + 突破检测
- **斐波那契** — 大周期回撤(0.236/0.382/0.5/0.618/0.786) + ATH扩展(1.618/2.618/3.618)
- **量价关系** — 量价背离检测
- **K线形态** — 早晨星 / 黄昏星 / 锤子线 / 吞没 / 孕线 / 穿头破脚等

**结构识别**
- **维加斯通道** — EMA12/144/169 趋势通道
- **一目均衡表** — 云图（先行带A/B）
- **支撑/压力** — 历史密集区台阶位 + 筹码分布(POC)
- **AVWAP** — 锚定VWAP（重要高点/低点起算）
- **月相** — 朔望识别（趋势阶段判断）

**信号判定**
- 均线密集 + K线在上方 = 买入
- 均线密集 + K线在下方 = 卖出
- 回踩MA20不破 = 强烈加仓
- 假突破MA20 = 卖出
- 假跌破MA20 = 买入

### 裸K形态分析 (`naked_k_analysis.py`)

纯价格行为（Price Action）分析，零指标依赖：

- **K线形态** — 锤子线 / 吞没 / 十字星 / Pin Bar 等
- **支撑/阻力** — 前高前低 / 多次测试位
- **价格结构** — HH/HL（上升趋势） / LH/LL（下降趋势）
- **关键位反应** — 价格在支撑压力位的行为

### 数据源 (`westock_wrapper.py`)

提供与 yfinance 兼容的 `download()` API，按顺序尝试：

1. `westock-data` CLI（可选，通过 `WESTOCK_DATA_SCRIPT` 指定脚本路径）
2. 腾讯 K 线接口（`web.ifzq.gtimg.cn`，备用 `proxy.finance.qq.com`）
3. Yahoo chart JSON 直连（绕过 yfinance cookie 预取）
4. yfinance 官方库兜底

代码会自动处理代码格式转换（如 `0700.HK` → `hk00700`）。如果本机没有 westock-data，港股仍可通过腾讯 / Yahoo chart 跑技术分析和裸 K。

## 安装

```bash
pip install -r requirements.txt
```

依赖项：
- Python 3.8+
- pandas, numpy, yfinance
- westock-data CLI（可选）

## 使用

### 双均线分析

```bash
# 单只股票，单一时间级别
python3 ma_analysis.py 0700.HK 4h
python3 ma_analysis.py NVDA daily
python3 ma_analysis.py 1810.HK weekly

# 多时间级别组合
python3 ma_analysis.py 0700.HK 4h,daily,weekly

# 跑全部默认持仓
python3 ma_analysis.py
```

### 裸K分析

```bash
python3 naked_k_analysis.py NVDA
python3 naked_k_analysis.py 0700.HK -p w -d 240
```

### Wall Street Skill 综合分析

```bash
python3 stock_advisor.py NVDA
python3 stock_advisor.py 0700.HK --json
```

综合分析会把 WSS 研究质量、市场泡沫/风险、财报 IV、技术指标和裸 K 结构合并成短期 / 中期 / 长期动作建议。JSON 和文本报告都会输出 `entry_triggers`（入场/加仓触发条件）和 `blocked_by`（阻止新开仓的因素），技术依据会解释 MACD、RSI、BOLL、Vegas、一目云、OBV、AVWAP、FRVP 和 Fib/结构信号。

WSS 研究 / 泡沫风险 / 财报缓存默认读取 `data/cache/wss/`。缓存刷新有两种方式：

```bash
# 推荐：从浏览器导出的 WSS 页面 HTML 刷新，只写派生 JSON
python3 stock_advisor.py NVDA --refresh-wss-cache --wss-html-dir /path/to/wss-html

# 可选：用环境变量里的登录 Cookie 在线刷新
export WSS_COOKIE='...'
python3 stock_advisor.py NVDA --refresh-wss-cache
```

HTML 文件名包含 `market` / `risk` / `bubble` / `泡沫` 会写入 `market_risk.json`；包含 `earning` / `财报` 会写入 `earnings.json`；其他 `.html` 默认按研究页解析写入 `research.json`。缓存只保存分数、评级、风险、催化、市场状态、规则和财报事件等派生字段，不保存原始 HTML、账号、密码或 Cookie。

### 一键日报

```bash
bash ma_daily_report.sh
```

## 信号说明

| 信号 | 含义 | 条件 |
|------|------|------|
| 🟢 买入 | 均线密集 + K线在上方 | 密集度 < 4%，收盘价高于多数均线 |
| 🔴 卖出 | 均线密集 + K线在下方 | 密集度 < 4%，收盘价低于多数均线 |
| ⚫ 观望 | 均线未密集 | 密集度 ≥ 4% |
| ⚡ 回踩加仓 | 回踩MA20不破 | 触及MA20后站稳反弹 |
| 🚨 假突破 | 站上MA20后快速跌破 | ≤5天内跌回 |
| 🟢 假跌破 | 跌破MA20后快速拉回 | ≤5天内站回，信号升级为买入 |

## 密集度等级

| 密集度 | 等级 | 含义 |
|--------|------|------|
| < 2% | 极度密集🔥 | 变盘在即，方向选择 |
| 2-4% | 较为密集⚡ | 趋势酝酿中 |
| ≥ 4% | 未密集 | 趋势已展开或无序 |

## 输出示例

```
⚫ 0700.HK 435.20 | 日:望 | S:399.9(极强) | R:467.3(中等) | VWAP↓
   维加斯🔴通道下方 | 云云下 | 🟢早晨星 | 筹码上方460.26 / 筹码上方505.12
   📍 周开432.4🟢上方 | 年开595.2🔴下方 | POC502.45(-13%)
   🟢 评分:+0.5 | 🟢早晨星+1 / 筹码压力460.26(强)-0.5 / 套牢盘10%+反弹+0.5
   ⚓ AVWAP_L:427.4(+1.8%) | AVWAP_H:512.7(-15.1%)
   ▲T1: 467.29(+7.4%, 中等7天) ≈Fib0.618
   📐 周期:355.0→677.7 | 0.236:601.5 0.382:554.4 0.500:516.4 0.618:478.3
```

## 哲学

- 信号驱动 > 价位驱动（描述"什么信号值得出手"，不预测"会到哪"）
- 80% 时间无序震荡，只关注资金波动开始的机会
- 强调盈亏比 + 认输条件，不强调方向预测
- 技术分析是辅助工具，跟着盘面走
- 没走出预期立马认输

## License

MIT
