# Release v3.5.0

**发布日期**: 2026-08-20

## 🎉 主要更新

### 智能资金信号显示改进
显示所有历史信号，让用户看到完整的主力行为轨迹。

**新特性**：
- ✅ **移除"过期"标记** - 显示所有历史信号，不再过滤
- ✅ **信号时间显示** - 显示信号发生时间（如"5天前"、"392天前"）
- ✅ **3个月统计** - 显示近3个月信号次数和日期列表
- ✅ **完整概率计算** - 所有信号参与主力行为概率评估

**输出示例**：
```
主力行为：主力抄底概率 83% (吸筹信号(392天前), 吸筹信号(78天前)) | 近3月2次
```

**价值**：
- 看到主力行为的完整历史轨迹
- 了解主力活跃频率（3个月统计）
- 判断信号的时效性（天数标记）

---

### Dual-Evidence 智能资金架构（实验性）
港股专属的双证据融合系统，结合价格行为和逐笔成交数据。

**新模块**：
1. **价格证据层** (`naked_k_price_evidence.py`)
   - 8种检测器：吸收、扫单回收、买卖衰竭、低量测试等
   - 基于价格区域和流动性池的主力行为识别

2. **成交数据采集** (`naked_k_flow_eastmoney.py`)
   - 港股逐笔成交数据（东方财富）
   - 盘中实时数据获取

3. **成交证据生成** (`naked_k_trade_flow_evidence.py`)
   - 4种证据：大额集中买入/卖出、小单集中买入/卖出
   - 基于逐笔成交的主力意图推断

4. **双证据融合** (`naked_k_smart_money_fusion.py`)
   - 9种融合结果：对齐看涨/看跌、单一证据、冲突、无信号等
   - 智能置信度评估

**架构特点**：
- 🎯 **事件驱动** - 只在明确主力行为出现时输出
- 🔒 **高质量信号** - 严格的证据标准，避免噪音
- 🛡️ **静默降级** - 任何错误不影响主流程
- 📊 **可追溯** - 完整的证据链和推理过程

**当前状态**：
- ✅ 代码完整实现并集成
- ✅ 44个测试全部通过
- ⏳ 生产环境运行中，等待市场特定形态触发

**配置**（`config.json`）：
```json
{
  "smart_money": {
    "enabled": true,
    "mode": "dual_evidence",
    "trade_flow": {
      "enabled": true,
      "provider": "eastmoney_hk"
    }
  }
}
```

---

## 📦 技术改进

### 代码质量
- 完整的类型注解和文档字符串
- 44个单元测试和集成测试
- 模块化设计，易于扩展

### 架构改进
- 证据层与融合层分离
- 统一的证据接口（`Evidence` protocol）
- 可配置的阈值和参数

---

## 📊 完整提交历史

本次发布包含 14 个提交：

```
3a1e6e8 feat(smart-money): show all signals with timestamps and 3-month statistics
5eb8ab5 docs: add final status report for dual-evidence architecture
f0085f6 fix(integration): use correct parameters for build_price_action_layer
ebffee1 fix(integration): use correct function name build_price_action_layer
9123a9c docs: add dual-evidence architecture completion report
8729207 feat(integration): integrate dual-evidence architecture into main analysis flow
3b1f182 docs: add integration plan and work summary for dual-evidence architecture
47d9a12 feat(fusion): implement dual-evidence fusion layer
fc28139 feat(trade-flow): implement evidence generator for tick concentration
d1e0925 feat(trade-flow): implement eastmoney provider for HK stock tick data
8a8c524 fix(smart-money): relax accumulation detector thresholds to restore signals
95d4be0 feat(zones): add stable zone_id and pool_id for traceability
db4ed5b fix(price-evidence): enforce pending_confirmation for last two bars
2b5ab04 refactor: define dual-evidence contracts and config
```

---

## 🔄 向后兼容性

**完全向后兼容** ✅

- 现有配置无需修改
- Dual-evidence 默认启用但静默降级
- 智能资金信号显示自动更新

---

## 📖 文档

新增文档：
- `docs/superpowers/smart-money-dual-evidence-design.md` - 设计规范
- `docs/superpowers/smart-money-dual-evidence-implementation-plan.md` - 实施计划
- `docs/superpowers/dual-evidence-integration-plan.md` - 集成计划
- `docs/superpowers/dual-evidence-work-summary.md` - 工作总结
- `docs/superpowers/dual-evidence-completion-report.md` - 完成报告
- `docs/superpowers/final-status.md` - 最终状态

---

## 🚀 升级指南

### 直接升级
```bash
git pull origin main
```

### 验证
```bash
python naked_k_analysis.py
```

查看报告中的智能资金信号：
- 时间标记（X天前）
- 3个月统计（近3月X次）
- Dual-evidence 分析（港股，如果有触发）

---

## 🎯 下一步计划

- 📊 收集 dual-evidence 首次触发案例
- 📈 历史回测验证信号质量
- 🔧 根据生产反馈调整阈值
- 📖 用户使用指南

---

## 🙏 致谢

感谢所有贡献者和用户的反馈！

---

**完整变更**: [v3.4.1...v3.5.0](https://github.com/loda13/naked-k-analysis/compare/v3.4.1...v3.5.0)
