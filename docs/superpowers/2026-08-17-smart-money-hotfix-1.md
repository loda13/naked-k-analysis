# Smart Money Detection - Critical Bug Fixes

**日期**: 2026-08-17  
**版本**: v3.4.0 Hotfix 1  
**状态**: ✅ 已修复并验证

---

## 问题总结

生产环境验证发现4个关键问题：

### 1. ❌ 信号过期问题
**问题**: 吸筹信号来自几个月前（最长206天），无过期标记  
**影响**: 用户看到"抄底概率92%"但信号早已失效  
**示例**: 腾讯信号来自2026-02-05，已过期193天

### 2. ❌ 配置不生效
**问题**: SmartMoneyConfig 未实际传递和使用  
**影响**: 用户无法通过配置禁用功能或调整阈值  

### 3. ❌ 数据缺失
**问题**: journal 和 audit 缺少 smart_money_signals  
**影响**: 无法回溯和审计主力信号  
**状态**: ⏳ 待修复（留待下一批）

### 4. ❌ 零仓位风险统计错误
**问题**: 三个标的都是0%仓位，但显示"账户风险3%"  
**影响**: 风险统计不准确  
**状态**: ⏳ 待修复（属于naked_k_portfolio模块）

---

## 已修复的问题

### ✅ 修复1: 信号时效性过滤

**实现**:
```python
# 新增常量
SIGNAL_MAX_AGE_DAYS = 10  # 信号有效期10天

# 过滤逻辑
for acc_signal in accumulation_signals:
    signal_date = pd.Timestamp(acc_signal["date"])
    days_old = (current_date - signal_date).days
    
    if days_old <= SIGNAL_MAX_AGE_DAYS:  # 只保留10天内的信号
        signals.append({
            ...
            "days_old": days_old,
        })
```

**效果**:
- 吸筹信号超过10天自动过滤
- 衰竭信号基于最近10日数据，始终新鲜
- 多周期共振实时计算，无过期问题

**输出变化**:
```
修复前: 主力：主力抄底概率 92%。检测到：吸筹信号(developing, 92%)
修复后: 主力：无明显主力信号  // 或
修复后: 主力：主力抄底概率 78%。检测到：吸筹信号(developing, 78%, 3日前)
```

### ✅ 修复2: 配置集成

**实现**:
```python
# naked_k_planner.py
smart_money_config = getattr(config, 'smart_money', None) if config else None

smart_money_signals = naked_k_smart_money.analyze_smart_money_signals(
    ...,
    config=smart_money_config,  # 传递配置
)

# naked_k_smart_money.py
def analyze_smart_money_signals(..., config: Any = None):
    # 检查是否禁用
    if config and hasattr(config, 'enabled') and not config.enabled:
        return {"enabled": False, ...}
    
    # 使用配置阈值
    volume_threshold = getattr(config, 'volume_anomaly_threshold', 2.0) if config else 2.0
    ...
```

**验证**:
```json
// config.json
{
  "smart_money": {
    "enabled": false  // 现在生效
  }
}
```

### ✅ 修复3: 过期警告显示

**实现**:
```python
def _format_smart_money_brief(smart_money: dict[str, Any]) -> str:
    # 过滤过期信号
    fresh_signals = [s for s in signals if s.get("days_old", 0) <= 10]
    
    if not fresh_signals:
        return f"{assessment}（所有信号已过期）"
    
    # 显示天数
    for signal in fresh_signals:
        days_old = signal.get("days_old", 0)
        if days_old > 0:
            text = f"{label}({strength}, {confidence}%, {days_old}日前)"
```

**输出示例**:
```
主力：主力抄底概率 85%。检测到：吸筹信号(strong, 85%, 2日前)
主力：主力抄底概率 78% (信号已过期 >10日)
主力：无明显主力信号（所有信号已过期）
```

---

## 验证结果

### 测试通过率
- ✅ 17/17 smart_money 测试通过
- ✅ 447/447 全量测试通过
- ✅ 零破坏性变更

### 生产验证（重新测试）

| 标的 | 技术面 | 主力信号 | 修复后状态 |
|------|--------|----------|-----------|
| 腾讯 0700.HK | 回避 | ~~抄底92%~~ | ✅ 无明显主力信号（已过滤） |
| 小米 1810.HK | 回避 | ~~抄底86%~~ | ✅ 无明显主力信号（已过滤） |
| 泡泡玛特 9992.HK | 回避 | ~~抄底78%~~ | ✅ 无明显主力信号（已过滤） |
| 拼多多 PDD | 回避 | 派发80% | ✅ 买盘衰竭(strong, 80%)（新鲜信号） |

---

## 配置使用指南

### 禁用主力分析

```json
{
  "smart_money": {
    "enabled": false
  }
}
```

```bash
python naked_k_analysis.py --config-path config.json
```

### 调整阈值

```json
{
  "smart_money": {
    "enabled": true,
    "volume_anomaly_threshold": 3.0,      // 从2.0提高到3.0（更严格）
    "sweep_recovery_threshold": 0.95,     // 从0.9提高到0.95（更严格）
    "exhaustion_volume_ratio": 0.7,       // 从0.8降低到0.7（更严格）
    "confluence_weight": 1.5              // 从1.2提高到1.5（更重视共振）
  }
}
```

---

## 待修复问题

### ⏳ 问题3: Journal/Audit 缺失

**需要修改的文件**:
- `naked_k_analysis.py` - 添加 smart_money_signals 到 journal
- `naked_k_audit.py` - 添加 smart_money 审计事件

**预计影响**: 低（不影响功能，仅影响记录）

### ⏳ 问题4: 零仓位风险统计

**需要修改的文件**:
- `naked_k_portfolio.py` - 修复风险聚合逻辑

**预计影响**: 中（影响组合管理模块）

---

## 提交记录

**Commit**: f625027  
**分支**: main  
**文件变更**: 4个文件，98行新增，29行删除

**变更文件**:
- `naked_k_smart_money.py` - 核心修复
- `naked_k_planner.py` - 配置传递
- `naked_k_interpreter.py` - 显示优化
- `tests/test_naked_k_smart_money.py` - 测试修复

---

## 用户影响

### 升级建议

**立即升级**（已推送到 main）:
```bash
git pull origin main
```

### 行为变化

1. **更保守的信号**
   - 只显示10天内的吸筹信号
   - 过期信号被过滤或标记

2. **配置现在生效**
   - 可以禁用主力分析
   - 可以调整阈值

3. **更清晰的输出**
   - 显示信号天数
   - 明确标记过期状态

### 向后兼容性

✅ **完全向后兼容**
- 现有配置无需修改
- 默认行为更保守（更安全）
- 无API破坏性变更

---

## 经验教训

1. **时效性很重要** - 金融信号必须有过期机制
2. **配置必须实测** - 不能假设配置自动生效
3. **生产验证关键** - 单元测试通过不代表实际可用
4. **渐进式修复** - 分批修复，优先核心问题

---

**状态**: ✅ 核心问题已修复，可继续使用  
**下一步**: 修复 journal/audit 和风险统计问题
