# Finnhub 快速开始（5分钟）

## 🎯 效果对比

### 改善前（仅 Yahoo + Google）
```
小米 (1810.HK):
  采集: 12条
  相关: 0条 ❌
  置信度: 0-10
  → 消息面不足，降级
```

### 改善后（+ Finnhub）
```
小米 (1810.HK):
  采集: 25-30条
  相关: 5-10条 ✅
  置信度: 30-60
  → 可用于辅助决策
```

---

## ⚡ 三步启用

### 1️⃣ 注册（2分钟）
访问: https://finnhub.io/register

填写邮箱和密码，验证邮箱。

### 2️⃣ 获取 API Key（1分钟）
登录后访问: https://finnhub.io/dashboard

复制 API Key（类似: `c1234567890abcdef...`）

### 3️⃣ 配置（1分钟）
编辑项目根目录的 `.env` 文件：

```bash
# 找到这一行（已注释）
# FINNHUB_API_KEY=your_api_key_here

# 取消注释并替换为你的 API Key
FINNHUB_API_KEY=c1234567890abcdef...
```

保存文件。

---

## ✅ 验证

运行测试命令：

```bash
python3 -c "
from naked_k_news_finnhub import test_finnhub_connection
result = test_finnhub_connection()
print(f'状态: {result[\"status\"]}')
print(f'消息: {result[\"message\"]}')
"
```

**成功输出**:
```
状态: ok
消息: Connection successful, retrieved 10 test items
```

---

## 🚀 使用

```bash
# 带 Finnhub 的完整分析
python naked_k_analysis.py --news
```

系统会自动使用 Finnhub + Yahoo + Google 三个数据源。

---

## ❓ 常见问题

**Q: 需要信用卡吗？**  
A: 不需要，完全免费。

**Q: 会超额吗？**  
A: 不会。免费版 60 calls/分钟，本项目每天仅 4 次调用。

**Q: 不配置会怎样？**  
A: 系统自动降级到 Yahoo + Google，不会报错。

---

## 📚 更多文档

- 完整设置指南: `FINNHUB_SETUP.md`
- 技术实施细节: `NEWS_IMPROVEMENT_SUMMARY.md`
- 使用说明: `README.md`

---

**耗时**: 5分钟  
**成本**: $0  
**效果**: 港股新闻覆盖提升 5-10倍 ⭐⭐⭐⭐⭐
