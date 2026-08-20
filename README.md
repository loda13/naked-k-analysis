# Naked K Analysis

裸K交易计划生成器。纯价格结构：BOS/CHoCH、供需区、OHLCV 量价代理证据，生成触发/止损/目标。可选新闻综合。零指标。

**当前版本**: [v3.5.1](https://github.com/loda13/naked-k-analysis/releases/tag/v3.5.1)

## 核心能力

**价格结构**  
市场结构（swing/BOS/CHoCH）、供需区、流动性池、OHLCV 量价代理证据、交易剧本、多周期框架、风险计划（1R/2R/3R）

**消息面**（`--news`）  
Yahoo + Google + Finnhub + AkShare + Sina 多源，相关性过滤，两轮综合

**回测**  
事件回测、Walk Forward、R倍数、Monte Carlo、市场周期分桶

**数据**  

westock-data CLI → 腾讯K线 → Yahoo chart JSON → yfinance 自动降级，支持港股/A股/北交所/美股/韩股。

## 快速开始

```bash
pip install -r requirements.txt
python naked_k_analysis.py 0700.HK
python naked_k_analysis.py 0700.HK TSLA --news
python naked_k_analysis.py QQQ --json
python -m unittest discover -v
```

每次运行必须显式给出一个或多个 ticker。项目不内置股票池，也不设股票白名单；
`company_names.json` 只为部分标的补充新闻别名和 provider 映射。

**输出**：`reports/naked_k_latest.md`、`reports/naked_k_journal.jsonl`、
`reports/naked_k_audit.jsonl`。

## OHLCV 量价代理证据

默认启用，输出吸筹/卖压衰竭/买盘衰竭/多周期共振四类量价规则信号。该证据未经样本外校准，不能识别机构或“主力”身份，不输出概率。

版本变化见 [CHANGELOG.md](CHANGELOG.md)。

**示例**:
```
量价代理: 量价代理偏多（规则强度未校准） | 近3月2次
分钟线资金流快照: 331根/VWAP 445.76/收盘447.20(+0.32%)
```

配置格式见 `config.example.json`；复制为自己的 JSON 文件后通过 `--config-path` 指定。

## 消息面配置（可选）

**无需配置**: Yahoo + Google（默认）  
**推荐配置**: Finnhub（60 calls/分钟，注册 https://finnhub.io/register）
```bash
echo "FINNHUB_API_KEY=your_key" >> .env
```

**AkShare**（中文财经）: `pip install akshare`  
**LLM综合**: 配置 `.env` 里的 `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` / `NAKED_K_NEWS_MODEL`

## 报告字段

- **action**: 买入/小仓试错/观望/减仓/回避
- **entry_trigger** / **stop_loss** / **target_price**: 触发/失效/目标
- **market_structure**: 结构序列、BOS/CHoCH
- **market_regime**: 趋势/震荡/高波动/压缩
- **trade_setup**: 交易剧本（BOS延续/CHoCH反转/假突破反打/压缩）
- **risk_plan**: 单笔风险、账户风险、1R/2R/3R
- **smart_money_signals**: 未校准的 OHLCV 量价代理证据
- **news_analysis**: 多源新闻、第一轮结论（`--news`）
- **combined_conclusion**: 第二轮综合（`--news`）

## 核心逻辑

**多周期**: 月线定方向 → 周线定结构 → 日线找机会 → 1H确认  
**市场结构**: 收盘突破前高 → BOS；下降中向上突破 → CHoCH  
**剧本**: BOS延续、CHoCH反转、假突破反打、压缩等待扩张  
**触发与止损**: 多头触发 = 高点 + ATR缓冲；失效 = 低点 - ATR缓冲  
**风险**: 建议仓位 = 账户风险 ÷ 单股风险，受动作上限约束

## 文件结构

**核心**: `naked_k_analysis.py` (CLI)、`naked_k_planner.py` (编排)、`naked_k_trade.py` (触发/止损)、`naked_k_structure.py` (BOS/CHoCH)、`naked_k_zones.py` (供需区)、`naked_k_smart_money.py` (OHLCV 量价代理)

**消息面**: `naked_k_news.py` (采集)、`naked_k_news_llm.py` (两轮综合)

**数据与回测**: `westock_wrapper.py` (多源兜底)、`naked_k_backtest.py` (事件回测)

## 参数配置

```json
{
  "risk": {
    "account_risk_pct": 0.8,
    "max_drawdown_pct": 6.0,
    "consecutive_loss_limit": 2,
    "action_gross_caps": {"买入": 20.0, "小仓试错": 8.0}
  },
  "smart_money": {
    "enabled": true,
    "volume_anomaly_threshold": 2.0
  }
}
```

## 免责声明

研究与交易辅助工具，不构成投资建议。需结合个人风险承受能力和独立判断。

## License

MIT — 见 [LICENSE](LICENSE)
