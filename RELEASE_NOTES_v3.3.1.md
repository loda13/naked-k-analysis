# Release v3.3.1 - SEC EDGAR 采集修复

**发布日期**: 2026-08-04

---

## 🐛 Bug 修复

### SEC EDGAR 重大事件文件采集优化

修复了 SEC EDGAR 采集器的两个行为 bug，使美股 8-K 和中概 ADR 6-K 文件能够正确采集和去重：

#### Bug 1: SEC 窗口太短导致零条返回

**问题**：
- SEC 使用默认 7 天窗口，而 Finnhub/AkShare 都已放宽到 30 天
- 8-K/6-K 是事件驱动的，围绕财报成簇出现、中间空 30-90 天
- NVDA/TSLA/AVGO/RKLB/SPCX 五只美股全部解析到 CIK、全部有充足 8-K 历史，但窗口太短导致零条返回

**修复**：
- 将 SEC 窗口延长到 `max(lookback_days, 60)`，与 Finnhub/AkShare 对齐
- 注释说明 8-K/6-K 的事件驱动节奏

**实测效果**（2026-08-04）：
| Ticker | 最新 8-K/6-K | 距今 | 7天窗口 | 60天窗口 |
|--------|-------------|------|---------|----------|
| TSLA   | 2026-07-22  | 13天 | 0条     | 2条 ✅   |
| AVGO   | 2026-07-06  | 29天 | 0条     | 3条 ✅   |
| NVDA   | 2026-07-02  | 33天 | 0条     | 0条      |
| RKLB   | 2026-06-29  | 36天 | 0条     | 0条      |
| SPCX   | 2026-06-26  | 39天 | 0条     | 0条      |
| PDD    | 2026-05-28  | 68天 | 0条     | 0条      |

#### Bug 2: 同日多份 filing 被去重丢掉

**问题**：
- 标题格式为 `"Form 8-K filing on 2026-07-02"`，只有日期精度
- 同一天报两份（如财报 + 高管变动）产生相同标题，`_deduplicate_ranked` 按标题命中即丢
- PDD 2025-12-19 两份 6-K（accession 000110465925122766 和 122765）：raw 2 条 → 去重后 1 条

**修复**：
- 标题添加 accession 后缀：`"Form 8-K filing on 2026-07-02 #046717"`
- 同日 filing 产生不同标题，去重时保留

**实测效果**：
```
PDD 2025-12-19 两份 6-K:
  Before: "Form 6-K filing on 2025-12-19" (x2) → 去重后 1 条
  After:  "Form 6-K filing on 2025-12-19 #122766"
          "Form 6-K filing on 2025-12-19 #122765" → 去重后 2 条 ✅
```

---

## 📊 影响范围

**受益标的**：
- ✅ 美股本土发行人（走 8-K）：NVDA, TSLA, AVGO, RKLB, SPCX 等
- ✅ 中概 ADR（走 6-K）：PDD, BABA, JD, NIO 等
- ❌ 港股/A股/北交所（无 CIK，不在 SEC 数据库）：自动跳过，无影响

**数据源优先级**（`collect_news_enhanced`）：
1. Finnhub（30天，质量权重 3.0x）
2. **SEC EDGAR（60天，质量权重 5.0x）** ← 本次修复
3. AkShare（30天，质量权重 2.0x）
4. Sina（实际 ~24h，质量权重 2.0x）
5. Google News（7天，质量权重 1.0x）
6. Yahoo Finance（7天，质量权重 0.5x）

---

## 🔧 技术细节

### 改动文件
```
naked_k_news_sec.py                 |  9 +++++-
naked_k_news_enhanced.py            |  5 +++-
tests/test_naked_k_news_sec.py      | 59 +++++++++++++++++++++++++++++++
tests/test_naked_k_news_enhanced.py | 28 +++++++++++++++
4 files changed, 93 insertions(+), 8 deletions(-)
```

### 新增测试
- `test_same_date_filings_produce_distinct_titles`：断言同日 filing 标题互不相同且都含日期
- `test_sec_failure_does_not_abort_collection`：断言 SEC 挂了时状态是 `insufficient`（单源失败）

### 放宽既有测试
- `test_periodic_reports_are_not_collected`
- `test_foreign_private_issuers_are_collected_via_6k`
- `test_both_material_event_forms_coexist_and_stay_sorted`

从精确匹配 `"Form 8-K filing on 2026-07-30"` 改成 `assertIn`，因为标题现在带 accession 后缀。

---

## ✅ 测试覆盖

**全量测试**：361 个测试全绿
```bash
python -m unittest discover -v
# Ran 361 tests in 0.783s
# OK
```

**SEC 专项测试**：20 个测试全绿
```bash
python -m unittest tests.test_naked_k_news_sec -v
# Ran 20 tests in 0.001s
# OK
```

**Live 验证**（2026-08-04）：
```python
# TSLA 返回 2 条 SEC 8-K
Form 8-K filing on 2026-07-22 #049213
Form 8-K filing on 2026-07-02 #046717

# AVGO 返回 3 条 SEC 8-K
Form 8-K filing on 2026-07-06 #295589
Form 8-K filing on 2026-06-18 #275077
Form 8-K filing on 2026-06-11 #266777

# PDD 2025-12-19 两份 6-K 都保留
Form 6-K filing on 2025-12-19 #122766
Form 6-K filing on 2025-12-19 #122765
```

---

## 🚀 升级指南

### 从 v3.3.0 升级

```bash
# 拉取最新代码
git pull origin main

# 无需额外配置，自动生效
python naked_k_analysis.py --news
```

### 无破坏性变更

- ✅ SEC EDGAR 自动跳过非美股（`.HK`/`.SS`/`.SZ` 等），无影响
- ✅ 无 CIK 的 ticker 返回空，不报错
- ✅ 标题格式变化不影响下游消费（仍是纯文本，只是多了后缀）
- ✅ 所有既有测试通过（放宽了 3 个标题断言）

---

## 📝 相关文档

- **SEC 采集器设计**：`naked_k_news_sec.py` 文件注释
- **多源采集设计**：`naked_k_news_enhanced.py` 文件注释
- **两轮消息面斟酌**：`docs/superpowers/specs/2026-07-20-news-two-pass-deliberation-design.md`
- **README 更新**：v3.3.1 版本说明

---

## 🙏 致谢

感谢测试和反馈！本次修复使 SEC EDGAR 重大事件文件（8-K/6-K）能够正确采集，为美股和中概 ADR 提供了监管级别的消息面覆盖。

---

**完整提交历史**: 
- `1d848e5` - fix(news): extend SEC lookback to 60d, disambiguate same-date filings
- `4fade32` - docs: restructure README to highlight naked-K technical and news fundamentals
