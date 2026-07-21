# Finnhub 设置指南

## 快速开始（5分钟）

### 第1步：注册 Finnhub 账号

1. 访问: https://finnhub.io/register
2. 填写信息:
   - Email
   - Password
   - 勾选 "I agree to the terms"
3. 点击 "Sign Up"
4. 验证邮箱（检查收件箱/垃圾箱）

### 第2步：获取 API Key

1. 登录后进入 Dashboard: https://finnhub.io/dashboard
2. 在 "API Key" 部分找到你的密钥
3. 复制 API Key（形如: `c1234567890abcdef...`）

### 第3步：配置到项目

打开项目根目录的 `.env` 文件，添加：

```bash
# Finnhub 专业财经新闻 API
FINNHUB_API_KEY=your_api_key_here
```

替换 `your_api_key_here` 为你的实际 API Key。

### 第4步：验证配置

运行测试命令：

```bash
python3 -c "
from naked_k_news_finnhub import test_finnhub_connection
import json
result = test_finnhub_connection()
print(json.dumps(result, indent=2))
"
```

**成功输出**:
```json
{
  "status": "ok",
  "message": "Connection successful, retrieved 10 test items",
  "api_key_prefix": "c1234567..."
}
```

### 第5步：运行完整分析

```bash
# 带 Finnhub 的完整分析
python naked_k_analysis.py --news
```

---

## 免费版额度说明

**Finnhub 免费版**:
- ✅ 60 calls/分钟
- ✅ 每月 unlimited calls（理论上）
- ✅ 公司新闻 API
- ✅ 港股、美股全覆盖

**本项目需求**:
- 4个标的 × 1次/天 = 4 calls/天
- 每次分析 < 5秒
- **完全在免费额度内** ✅

---

## 预期改善效果

### 改善前（仅 Yahoo + Google）

**小米 (1810.HK)**:
- 采集: 14条
- 相关: 0条 ❌
- 置信度: 0-10
- 状态: 消息面不足

**腾讯 (0700.HK)**:
- 采集: 10条
- 相关: 2条
- 置信度: 15
- 状态: 消息面不足

### 改善后（+ Finnhub）

**小米 (1810.HK)**:
- 采集: 25-30条
- 相关: 5-10条 ✅
- 置信度: 30-60
- 状态: 可用于辅助决策

**腾讯 (0700.HK)**:
- 采集: 30-40条
- 相关: 10-15条 ✅
- 置信度: 60-80
- 状态: 高质量分析

**PDD (PDD)**:
- 采集: 30-40条
- 相关: 15-20条 ✅
- 置信度: 70-85
- 状态: 高质量分析

---

## 常见问题

### Q1: 注册需要信用卡吗？
**A**: 不需要。免费版无需绑定信用卡。

### Q2: API Key 会过期吗？
**A**: 不会。除非你主动重置或账号被封。

### Q3: 如果超过免费额度会怎样？
**A**: 
- 免费版: 60 calls/分钟
- 本项目: 每天仅4次调用
- **不会超额** ✅

### Q4: 数据延迟多久？
**A**: 实时到几分钟延迟，取决于新闻源。

### Q5: 支持哪些市场？
**A**: 
- ✅ 美股（NYSE, NASDAQ）
- ✅ 港股（HKEX）
- ✅ A股（部分）
- ✅ 欧洲、日本等主流市场

### Q6: 不配置 Finnhub 可以用吗？
**A**: 可以。系统会自动降级到 Yahoo + Google，不会报错。

---

## 故障排查

### 错误：`no_api_key`
**问题**: 环境变量未设置  
**解决**: 检查 `.env` 文件，确保有 `FINNHUB_API_KEY=...`

### 错误：`api_error - Invalid API key`
**问题**: API Key 无效或过期  
**解决**: 
1. 重新登录 Finnhub Dashboard
2. 检查 API Key 是否完整复制
3. 必要时重新生成 API Key

### 错误：`connection_error`
**问题**: 网络问题  
**解决**:
1. 检查网络连接
2. 检查防火墙/代理设置
3. 尝试访问 https://finnhub.io

### 错误：`Rate limit exceeded`
**问题**: 超过 60 calls/分钟  
**解决**: 本项目不会触发此错误（每天仅4次调用）

---

## 技术细节

### API 端点
```
GET https://finnhub.io/api/v1/company-news
```

### 请求参数
```
symbol: 股票代码（如 "1810.HK", "PDD"）
from: 开始日期（YYYY-MM-DD）
to: 结束日期（YYYY-MM-DD）
token: API Key
```

### 响应格式
```json
[
  {
    "category": "company news",
    "datetime": 1689724800,
    "headline": "Xiaomi Reports Q2 Revenue Growth",
    "id": 123456,
    "image": "https://...",
    "related": "1810.HK",
    "source": "Reuters",
    "summary": "Xiaomi Corporation reported...",
    "url": "https://..."
  }
]
```

### 集成位置
- **模块**: `naked_k_news_finnhub.py`
- **集成**: `naked_k_news_enhanced.py`
- **调用**: `naked_k_synthesis.py` (通过 `collect_news_enhanced`)

---

## 进阶配置

### 环境变量优先级
```bash
# 方式1: .env 文件（推荐）
FINNHUB_API_KEY=xxx

# 方式2: 系统环境变量
export FINNHUB_API_KEY=xxx
```

### 禁用 Finnhub（临时）
```python
# 在代码中禁用
result = collect_news_enhanced(
    name="小米",
    ticker="1810.HK",
    use_finnhub=False  # 仅用 Yahoo + Google
)
```

### 调试模式
```python
from naked_k_news_finnhub import collect_finnhub_news

# 直接调用 Finnhub
news = collect_finnhub_news("1810.HK", lookback_days=7)
print(f"Finnhub 返回 {len(news)} 条新闻")
```

---

## 安全提示

⚠️ **不要提交 API Key 到 Git**

`.env` 文件已在 `.gitignore` 中，但仍需注意：
- ❌ 不要硬编码到代码
- ❌ 不要在公开场合分享
- ❌ 不要截图包含 API Key 的屏幕
- ✅ 使用环境变量
- ✅ 定期轮换 API Key

---

## 总结

**配置成本**: 5分钟  
**使用成本**: $0  
**效果提升**: 0条相关 → 5-10条相关  
**投资回报**: 极高 ⭐⭐⭐⭐⭐

**立即行动**: https://finnhub.io/register

---

## 支持

- **Finnhub 文档**: https://finnhub.io/docs/api
- **本项目文档**: `NEWS_IMPROVEMENT_SUMMARY.md`
- **技术支持**: Finnhub Support / GitHub Issues
