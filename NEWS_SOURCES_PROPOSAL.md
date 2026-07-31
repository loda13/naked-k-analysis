# 消息源补充方案

## 当前问题

根据分析，当前新闻采集系统存在以下缺口：

1. **滚动快讯缺失**：「小米澎程新车 25.99 万」这类分钟级重大事件无法及时捕获
2. **时效性滞后**：依赖 Finnhub、东财、Yahoo Finance，更新频率为小时到天级
3. **覆盖面不均**：美股深度报道较好（Finnhub），港股/A股实时动态较弱

---

## 推荐补充方案

### 🎯 **短期优先**（1-2周可上线）

#### 1. **财联社快讯 API**
- **覆盖范围**：A股、港股、美股实时滚动快讯
- **时效性**：秒级到分钟级，专业财经媒体
- **典型场景**：新车发布、回购公告、业绩预告、监管动态
- **接入方式**：
  - 官方 API（需付费订阅，约 ¥2000-5000/月）
  - 或通过 AkShare 的 `stock_news_em()` 接口（免费但可能不稳定）
- **数据格式**：标题、正文、时间戳、相关股票代码
- **优先级**：⭐⭐⭐⭐⭐

**实现建议**：
```python
def collect_cls_breaking_news(ticker: str, lookback_hours: int = 24) -> list[dict]:
    """
    从财联社获取指定股票的滚动快讯
    
    Returns:
        [
            {
                "title": "小米澎程新车25.99万元起售",
                "content": "...",
                "timestamp": "2026-07-31 14:23:00",
                "source": "财联社",
                "relevance_score": 0.95
            },
            ...
        ]
    """
    pass
```

---

#### 2. **新浪财经滚动新闻** — ✅ 已接入（`naked_k_news_sina.py`）
- **覆盖范围**：全市场快讯摘要（非按标的检索）
- **时效性**：分钟级
- **接入方式**：直连 `zhibo.sina.com.cn/api/zhibo/feed`（zhibo_id=152），
  **不走 akshare**
  - `akshare.stock_info_global_sina()` 把 `page_size` 写死成 20。该频道约
    45 分钟就有 100 条，20 条只覆盖十几分钟，`lookback_days=7` 形同虚设
  - 上游其实支持 `page` / `page_size`，实测 `page_size=100` 有效，
    翻 20 页 = 2000 条 ≈ **21.7 小时**（2026-07-31 实测）
  - 因此采集器自行翻页，直到某页整体早于 cutoff 为止，上限 20 页
  - 另注：不存在 `stock_news_sina()`；`stock_news_em()` 是东财，已由
    `naked_k_news_akshare.py` 接入，两者不重复
- **返回结构**：仅 `时间` / `内容` 两列，无逐条 URL 与来源，
  正文按 `【标题】正文` 打包，需自行拆分
- **实际能力边界**：单次翻页最多回溯约一天。**这是个偏近端的源**，
  深历史仍靠东财；它的价值在于时效，不在于窗口长度
- **归属判定**：全市场摘要，必须按**标题**匹配别名；正文经常提及无关公司
  - 港股只用补零五位码（`01810`），裸码 `1810` 会命中「利润暴增1810%」
  - 别名只取 `company_names.json` 的 `zh` / `en`，不取 `keywords`
    （`Mi`、`盲盒` 这类松散词在全市场摘要里会误配）
- **数据质量**：中等，但量大且快
- **优先级**：⭐⭐⭐⭐

---

### 🏢 **中期补强**（权威性 + 合规性）

#### 3. **港交所公告系统 (HKEx披露易)** — ⛔ 暂不可行
- **覆盖范围**：港股上市公司正式公告
- **实测结论（2026-07-31）**：**没有可用的免费接口**，本次未实现
  - `https://www1.hkexnews.hk/rss/rss.xml` → **404**，RSS 已下线
  - `https://www1.hkexnews.hk/rss/listedco_rss.xml` → **404**
  - `https://www1.hkexnews.hk/ncms/json/eds/app_a1_ec_*.json` → **404**
  - `titlesearch.xhtml` 返回 200，但是 JSF 页面，依赖 ViewState
    postback，不是稳定可解析的数据接口
  - `hkex-api` 这个 PyPI 包并不存在
- **可行路径**：订阅 HKEx 商业数据服务，或对披露易做有状态爬虫
- **现状**：港股公告已由东财（`akshare_em`）覆盖，缺口是时效而非有无
- **优先级**：⭐⭐（投入产出比低，除非确有一手时效需求）

---

#### 4. **SEC EDGAR (美股官方文件)**
- **覆盖范围**：美股上市公司 SEC 文件
- **内容类型**：
  - Form 8-K（重大事件）
  - Form 10-Q/10-K（季报/年报）
  - Form 4（内部人交易）
  - Form 13F（机构持仓）
- **接入方式**：
  - 官方 API：`https://www.sec.gov/data.json`
  - Python 库：`sec-api`, `sec-edgar-downloader`
- **适用标的**：PDD 等美股
- **优先级**：⭐⭐⭐

---

### 🌐 **长期探索**（社交情绪 + 另类数据）

#### 5. **雪球动态**
- **覆盖范围**：A股、港股、美股用户生成内容
- **内容类型**：
  - 热门讨论
  - 用户观点
  - 实地调研
  - 突发爆料
- **接入方式**：
  - 非官方 API/爬虫（需注意反爬）
  - 可能需要账号登录
- **数据处理**：
  - 需要过滤噪音（情绪化、虚假信息）
  - 可以提取情绪指标（看多/看空比例）
  - 适合作为「市场情绪」的辅助维度
- **优先级**：⭐⭐⭐

**注意事项**：
- 雪球数据质量参差不齐，需要建立「可信用户白名单」
- 仅作为补充信号，不能作为主要决策依据
- 可以用 LLM 做内容质量筛选和情绪分析

---

#### 6. **Twitter/X 财经博主聚合**
- **覆盖范围**：全球市场，时效性极强
- **内容类型**：
  - 突发新闻
  - 分析师观点
  - 行业动态
  - 数据图表
- **接入方式**：
  - Twitter API（需付费，Basic $100/月，Pro $5000/月）
  - 第三方聚合服务
- **数据处理**：
  - 建立「财经 KOL 白名单」（如 @unusual_whales、@livesquawk）
  - 需要去重和验证
- **优先级**：⭐⭐

---

## 技术架构建议

### 消息源优先级队列

```
优先级 1（官方 & 权威）：
  - HKEx 公告
  - SEC EDGAR
  - 公司官网 IR
  
优先级 2（专业财经媒体）：
  - 财联社快讯
  - 彭博终端（如果有预算）
  - 路透社
  
优先级 3（实时新闻聚合）：
  - 新浪财经
  - 东财快讯（现有）
  - Finnhub（现有）
  
优先级 4（社交情绪）：
  - 雪球热门
  - Twitter KOL
```

### 去重和融合策略

```python
def merge_news_from_multiple_sources(
    sources: list[NewsSource],
    ticker: str,
    lookback_hours: int
) -> list[NewsItem]:
    """
    从多个源采集新闻，去重并按权威性加权
    
    去重规则：
    1. 标题相似度 > 0.8 认为是同一条新闻
    2. 时间戳在 30 分钟内 + 关键词重合 > 5 个
    
    权威性加权：
    - 官方公告：1.0
    - 财联社/彭博/路透：0.9
    - 新浪/东财：0.7
    - 雪球/Twitter：0.5
    """
    pass
```

---

## 成本估算

| 消息源 | 接入方式 | 月成本 | 时效性 | 可信度 |
|--------|----------|--------|--------|--------|
| 财联社 | 官方 API | ¥2000-5000 | 秒级 | 高 |
| 新浪财经 | 免费（AkShare）| ¥0 | 分钟级 | 中 |
| HKEx | 无免费接口（实测 404）| 商业订阅 | — | 极高 |
| SEC | 官方免费 | ¥0 | 小时级 | 极高 |
| 雪球 | 爬虫 | ¥0-500 | 分钟级 | 低-中 |
| Twitter | API Basic | $100 ≈ ¥700 | 秒级 | 中 |

**推荐初期预算**：¥3000/月
- 财联社 API：¥2000
- Twitter Basic：¥700
- 其他免费源：¥0

---

## 实施路线图

### Phase 1（1 周）：免费源快速补充
- [x] 接入新浪财经滚动快讯（`naked_k_news_sina.py`，28 项单测）
- [x] ~~接入 HKEx 官方公告 RSS~~ → 实测无免费接口，已放弃（见上）
- [ ] 接入 SEC EDGAR RSS
- [x] 测试去重和融合逻辑（新浪 bypass 相关性闸门，参与统一去重与质量排序）

### Phase 2（2 周）：付费专业源
- [ ] 评估财联社 API 接入
- [ ] 或评估 Twitter API 接入
- [ ] 建立 KOL/可信源白名单

### Phase 3（4 周）：社交情绪层
- [ ] 雪球动态爬虫（需要稳定性测试）
- [ ] LLM 情绪分析和噪音过滤
- [ ] 情绪指标集成到分析报告

---

## 集成到现有系统

修改 `naked_k_news_enhanced.py` 的 `collect_news_enhanced()` 函数：

```python
def collect_news_enhanced(
    name: str,
    ticker: str,
    lookback_days: int,
    max_items: int,
    use_finnhub: bool = True,
) -> dict[str, Any]:
    """扩展采集逻辑"""
    
    sources = []
    
    # 现有源
    if use_finnhub:
        sources.append(collect_from_finnhub(ticker, lookback_days))
    sources.append(collect_from_eastmoney(name, lookback_days))
    
    # 新增源（按优先级）
    sources.append(collect_from_hkex(ticker, lookback_days))  # 官方公告
    sources.append(collect_from_cls(ticker, lookback_days))   # 财联社快讯
    sources.append(collect_from_sina(ticker, lookback_days))  # 新浪滚动
    
    # 可选：社交情绪
    if enable_social_sentiment:
        sources.append(collect_from_xueqiu(ticker, lookback_days))
    
    # 去重、融合、排序
    merged = merge_and_deduplicate(sources)
    ranked = rank_by_relevance_and_authority(merged, ticker, name)
    
    return {
        "status": "ok",
        "items": ranked[:max_items],
        "source_breakdown": {s["source"]: len(s["items"]) for s in sources}
    }
```

---

## 总结

**已完成**（0 成本）：
1. ✅ 新浪财经滚动快讯 —— 已接入，分钟级，是当前唯一的分钟级源

**下一步可做**（0 成本）：
2. SEC EDGAR（美股官方文件，`sec-edgar-downloader`）

**已排除**：
3. ⛔ HKEx 披露易 —— 无免费接口（RSS / ncms JSON 均 404），
   港股公告已由东财覆盖，缺口是时效而非有无

**值得投入**（性价比高）：
4. 财联社 API（¥2000/月）—— 秒级，覆盖面比新浪更专业

**长期探索**（需要验证）：
5. 雪球 + Twitter 情绪层

新浪滚动快讯的接入把中文快讯从「天级滞后」拉到了分钟级。2026-07-31 实测，
翻 20 页覆盖 21.7 小时，小米在该窗口内命中 7 条，含回购、新车定价、
高盛/野村评级——正是原先要等下一轮才拿到的那类事件。

两个已知边界，不要误读为「已解决所有问题」：

1. **窗口只有约一天**。这是个近端源，`--news-lookback-days 7` 对它无意义，
   深历史仍靠东财。
2. **按标题归属**，命中率取决于快讯标题是否点名标的。要进一步提高召回，
   需要财联社这类按标的检索的专业源（`stock_info_global_cls` 实测会挂住
   不返回，未接）。
