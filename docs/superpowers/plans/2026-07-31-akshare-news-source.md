# AkShare 中文财经新闻源接入

Date: 2026-07-31
Status: done（285 测试全绿，含实盘验证）

## 问题

现有三源（Finnhub / Google News RSS / Yahoo Finance）缺中文财经媒体覆盖。港股与 A 股的实质性消息主要以中文发布，当前无源覆盖。`9992.HK` 的 `finnhub_ticker` 为 `null`，只剩 Yahoo（权重 0.5，噪音大）与 Google RSS。

## 实测依据（2026-07-31）

`akshare.stock_news_em`（东方财富个股新闻）：无需 API key，0.1s 返回 10 条，字段 `关键词/新闻标题/新闻内容/发布时间/文章来源/新闻链接`。

Ticker 必须补零到 5 位：`01810` 返回小米回购公告；`1810` 匹配到三星"利润暴增1810%"，全噪音。

新鲜度：7 天内普遍 0–2 条，30 天内 6–7 条 → 适合喂 30 天 `low_freshness` 回退窗，而非 7 天主窗。

已排除：`stock_info_global_cls` / `stock_info_global_em`（90–120s 无返回）；`stock_news_main_cx` / `stock_info_global_ths`（全市场快讯，不按个股，财新连标题与时间戳字段都没有）。

## 设计

### 新模块 `naked_k_news_akshare.py`

照 `naked_k_news_finnhub.py` 的模子：

```python
def collect_akshare_news(ticker, *, now=None, lookback_days=30,
                         max_items=20, fetch=None) -> list[dict]
```

- `fetch` 可注入（返回 DataFrame 的 callable），默认惰性 `import akshare` 取 `stock_news_em`
- akshare 缺失或任何异常 → 返回 `[]`，绝不向上抛
- `source_provider: "akshare_em"`
- 参数校验（`lookback_days <= 0` / `max_items <= 0` → `ValueError`）在触网前完成

### Ticker 归一化

本地 helper，不 import `westock_wrapper`（数据层，会拖进 subprocess/yfinance）：

| 输入 | 输出 |
|---|---|
| `1810.HK` | `01810`（zfill 5） |
| `600519.SS` | `600519` |
| `PDD` | `PDD` |

### 时区（关键正确性点）

`发布时间` 是**朴素北京时间**。`naked_k_news._to_utc` 把朴素时间当 UTC 处理，会产生 8 小时误差，使条目看起来更新或更旧。必须显式 `tz_localize("Asia/Shanghai").tz_convert("UTC")`。

### 窗口过滤

Finnhub 靠 API 的 from/to 收窗；akshare 固定返回 10 条不管窗口，且 `naked_k_news_enhanced` 本身不做窗口过滤（只打分+去重）。因此必须在采集器内做客户端过滤：`now - lookback_days <= published_at <= now`，否则 5 月的旧闻会漏进报告。

### 合并器接入 `naked_k_news_enhanced.py`

- 质量权重 **2.0**（介于 Finnhub 3.0 与 Google 1.0 之间）
- **保留相关性过滤** —— 不照抄 Finnhub 在 `:117` 的 `or source_provider == "finnhub"` 豁免。`09992` 的结果里混了"港股通净卖出"这类通用资金流噪音，必须过滤。`company_names.json` 的 `zh` 字段正好给中文标题打分
- 新增 `use_akshare: bool = True`、`akshare_fetch=None`（注入点与 HTTP 的 `get` 不同）

## 安全边界

`新闻内容` 是全文正文，比现有源的 summary 长。按现有惯例 clip 到 500，走 `sanitize_provider_value` 与 `naked_k_news_llm` 隔离逻辑。

不动两遍推演边界：新源只是多几个 evidence ID；round 1 仍只看新闻；方向翻转仍由 `naked_k_synthesis.py` 的确定性价格函数重建。

## 依赖

akshare 拖 14 个依赖（mini-racer / curl_cffi / lxml / html5lib / openpyxl / xlrd…），当前 `requirements.txt` 只有 4 个。**做成可选依赖**：函数内 import，缺失即降级返回空列表，与 Finnhub 现行方式一致。不进 `requirements.txt`，写进 README 可选安装。

## TDD 步骤

1. `tests/test_naked_k_news_akshare.py` → RED → 实现 `naked_k_news_akshare.py`
2. 更新 `tests/test_naked_k_news_enhanced.py` 接入契约 → RED → 改 `naked_k_news_enhanced.py`

现有 enhanced 测试未 patch akshare，会真实触网 —— 违反"测试不碰网络"。必须在这些测试里补 patch。

## 验证

`python -m unittest discover -v` 全绿；`--news` 端到端不因新源失败而退化。

## 实施结果

285 测试全绿（新增 4 个模块外测试 + 11 个采集器测试）。`requirements.txt` 未改动，akshare 保持可选。

### 实施中发现的两个缺陷（原计划未预见）

**1. CJK 短关键词永不命中（既有缺陷，影响所有中文源）**

`_calculate_relevance_score` 对 `len <= 3 and isalpha()` 的关键词走 `\b` 词边界匹配。Python 的 `isalpha()` 对中文为真，而 `\b` 由 `\w` 定义、中文无空格，因此 `\b小米\b` 在「小米集团回购股份」中永不匹配 —— 小米/腾讯/拼多多全部评 0 分。修复：该分支增加 `isascii()` 限制。

这个缺陷在接入 akshare 前就存在（`company_names.json` 的 `zh` 字段一直失效），但只有引入中文源后才会实际影响结果。

**2. 全市场资金流水表绕过相关性门（新源引入）**

东方财富混入「港股通净卖出」「南向资金」这类流水表，其正文列出了每一个 ticker 代码**与发行人名称**。原计划以为保留默认门槛（>= 1）即可过滤，实测不行：正文里的裸代码 `1810` 命中一次即恰好达到阈值 1.0。

第一版改成 `>= 3` 仍不足 —— 正文同时含 `腾讯` + `腾讯控股` + `0700`，三次正文命中累加也到 3.0。最终方案：AkShare 走**标题命中**门（`title_score >= 3`），正文完全不参与其准入判断。抽出 `_passes_relevance_gate` 承载这一按源分流的逻辑。

第一版测试之所以误判通过，是因为 fixture 里设了 `summary=title`，没有建模真实正文 —— 实盘验证才暴露出来。教训：新源的 fixture 必须照抄真实 payload 形状。

### 实盘验证（2026-07-31，接口真实调用）

| ticker | 采集 | 过滤后保留 | 说明 |
|---|---|---|---|
| `1810.HK` | 6 | 5 | 全为小米回购公告，1 条流水表被拦 |
| `0700.HK` | 5 | 5 | 全为腾讯回购公告 |
| `9992.HK` | 6 | 4 | 泡泡玛特实质新闻，2 条资金流噪音被拦 |
| `PDD` | 6 | 0 | 见下 |

`PDD` 归零是正确结果：唯一接近的「速卖通被欧盟开出5.5亿欧元罚单」是速卖通新闻，仅在正文把拼多多/Temu 当作先例引用，不算 PDD 消息。

### 已知限制

**未登记 `company_names.json` 的标的，AkShare 实际贡献为零。** 标题门要求命中公司名，而未登记标的只有裸代码可匹配 —— 港股/A 股标题极少直接写代码。实测 `600519.SS`（贵州茅台，未登记）采到 6 条全是「70只个股突破半年线」这类全市场筛选噪音，全部被拦，`status=insufficient`。

这是可接受的取舍：宁可无贡献，也不能放噪音进两遍推演。要扩展覆盖，就给 `company_names.json` 补 `zh` 名称条目 —— 无需改代码。
