# Smart Money Detection - Hotfix Round 2

**日期**: 2026-08-17  
**Commit**: 74cd06b  
**状态**: ⚠️ 部分修复，仍有3个问题待解决

---

## 📊 修复进度总览

| 问题 | 状态 | 说明 |
|------|------|------|
| 1. 信号时效性 | ✅ 已修复 | 10天过期机制生效 |
| 2. 配置集成 | ✅ 已修复 | enabled标志和阈值参数生效 |
| 3. 过期信号审计 | ✅ 已修复 | 保留stale标记，返回fresh/stale分离列表 |
| 4. 配置阈值使用 | ✅ 已修复 | volume_ratio_threshold实际使用 |
| 5. Journal集成 | ⏳ 待修复 | smart_money_signals未写入journal |
| 6. Audit集成 | ⏳ 待修复 | 缺少结构化smart_money字段 |
| 7. 零仓位风险统计 | ⏳ 待修复 | 0%仓位显示3%风险（portfolio模块） |

---

## ✅ 本轮修复内容

### 1. 保留过期信号用于审计

**问题**: 过期信号被直接丢弃，无法审计  
**修复**: 

```python
# 为每个信号添加 stale 标志
signals.append({
    ...
    "days_old": days_old,
    "stale": is_stale,  # 新增
})

# 返回分离的列表
return {
    "signals": signals,           # 所有信号
    "fresh_signals": fresh_signals,  # 新增：仅新鲜信号
    "stale_signals": stale_signals,  # 新增：仅过期信号
}
```

**效果**:
- 所有信号保留在 `signals` 数组中
- 过期信号标记 `stale=True`
- 便于审计和回溯分析

### 2. 配置阈值实际使用

**问题**: sweep_recovery_threshold 和 exhaustion_volume_ratio 被读取但未使用  
**修复**:

```python
# 函数签名修改
def detect_selling_exhaustion(
    frame, 
    lookback=10, 
    volume_window=20,
    volume_ratio_threshold=0.8  # 新增参数
):
    ...
    volume_dried = volume_ratio < volume_ratio_threshold  # 使用配置值

# 调用时传递配置
exhaustion = detect_selling_exhaustion(
    daily_df, 
    volume_window=20,
    volume_ratio_threshold=exhaustion_ratio  # 从config读取
)
```

**验证**:
```json
{
  "smart_money": {
    "exhaustion_volume_ratio": 0.7  // 现在生效，从0.8改为0.7
  }
}
```

### 3. 改进显示逻辑

**修复前**:
```
主力：主力抄底概率 92%（腾讯，信号来自193天前）
```

**修复后**:
```
主力：无明显主力信号（1个信号已过期）
主力：主力抄底概率 85%。检测到：吸筹信号(strong, 85%, 2日前)；另有1个过期信号
```

---

## ⏳ 仍待修复的问题

### 问题5: Journal 缺失 smart_money_signals

**当前状态**:
```jsonl
// journal 中没有 smart_money_signals 字段
{"ticker": "0700.HK", "action": "回避", ...}
```

**需要修复**:
```jsonl
{"ticker": "0700.HK", "action": "回避", "smart_money_signals": {...}, ...}
```

**修复位置**: `naked_k_analysis.py` - 写入journal的地方

**影响**: 无法通过journal回溯主力信号历史

---

### 问题6: Audit 缺少 smart_money 事件

**当前状态**:
```jsonl
// audit 中没有 smart_money 相关事件
{"event": "run_start", ...}
{"event": "instrument_analyzed", ...}
```

**需要添加**:
```jsonl
{"event": "smart_money_detected", "ticker": "0700.HK", "signals": [...], ...}
```

**修复位置**: `naked_k_planner.py` 或 `naked_k_analysis.py`

**影响**: 审计追踪不完整

---

### 问题7: 零仓位风险统计错误

**问题描述**:
- 腾讯/小米/泡泡玛特均为 0% 仓位
- 但组合显示"账户风险 3%"

**根本原因**: 
- 属于 `naked_k_portfolio.py` 模块的风险聚合bug
- 不是 smart_money 模块的问题

**修复位置**: `naked_k_portfolio.py` 的风险计算逻辑

**影响**: 风险统计不准确，影响组合管理决策

---

## 🧪 测试验证

### 单元测试
```bash
python -m unittest tests.test_naked_k_smart_money -v
# 17/17 通过 ✅

python -m unittest discover -s tests -p "test_*.py"
# 447/447 通过 ✅
```

### 生产测试

需要重新运行三个标的验证：

**预期结果**:
1. ✅ 过期信号不显示为当前概率
2. ✅ 如果有过期信号，显示"另有N个过期信号"
3. ✅ Config阈值调整后行为改变
4. ⏳ Journal仍缺失（待下轮修复）
5. ⏳ Audit仍缺失（待下轮修复）

---

## 📝 使用示例

### 查看所有信号（包括过期）

```python
from naked_k_smart_money import analyze_smart_money_signals

result = analyze_smart_money_signals(...)

print(result['signals'])  # 所有信号
# [
#   {"label": "吸筹信号", "days_old": 3, "stale": False, ...},
#   {"label": "吸筹信号", "days_old": 25, "stale": True, ...}
# ]

print(result['fresh_signals'])  # 仅新鲜信号
# [{"label": "吸筹信号", "days_old": 3, ...}]

print(result['stale_signals'])  # 仅过期信号
# [{"label": "吸筹信号", "days_old": 25, ...}]
```

### 调整阈值测试

```json
// config.json
{
  "smart_money": {
    "exhaustion_volume_ratio": 0.7  // 从0.8改为0.7（更严格）
  }
}
```

运行后，卖压衰竭信号会更少（因为要求成交量 < 70% 才算衰竭）

---

## 🎯 下一步行动

### 优先级1: Journal 集成（30分钟）
- 修改 `naked_k_analysis.py`
- 添加 `smart_money_signals` 字段到journal写入
- 测试验证

### 优先级2: Audit 集成（20分钟）
- 添加 `AuditLogger.log_smart_money_signal()` 方法
- 在 `naked_k_planner.py` 调用
- 测试验证

### 优先级3: 零仓位风险统计（60分钟）
- 调查 `naked_k_portfolio.py` 风险聚合逻辑
- 定位0%仓位显示3%风险的原因
- 修复并测试

---

## 📊 改进统计

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 过期信号处理 | 丢弃 | 保留+标记 |
| 配置阈值 | 未使用 | 已使用 |
| 审计完整性 | 部分 | 部分（仍缺journal/audit） |
| 测试通过率 | 447/447 | 447/447 |
| 用户可见改进 | 无过期提示 | 有过期提示 |

---

## 🔗 相关文档

- 第一轮修复: `docs/superpowers/2026-08-17-smart-money-hotfix-1.md`
- 原始设计: `docs/superpowers/specs/2026-08-17-smart-money-detection-design.md`
- 用户指南: `docs/superpowers/smart-money-user-guide.md`

---

**当前状态**: ⚠️ 核心功能可用，审计和journal集成待完善  
**下次验证**: 完成journal/audit集成后重测
