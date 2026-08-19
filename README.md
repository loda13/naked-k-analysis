# Naked K Analysis

裸 K 交易计划生成器。纯价格结构驱动：识别 BOS/CHoCH、供需区、主力资金行为，生成触发位、止损、目标和风险计划。可选叠加多源新闻综合。零技术指标。

当前版本：[v3.5.0](https://github.com/loda13/naked-k-analysis/releases/tag/v3.5.0)

## 核心能力

**技术面**：
- **市场结构**：swing high/low、HH/HL/LH/LL、BOS/CHoCH
- **关键区域**：供需区、流动性池、POC、价值区域、Anchored VWAP
- **主力资金** ⭐：吸筹、扫单、卖压衰竭，输出概率评分（如"主力抄底概率 92%"）
- **交易剧本**：BOS 延续、CHoCH 反转、假突破反打、压缩等待扩张
- **多周期框架**：月线定方向、周线定结构、日线找机会、1H 做触发
- **风险计划**：1R/2R/3R 目标、建议仓位、账户风险、回撤保护

**消息面**（可选 `--news`）：
- **多源采集**：Yahoo + Google + SEC EDGAR + Finnhub（专业财经）+ AkShare（中文）+ 新浪（分钟级）
- **智能过滤**：相关性评分、质量权重、单词边界匹配
- **两轮斟酌**：第一轮独立审查新闻，第二轮综合技术与消息
- **安全边界**：指令注入隔离、增仓交叉佐证门、价格字段只由代码生成

**回测**：
- 事件回测、Walk Forward、R 倍数绩效、Monte Carlo 重排、市场周期分桶

**数据**：
- westock-data CLI → 腾讯 K 线 → Yahoo chart → yfinance 自动降级
- 支持港股 `.HK`、A 股 `.SS`/`.SZ`、北交所 `.BJ`、美股、韩股

## 快速开始

```bash
# 安装
python -m pip install -r requirements.txt

# 运行（默认：腾讯/小米/PDD/泡泡玛特）
python naked_k_analysis.py

# 启用消息面综合
python naked_k_analysis.py --news

# 自定义输出
python naked_k_analysis.py --report-path reports/today.md --config-path config/naked_k.json

# 测试
python -m unittest discover -v
```

**输出**：
- `reports/naked_k_latest.md` - Markdown 报告
- `reports/naked_k_journal.jsonl` - 复盘日志
- `reports/naked_k_audit.jsonl` - 运行审计

## 主力资金检测

v3.4.0 新增 Smart Money Concepts (SMC)，默认启用：

**信号类型**：
- **吸筹信号**：放量但价格窄幅震荡
- **卖压衰竭**：新低但量能萎缩
- **买盘衰竭**：新高但量能萎缩
- **多周期共振**：日/周/月需求区或供给区重叠

**v3.5.0 改进**：
- ✅ 显示所有历史信号（带时间标记，如"5天前"）
- ✅ 近3个月信号统计（次数和日期列表）
- ✅ Dual-Evidence 架构（价格证据 + 成交证据融合，港股专属，实验性）

**输出示例**：
```
主力行为：主力抄底概率 83% (吸筹信号(392天前), 吸筹信号(78天前)) | 近3月2次
```

可通过配置禁用或调整阈值（`config.json` 的 `smart_money` 部分）。

## 消息面配置（可选）

### 无需配置
- Yahoo Finance + Google News（默认启用）

### 推荐配置
**Finnhub**（专业财经，免费 60 calls/分钟）：
```bash
# 1. 注册 https://finnhub.io/register
# 2. 添加到 .env
FINNHUB_API_KEY=your_api_key_here
```

**AkShare**（中文财经，可选依赖）：
```bash
pip install akshare
```

**Anthropic-compatible**（两轮综合，需模型）：
```dotenv
ANTHROPIC_BASE_URL="https://your-endpoint/v1"
ANTHROPIC_AUTH_TOKEN="your-token"
NAKED_K_NEWS_MODEL="your-model-id"
```

未配置时自动降级到纯技术分析。

## 报告字段

**技术面**：
- `action`：买入 / 小仓试错 / 观望 / 减仓 / 回避
- `entry_trigger` / `stop_loss` / `target_price`：触发 / 失效 / 目标
- `market_structure`：结构序列、BOS/CHoCH 事件
- `market_regime`：趋势 / 震荡 / 高波动 / 低波动压缩
- `trade_setup`：交易剧本分类
- `risk_plan`：单笔风险、账户风险、1R/2R/3R 目标
- `smart_money_signals`：主力资金行为概率评分

**消息面**（`--news` 启用时）：
- `news_analysis`：多源新闻、第一轮消息面结论
- `combined_conclusion`：第二轮综合建议、证据引用

**复盘**：
- `review`：上一计划触发 / 失效复盘
- `intraday_status`：1H 盘中状态

## 核心逻辑

**多周期框架**：月线定方向 → 周线定结构 → 日线找机会 → 1H 确认触发。周期冲突时降仓或观望。

**市场结构**：
- 收盘突破前结构高点 → 多头 BOS
- 下降结构中向上突破 → 多头 CHoCH
- 反之为空头 BOS/CHoCH

**交易剧本**：
- **BOS 延续**：趋势结构中突破，等待回踩确认
- **CHoCH 反转**：结构转换，需小周期确认
- **假突破反打**：扫过前高/前低后收回，结合派发压力
- **压缩等待**：低波动不押方向，等扩张确认

**触发与止损**：
- 多头：触发 = 信号 K 高点 + ATR 缓冲；失效 = 低点 - ATR 缓冲
- 空头：触发 = 信号 K 低点 - ATR 缓冲；失效 = 高点 + ATR 缓冲

**风险计划**：
- 建议仓位 = 账户风险 ÷ 单股风险，受动作上限约束
- 回撤超限 → 暂停新仓；连续亏损 → 账户风险减半

## 文件结构

**核心模块**：
- `naked_k_analysis.py` - CLI 入口
- `naked_k_planner.py` - 交易计划编排
- `naked_k_trade.py` - 触发/止损/ATR 缓冲
- `naked_k_structure.py` - BOS/CHoCH/market regime
- `naked_k_zones.py` - 供需区/流动性池
- `naked_k_setups.py` - 交易剧本分类
- `naked_k_timeframes.py` - 多周期框架
- `naked_k_risk.py` - 风险计划
- `naked_k_smart_money.py` - 主力资金检测
- `naked_k_portfolio.py` - 组合风险暴露

**消息面**（可选）：
- `naked_k_news.py` - 公开新闻采集
- `naked_k_news_enhanced.py` - 多源合并/质量排序
- `naked_k_news_llm.py` - 两轮综合斟酌
- `naked_k_synthesis.py` - 技术与消息综合

**数据与回测**：
- `westock_wrapper.py` - 多数据源兜底
- `naked_k_backtest.py` - 事件回测/Walk Forward

**测试**：447 单元测试覆盖所有核心逻辑

## 参数配置

```json
{
  "risk": {
    "account_risk_pct": 0.8,
    "max_drawdown_pct": 6.0,
    "consecutive_loss_limit": 2,
    "action_gross_caps": {"买入": 20.0, "小仓试错": 8.0}
  },
  "portfolio": {
    "max_total_gross_pct": 60.0,
    "max_direction_gross_pct": 45.0,
    "max_market_gross_pct": 35.0
  },
  "smart_money": {
    "enabled": true,
    "volume_anomaly_threshold": 2.0,
    "exhaustion_volume_ratio": 0.8,
    "confluence_weight": 1.2
  }
}
```

## 免责声明

本项目是研究和交易辅助工具，不构成投资建议。所有输出需结合个人风险承受能力和独立判断使用。

## License

MIT — 见 [LICENSE](LICENSE)
