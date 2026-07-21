# 消息面增强方案

## 当前问题诊断

### 小米案例分析（2026-07-21）
- **查询**: "小米 1810.HK" / "Xiaomi 1810.HK"
- **结果**: 采集到10-14条新闻，但**0条相关**
- **原因**:
  1. Yahoo Finance/Google News 搜索质量不足
  2. 港股新闻覆盖度低
  3. 缺少中文财经媒体
  4. 缺少公司官方公告

### 根本问题
```
当前架构: Yahoo Finance + Google News RSS (2个源)
          ↓
     采集通用财经新闻
          ↓
     模型过滤（第一轮）
          ↓
     ❌ 全部不相关 → 降级
```

**症结**: 采集端质量不足，模型无法弥补

---

## 增强方案

### 方案 A: 多语言查询优化 ✅ 已实现
**文件**: `naked_k_news_enhanced.py` + `company_names.json`

**改进**:
- 英文名称: Xiaomi, Xiaomi Corporation
- 中文名称: 小米, 小米集团
- 关键词: Lei Jun, Xiaomi EV, 小米汽车

**效果**: 
- ✅ 采集量增加（10→14条）
- ❌ 相关性未改善（仍然0条相关）

**结论**: 多查询帮助有限，需要更专业的新闻源

---

### 方案 B: 新增专业新闻源（推荐）

#### B1. 港交所披露易 ⭐⭐⭐⭐⭐
**成本**: 免费  
**权威性**: 最高（官方公告）  
**实施难度**: 低

**API**:
```
https://www1.hkexnews.hk/listedco/listconews/sehk/{stock_code}/...
```

**优势**:
- ✅ 财报、业绩预告、董事变动等重大事项
- ✅ 中英双语
- ✅ 零成本
- ✅ 适合所有港股（腾讯、小米、泡泡玛特）

**数据示例**:
```json
{
  "title": "小米集团：二零二六年度中期业绩公告",
  "date": "2026-07-15",
  "type": "财务报告",
  "url": "https://www1.hkexnews.hk/..."
}
```

#### B2. Finnhub ⭐⭐⭐⭐
**成本**: 免费（60 calls/min）  
**覆盖**: 全球股市  
**实施难度**: 低

**API**:
```bash
curl "https://finnhub.io/api/v1/company-news?symbol=1810.HK&from=2026-07-14&to=2026-07-21&token=YOUR_API_KEY"
```

**优势**:
- ✅ 专业财经新闻聚合
- ✅ 港股、美股全覆盖
- ✅ 免费额度充足（4个标的，每天4次，每次60条 = 够用）
- ✅ 简单 REST API

**注册**: https://finnhub.io/register (免费)

#### B3. Alpha Vantage ⭐⭐⭐
**成本**: 免费（25 calls/day）  
**覆盖**: 美股为主，港股有限  
**实施难度**: 低

**API**:
```bash
curl "https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers=1810.HK&apikey=YOUR_API_KEY"
```

**限制**:
- ⚠️ 每天25次调用（勉强够4个标的）
- ⚠️ 港股覆盖不如 Finnhub

**适合**: 美股（PDD）

---

### 方案 C: yfinance 新闻增强
**当前问题**: yfinance 的 `Search` API 返回通用财经新闻

**改进方向**:
1. 使用 `yfinance.Ticker(symbol).news` 直接获取股票新闻
2. 增加重试机制
3. 添加时间窗口过滤

**代码示例**:
```python
import yfinance as yf

ticker = yf.Ticker("1810.HK")
news = ticker.news  # 直接获取该股票的新闻
```

**优势**:
- ✅ 零配置
- ✅ 不需要额外 API key
- ✅ 可能比 Search API 更精准

---

## 推荐实施路径

### 第一阶段（立即）: yfinance 新闻增强
**目标**: 改善 Yahoo Finance 新闻质量  
**工作量**: 1-2小时  
**文件**: 修改 `naked_k_news.py`

**改动**:
```python
# 从 Search API 改为 Ticker.news API
def _yahoo_candidates_enhanced(ticker: str):
    import yfinance as yf
    try:
        ticker_obj = yf.Ticker(ticker)
        return ticker_obj.news  # 更精准的新闻
    except:
        # fallback to Search API
        pass
```

### 第二阶段（短期）: 添加 Finnhub
**目标**: 专业财经新闻覆盖  
**工作量**: 2-3小时  
**文件**: 新建 `naked_k_news_finnhub.py`

**步骤**:
1. 注册 Finnhub 免费账号
2. 获取 API key
3. 添加到 `.env`: `FINNHUB_API_KEY=xxx`
4. 实现 Finnhub 采集器
5. 集成到 `naked_k_news_enhanced.py`

### 第三阶段（中期）: 港交所披露易
**目标**: 官方公告权威性  
**工作量**: 4-6小时（需要解析 HTML/XML）  
**文件**: 新建 `naked_k_news_hkex.py`

**挑战**:
- 港交所网站结构复杂
- 需要解析多种文件格式
- 中英文混合

### 第四阶段（长期）: 中文财经媒体
**目标**: 补充中文市场信息  
**工作量**: 8-10小时  
**风险**: 爬虫维护成本高

---

## 效果预期

### 当前（v3.1.0）
```
数据源: Yahoo Search + Google RSS (2源)
相关性: 0/10 (小米案例)
置信度: 0-10
```

### 第一阶段后
```
数据源: Yahoo Ticker.news + Google RSS (2源优化)
相关性: 2-5/10 (预期改善)
置信度: 10-30
```

### 第二阶段后
```
数据源: Yahoo + Google + Finnhub (3源)
相关性: 5-8/10 (专业新闻)
置信度: 30-60
```

### 第三阶段后
```
数据源: Yahoo + Google + Finnhub + 港交所 (4源)
相关性: 8-10/10 (含官方公告)
置信度: 60-80
```

---

## 配置建议

### 环境变量
```bash
# .env
# Finnhub (第二阶段)
FINNHUB_API_KEY=your_free_api_key

# Alpha Vantage (备选)
ALPHAVANTAGE_API_KEY=your_free_api_key
```

### CLI 参数
```bash
# 当前可用
python naked_k_analysis.py --news \
  --news-lookback-days 14 \
  --news-max-items 20

# 未来（第二阶段后）
python naked_k_analysis.py --news \
  --news-sources yahoo,google,finnhub,hkex \
  --news-lookback-days 14 \
  --news-max-items 20
```

---

## 测试计划

### 测试用例
1. **小米 (1810.HK)** - 港股，中文名称
2. **腾讯 (0700.HK)** - 港股，高活跃度
3. **PDD (PDD)** - 美股，中文公司
4. **泡泡玛特 (9992.HK)** - 港股，小盘股

### 成功标准
- ✅ 每个标的至少5条相关新闻
- ✅ 置信度 >= 45
- ✅ 覆盖多种新闻类型（公告/分析/事件）

---

## 立即可行的临时方案

在实施新数据源之前，可以：

1. **增加时间窗口**
```bash
--news-lookback-days 30  # 7→30天
```

2. **使用增强查询**
```bash
# 已实现 naked_k_news_enhanced.py
# 自动使用 "Xiaomi 1810.HK" 多语言查询
```

3. **手动补充（权宜之计）**
- 访问港交所网站手动查看公告
- 在报告中注明"建议补充港交所公告"

---

## 优先级建议

**立即（本周）**: 
- ✅ 多语言查询（已完成）
- 🔄 yfinance Ticker.news 改进

**短期（2周内）**: 
- ⏳ 注册 Finnhub + 集成

**中期（1月内）**: 
- ⏳ 港交所披露易

**长期（按需）**: 
- ⏳ 中文财经媒体爬虫

---

## 总结

**核心问题**: 当前新闻源质量不足，导致港股新闻覆盖度低

**最优方案**: Finnhub (专业) + 港交所 (权威) + Yahoo/Google (补充)

**最快见效**: yfinance Ticker.news API（1小时实施）

**最高性价比**: Finnhub 免费版（60 calls/min，足够4个标的）

**最权威**: 港交所披露易（官方公告，零成本）
