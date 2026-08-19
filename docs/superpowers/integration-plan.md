# Dual-Evidence 集成计划

**日期**: 2026-08-20
**状态**: 待实施

## 已完成模块

### 1. 价格证据层
- ✅ `naked_k_price_evidence.py` (13 tests)
- ✅ 8种证据检测器
- ✅ 生命周期管理

### 2. 成交证据层
- ✅ `naked_k_flow_eastmoney.py` (9 tests)
- ✅ `naked_k_trade_flow_evidence.py` (7 tests)
- ✅ 逐笔成交采集 + 证据生成

### 3. 融合层
- ✅ `naked_k_smart_money_fusion.py` (12 tests)
- ✅ 双证据融合矩阵
- ✅ 时间对齐检查

### 4. 基础设施
- ✅ zone_id/pool_id 追溯
- ✅ 数据契约定义

## 集成步骤

### 步骤 1: 在 analyze_stock() 中调用 dual-evidence

```python
# 1. 生成价格证据
from naked_k_price_evidence import generate_price_evidences

price_evidences = generate_price_evidences(
    daily_df=daily,
    zones=price_zones,
    liquidity_pools=liquidity_pools,
    current_price=current_price,
)

# 2. 获取逐笔成交数据（仅港股）
trade_flow_evidences = []
if ticker.endswith('.HK'):
    from naked_k_flow_eastmoney import fetch_trade_flow
    from naked_k_trade_flow_evidence import generate_trade_flow_evidence
    
    today = pd.Timestamp.now().strftime('%Y-%m-%d')
    snapshot = fetch_trade_flow(ticker, today)
    
    if snapshot.status == "OK":
        trade_flow_evidences = generate_trade_flow_evidence(snapshot)

# 3. 构建层结果
from naked_k_smart_money_fusion import (
    LayerResult,
    fuse_dual_evidence,
    _compute_layer_state,
)

if price_evidences:
    price_state, price_direction = _compute_layer_state(
        price_evidences,
        quality="VALID",
        limitations=(),
    )
    price_layer = LayerResult(
        layer="price_action",
        state=price_state,
        direction=price_direction,
        evidences=tuple(price_evidences),
        quality="VALID",
        limitations=(),
        decision_time=datetime.now(timezone.utc),
        target_session=today,
        valid_from=datetime.now(timezone.utc),
        valid_until=datetime.now(timezone.utc) + timedelta(days=10),
    )
else:
    price_layer = None

if trade_flow_evidences:
    tf_state, tf_direction = _compute_layer_state(
        trade_flow_evidences,
        quality=snapshot.quality if snapshot else "UNAVAILABLE",
        limitations=snapshot.limitations if snapshot else (),
    )
    trade_flow_layer = LayerResult(
        layer="trade_flow",
        state=tf_state,
        direction=tf_direction,
        evidences=tuple(trade_flow_evidences),
        quality=snapshot.quality if snapshot else "UNAVAILABLE",
        limitations=snapshot.limitations if snapshot else (),
        decision_time=datetime.now(timezone.utc),
        target_session=today,
        valid_from=datetime.now(timezone.utc),
        valid_until=datetime.now(timezone.utc) + timedelta(days=3),
    )
else:
    trade_flow_layer = None

# 4. 融合
fusion_result = fuse_dual_evidence(trade_flow_layer, price_layer)
```

### 步骤 2: 添加到 StockReport

```python
@dataclass
class StockReport:
    # ... 现有字段 ...
    
    # 新增双证据字段
    dual_evidence_fusion: DualEvidenceFusion | None = None
    price_evidences: list[PriceEvidence] = field(default_factory=list)
    trade_flow_evidences: list[TradeFlowEvidence] = field(default_factory=list)
```

### 步骤 3: 报告输出格式

在 `format_markdown()` 中添加：

```markdown
## 主力资金双证据分析 (实验性)

### 融合结果
- 结论: {fusion_result.result.value}
- 方向: {fusion_result.direction}
- 置信度: {fusion_result.confidence}
- 解释: {fusion_result.explanation}

### 价格证据层
{显示 price_evidences 列表}

### 成交证据层 (仅港股)
{显示 trade_flow_evidences 列表}

⚠️ 本分析处于实验阶段，未经事件研究验证，仅供参考。
```

## 降级策略

1. **trade_flow 不可用** → 仅使用价格证据层
2. **历史数据不足** → 使用 bootstrap 阈值
3. **时间未对齐** → 标记 PROVISIONAL
4. **网络失败** → 静默降级，不影响主报告

## 验证检查点

- [ ] 港股能正常获取逐笔数据
- [ ] 非港股静默降级到旧 smart_money
- [ ] 报告格式正确
- [ ] 测试覆盖集成点
- [ ] 性能影响可接受（<2秒增量）

## 兼容性

- 保留旧 `analyze_smart_money_signals()` 作为降级路径
- 新系统通过 config 开关控制
- 默认对所有股票启用价格证据层
- 默认仅对港股启用成交证据层

## 下一步

实施集成代码，运行端到端测试。
