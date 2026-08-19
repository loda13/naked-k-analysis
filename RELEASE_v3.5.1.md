# Release v3.5.1

**发布日期**: 2026-08-19

## 核心修复

### 时区混合比较修复
30天窗口过滤在 `naked_k_price_evidence.py` 和 `naked_k_smart_money.py` 中使用 tz-naive cutoff 与可能 tz-aware 的信号时间戳比较，导致 `TypeError: Cannot compare tz-naive and tz-aware timestamps`。

**修复**: 两边时间戳显式统一转 naive 再比较。

**影响**: 使用 tz-aware DataFrame index 的用户（如手动 `.tz_localize('Asia/Hong_Kong')`）不再抛异常。

---

### 公开函数测试覆盖
`fetch_intraday_bars` 和 `collect_intraday_flow` 无测试覆盖。

**新增**:
- 网络失败时返回 None 不抛异常
- collect 降级到 UNAVAILABLE 快照
- 端到端 mock 验证 status/quality/bar_count

**测试**: 541 pass（507 原有 + 31 intraday + 3 新增）

---

### 过度工程清理
删除无读者字段：
- `provider`: 硬编码常量
- `volume_q1/q2/max`: 仅自身测试读取

保留 `volume_q3`（large_mask 依赖）、`status`（planner 条件判断依赖）、`schema_version`（测试断言）。

**影响**: `to_dict()` 输出更精简，报告格式化 key 保持不变。

---

## 技术改进

**30天窗口时效过滤**（v3.5.0 引入，本版修复时区 bug）:
- 只用近30天信号计算主力概率，避免超老信号（392天前）污染当前判断
- 保留所有历史信号用于显示和3个月统计
- 修复前：腾讯报"抄底 83%"，实际支撑来自 531/497/400 天前
- 修复后：老实报 neutral，或基于近期信号的真实概率

**分钟线聚合替代逐笔**（v3.5.0 引入）:
- 东财逐笔接口（`push2.eastmoney.com`）对本机停止响应
- 改用 Yahoo 1分钟 OHLCV 聚合：VWAP、收阳占比、大量分钟分布、早午盘结构
- 质量标记 `PROXY`（与日线 Volume 同源，不构成独立双证据）
- 实测：331根分钟线/交易日，腾讯收盘 +0.32% vs VWAP

---

## 升级指南

```bash
git pull origin main
python -m unittest discover -q  # 验证 541 测试通过
python naked_k_analysis.py      # 正常跑三只
```

无破坏性变更，现有配置和命令行参数不受影响。

---

## 变更详情

**代码**:
- `naked_k_price_evidence.py`: 时区修复 L652-658
- `naked_k_smart_money.py`: 时区修复 L629-637
- `naked_k_intraday_flow.py`: 删除 provider / volume_q1/q2/max
- `tests/test_naked_k_intraday_flow.py`: +3 公开函数测试

**文档**:
- README.md: 精简至 120 行，核心能力前置，v3.5.1 改进说明

**完整对比**: [v3.5.0...v3.5.1](https://github.com/loda13/naked-k-analysis/compare/v3.5.0...v3.5.1)
