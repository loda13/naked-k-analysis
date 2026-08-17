# v3.4.1 Release Notes

**发布日期**: 2026-08-17

## ✨ 新特性

### Smart Money Detection 主力资金检测正式上线

纯 OHLCV 分析，识别机构/大资金行为模式，输出概率评分。默认启用。

**四类信号**：
- **吸筹信号**：放量 + 价格窄幅震荡（主力低位建仓）
- **卖压衰竭**：新低 + 量能萎缩（抄底前兆）
- **买盘衰竭**：新高 + 量能萎缩（顶部预警）
- **多周期共振**：日/周/月供需区重叠（长期布局区）

**输出示例**：
```markdown
主力行为：主力抄底概率 92%
- 吸筹信号（置信度 78%）：放量2.3倍但价格窄幅震荡
- 多周期需求共振（置信度 85%）：日线、周线、月线需求区三重共振
```

**特性**：
- ✅ 过期信号自动过滤（10 天窗口）
- ✅ 方向判断准确（bearish 共振 → 主力派发）
- ✅ 可配置阈值（volume_anomaly_threshold / exhaustion_volume_ratio / confluence_weight）
- ✅ 可完全禁用（`SmartMoneyConfig.enabled = false`）

## 🐛 修复

### 1. 仓位建议语义清晰化
**问题**：回避动作显示"0%-5%"仓位建议，语义冲突  
**修复**：改为明确的"不建仓"

**修复前**：
```
- 当前机会：回避
- 仓位建议：0%-5%  ❌ 冲突
```

**修复后**：
```
- 当前机会：回避
- 仓位建议：不建仓  ✅ 一致
```

### 2. 汇总显示完整回避列表
**问题**：只显示第一只回避股票  
**修复**：显示所有回避标的

**修复前**：
```
需要回避：腾讯  ❌ 不完整
```

**修复后**：
```
需要回避：腾讯, 小米, PDD, 泡泡玛特  ✅ 完整
```

### 3. 过期信号标签清理
**问题**：理由段落显示过期信号标签  
**修复**：只显示新鲜信号，过期信号仅保留审计

## 📋 验证

- ✅ 447/447 单元测试通过
- ✅ 四类主力信号正常工作
- ✅ 过期信号正确过滤（fresh/stale 分离）
- ✅ 方向判断准确（bearish 共振测试）
- ✅ 报告输出清晰（语义一致性）
- ✅ 审计日志完整（单一 run_id，无错误）

## 🔮 未来功能

**流动性扫荡检测**（⏳ 待集成）：
- 函数已就位（`analyze_sweep_quality`）
- 配置参数已就位（`sweep_recovery_threshold`）
- 测试覆盖完整（3 个单元测试）
- 需要复杂前置条件（流动性池识别、扫荡/恢复 K 线检测）

## 📦 完整更新日志

**v3.4.1** (2026-08-17):
- feat: Smart Money Detection 正式上线
- fix: 回避动作仓位建议改为"不建仓"
- fix: 汇总显示所有回避标的
- fix: 清理过期信号标签残留
- docs: 精简 README，聚焦核心能力

**v3.4.0** (2026-08-16):
- feat: Smart Money 初始集成
- feat: 吸筹/卖压衰竭/买盘衰竭检测
- feat: 多周期供需共振
- feat: 信号时效性过滤

## 🚀 升级指南

### 从 v3.3.x 升级

1. 拉取最新代码：
```bash
git pull origin main
```

2. Smart Money 默认启用，无需额外配置

3. 可选：自定义阈值（`config.json`）：
```json
{
  "smart_money": {
    "enabled": true,
    "volume_anomaly_threshold": 2.0,
    "exhaustion_volume_ratio": 0.8,
    "confluence_weight": 1.2
  }
}
```

4. 运行测试验证：
```bash
python -m unittest discover -v
```

### 禁用 Smart Money

如需禁用（保持纯价格结构分析）：

```json
{
  "smart_money": {
    "enabled": false
  }
}
```

或使用代码：
```python
config = naked_k_config.build_trading_config({
    "smart_money": {"enabled": False}
})
```

## 📚 相关文档

- [Smart Money User Guide](docs/superpowers/smart-money-user-guide.md)
- [Implementation Summary](docs/superpowers/2026-08-17-smart-money-implementation-summary.md)
- [Round 6 Final Report](docs/superpowers/2026-08-17-smart-money-round-6-final-report.md)

## 🙏 致谢

感谢社区反馈和测试支持。

---

**完整代码**: https://github.com/loda13/naked-k-analysis  
**问题反馈**: https://github.com/loda13/naked-k-analysis/issues
