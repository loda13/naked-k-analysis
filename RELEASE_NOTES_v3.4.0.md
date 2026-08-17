# Release Notes v3.4.0

**发布日期**: 2026-08-17

## 🎉 重大新增功能

### 主力资金行为识别 (Smart Money Detection)

新增 `naked_k_smart_money.py` 模块，识别机构/大资金的建仓、吸筹、洗盘等行为模式。

#### 核心能力

**识别的行为模式**：
- **吸筹信号** - 异常成交量放大但价格窄幅震荡，显示主力在同一价位反复建仓
- **流动性扫荡** - 价格扫过关键区域后快速反转，主力洗盘完成
- **卖压衰竭** - 价格创新低但成交量萎缩、下跌减速，抄底前兆
- **买盘衰竭** - 价格创新高但成交量萎缩、上涨减速，见顶前兆
- **多周期共振** - 日线/周线/月线需求区或供给区三重对齐，主力长期布局区域

**输出示例**：
```markdown
- 交易员简报：
  主力：主力抄底概率 92%。检测到：吸筹信号(developing, 92%)
```

#### 技术特性

- ✅ **纯 OHLCV 分析** - 无外部数据依赖，保持系统"裸K"哲学
- ✅ **确定性可重现** - 所有计算确定性，无黑盒
- ✅ **默认启用** - 无需配置即可使用
- ✅ **可配置** - 支持通过 `config.json` 调整阈值或禁用
- ✅ **零破坏** - 447/447 测试全部通过，向后兼容

#### 配置选项

创建 `config.json`（可选）：

```json
{
  "smart_money": {
    "enabled": true,
    "volume_anomaly_threshold": 2.0,
    "sweep_recovery_threshold": 0.9,
    "exhaustion_volume_ratio": 0.8,
    "confluence_weight": 1.2
  }
}
```

**参数说明**：
- `enabled`: 是否启用主力分析（默认 `true`）
- `volume_anomaly_threshold`: 异常成交量倍数阈值（默认 `2.0`）
- `sweep_recovery_threshold`: 扫荡收回比例阈值（默认 `0.9` = 90%）
- `exhaustion_volume_ratio`: 衰竭成交量比率阈值（默认 `0.8` = 80%）
- `confluence_weight`: 多周期共振权重加成（默认 `1.2`）

#### 使用方式

**默认使用**（无需配置）：
```bash
python naked_k_analysis.py
```

**禁用主力分析**：
```bash
# config.json
{
  "smart_money": {"enabled": false}
}

python naked_k_analysis.py --config-path config.json
```

**调整灵敏度**：
```json
{
  "smart_money": {
    "volume_anomaly_threshold": 3.0,  // 提高门槛，减少信号
    "exhaustion_volume_ratio": 0.6    // 降低门槛，更严格判断衰竭
  }
}
```

#### 实战案例

**腾讯 0700.HK (2026-08-17)**：
- 技术面：下降结构，观望
- 主力信号：**抄底概率 92%**，检测到吸筹信号
- 解读：尽管技术面显示观望，但主力行为显示有大资金在低位建仓，可考虑小仓试错

#### 注意事项

⚠️ **重要提示**：
- 主力分析是**概率优势工具**，不是确定性预测
- 必须配合技术面使用，不能单独作为入场依据
- 建议置信度 >70% 才作为辅助参考
- 主力也会失败，信号仅供参考

**无法识别**：
- 大单逐笔追踪（需 tick 数据）
- 资金流向（需专业数据源）
- 机构持仓变化（需披露数据）

#### 文档

- **用户指南**: `docs/superpowers/smart-money-user-guide.md`
- **设计文档**: `docs/superpowers/specs/2026-08-17-smart-money-detection-design.md`
- **集成报告**: `docs/superpowers/2026-08-17-smart-money-integration-complete.md`
- **交付报告**: `docs/superpowers/PROJECT-DELIVERY-REPORT.md`

---

## 🔧 架构变更

### 新增模块
- `naked_k_smart_money.py` - 主力行为识别核心逻辑（440 行）
- `tests/test_naked_k_smart_money.py` - 完整单元测试（17 个测试）

### 修改模块
- `naked_k_planner.py` - 集成主力分析到交易计划生成流程
- `naked_k_interpreter.py` - 在交易员简报中展示主力信号
- `naked_k_config.py` - 添加 `SmartMoneyConfig` 配置类
- `CLAUDE.md` - 更新架构文档

### 新增文件
- `config.example.json` - 完整配置示例，包含 smart_money 配置段
- 5 个详细文档文件

---

## 📊 测试结果

```
Ran 447 tests in 1.065s
OK ✅

新增测试：
- 吸筹检测：4/4 通过
- 扫荡质量：3/3 通过
- 衰竭检测：3/3 通过
- 多周期共振：3/3 通过
- 综合分析：3/3 通过
- 集成测试：7/7 通过
```

---

## 🚀 性能

- **时间复杂度**: O(n)，n = 数据长度
- **典型耗时**: <10ms（50根K线）
- **内存占用**: 无显著增加
- **网络请求**: 0（纯本地计算）

---

## 📦 依赖

无新增依赖，继续使用：
- `pandas`
- `numpy`
- `yfinance`
- `requests`

---

## 🔄 向后兼容性

✅ **完全向后兼容**
- 现有配置文件无需修改
- 现有代码无需修改
- 主力分析默认启用，不影响现有逻辑
- 所有现有功能正常工作

---

## 📝 升级指南

### 从 v3.3.x 升级

**无需任何操作**，直接更新代码即可：

```bash
git pull origin main
```

主力分析会自动启用并出现在报告中。

### 可选：禁用主力分析

如果不需要主力分析，创建 `config.json`：

```json
{
  "smart_money": {
    "enabled": false
  }
}
```

---

## 🙏 致谢

感谢社区反馈和测试。

---

## 📞 支持

- **文档**: `docs/superpowers/smart-money-user-guide.md`
- **Issue**: https://github.com/loda13/naked-k-analysis/issues
- **项目主页**: https://github.com/loda13/naked-k-analysis

---

**完整变更记录**: https://github.com/loda13/naked-k-analysis/compare/v3.3.1...v3.4.0
