# 主力抄底识别增强设计

**日期**: 2026-08-17  
**状态**: Draft

## 目标

在保持"纯价格+结构"哲学的前提下，增强系统对主力资金（Smart Money）行为的识别能力，特别是抄底和建仓信号。

## 设计原则

1. **只使用OHLCV数据** - 不引入付费数据源或复杂指标
2. **保持确定性核心** - 所有计算可重现，无黑盒
3. **分层可选** - 增强模块独立，不破坏现有逻辑
4. **测试优先** - 每个信号都有对应的单元测试

## 核心识别信号

### 1. 异常成交量模式 (Volume Anomaly)

**原理**: 主力建仓/抄底时成交量会显著放大，但价格涨幅有限（吸筹）或先跌后涨（扫单）

**实现**: `naked_k_smart_money.py` - 新模块

```python
def detect_accumulation_volume(df: pd.DataFrame, window: int = 20) -> dict:
    """
    识别吸筹成交量模式
    
    特征：
    - 成交量 > 均量 2倍以上
    - 收盘价在下影线上半部分（拒绝下跌）
    - 连续2-3根出现在相似价位
    """
    volume_ma = df['Volume'].rolling(window).mean()
    avg_range = (df['High'] - df['Low']).rolling(window).mean()
    
    signals = []
    for i in range(len(df) - 3):
        # 成交量异常
        vol_ratio = df['Volume'].iloc[i] / volume_ma.iloc[i]
        
        # 价格行为：低位+长下影线+收在上半区
        close = df['Close'].iloc[i]
        low = df['Low'].iloc[i]
        high = df['High'].iloc[i]
        body_position = (close - low) / (high - low) if high > low else 0
        
        # 价格区间重叠（同一位置反复吸筹）
        price_cluster = abs(df['Close'].iloc[i:i+3].std() / close) < 0.02
        
        if vol_ratio > 2.0 and body_position > 0.5 and price_cluster:
            signals.append({
                'type': 'accumulation',
                'position': i,
                'volume_ratio': vol_ratio,
                'strength': 'strong' if vol_ratio > 3.0 else 'developing'
            })
    
    return signals
```

### 2. 流动性扫荡后的快速反转 (Liquidity Sweep + Reversal)

**原理**: 主力先击穿支撑触发散户止损，随后快速拉回（spring动作）

**增强现有**: `naked_k_context.py` 中已有 `liquidity_sweep` 识别，增强判断逻辑

```python
def analyze_sweep_quality(
    sweep_candle: dict,
    recovery_candles: list[dict],
    demand_zone: dict
) -> dict:
    """
    评估扫荡后的反转质量
    
    高质量信号：
    - 扫荡K长下影线，收盘价收回90%以上
    - 后续1-2根快速站稳需求区上沿
    - 扫荡K成交量 > 回收K成交量 1.5倍（洗盘完成）
    """
    sweep_low = sweep_candle['Low']
    sweep_close = sweep_candle['Close']
    sweep_volume = sweep_candle['Volume']
    
    # 反转力度
    wick_recovery = (sweep_close - sweep_low) / (sweep_candle['High'] - sweep_low)
    
    # 后续确认
    reclaim_zone = all(c['Close'] > demand_zone['upper'] for c in recovery_candles)
    
    # 成交量对比（洗盘后缩量是健康的）
    avg_recovery_volume = sum(c['Volume'] for c in recovery_candles) / len(recovery_candles)
    volume_contrast = sweep_volume / avg_recovery_volume
    
    quality_score = 0
    if wick_recovery > 0.9:
        quality_score += 40
    if reclaim_zone:
        quality_score += 30
    if volume_contrast > 1.5:
        quality_score += 30
    
    return {
        'quality': 'strong' if quality_score >= 70 else 'developing',
        'confidence_score': quality_score,
        'thesis': '流动性扫荡后快速收回，显示下方买盘强劲',
        'components': {
            'wick_recovery': wick_recovery,
            'reclaim_confirmed': reclaim_zone,
            'volume_contrast': volume_contrast
        }
    }
```

### 3. 区间底部的量价背离 (Volume-Price Divergence)

**原理**: 价格新低但成交量萎缩 = 卖压衰竭，主力可能在低位接货

```python
def detect_selling_exhaustion(df: pd.DataFrame, lookback: int = 10) -> dict:
    """
    识别卖压衰竭信号
    
    特征：
    - 价格创近期新低
    - 成交量持续萎缩（< 近20日均量 80%）
    - 下跌斜率变缓
    """
    recent_low = df['Low'].iloc[-lookback:].min()
    current_low = df['Low'].iloc[-1]
    
    volume_ma20 = df['Volume'].rolling(20).mean().iloc[-1]
    recent_volume = df['Volume'].iloc[-3:].mean()
    
    # 价格新低
    new_low = current_low <= recent_low
    
    # 成交量萎缩
    volume_dried = recent_volume < volume_ma20 * 0.8
    
    # 下跌减速
    slope_recent = (df['Close'].iloc[-3] - df['Close'].iloc[-1]) / 3
    slope_earlier = (df['Close'].iloc[-10] - df['Close'].iloc[-3]) / 7
    deceleration = slope_recent < slope_earlier * 0.5
    
    if new_low and volume_dried and deceleration:
        return {
            'signal': 'selling_exhaustion',
            'strength': 'developing',
            'thesis': '价格新低但量能萎缩，卖压衰竭，底部可能形成',
            'volume_ratio': recent_volume / volume_ma20,
            'slope_change': slope_recent / slope_earlier if slope_earlier != 0 else 0
        }
    
    return {}
```

### 4. 多周期共振确认 (Multi-Timeframe Confluence)

**增强现有**: `naked_k_timeframes.py` 已有多周期分析，增加主力行为的周期共振

```python
def detect_smart_money_confluence(
    monthly_zones: list,
    weekly_zones: list,
    daily_zones: list,
    daily_price: float
) -> dict:
    """
    识别多周期需求区共振
    
    强信号：日线在周线需求区内，且周线在月线需求区内
    """
    daily_in_weekly = any(
        z['lower'] <= daily_price <= z['upper'] 
        for z in weekly_zones 
        if z['kind'] == 'demand'
    )
    
    weekly_in_monthly = any(
        wz['midpoint'] >= mz['lower'] and wz['midpoint'] <= mz['upper']
        for wz in weekly_zones if wz['kind'] == 'demand'
        for mz in monthly_zones if mz['kind'] == 'demand'
    )
    
    if daily_in_weekly and weekly_in_monthly:
        return {
            'signal': 'multi_tf_demand_confluence',
            'strength': 'strong',
            'confidence_score': 85,
            'thesis': '日线、周线、月线需求区三重共振，主力长期建仓区域'
        }
    
    return {}
```

## 集成到现有架构

### 新增模块

```
naked_k_smart_money.py          # 主力行为识别核心
tests/test_naked_k_smart_money.py
```

### 修改模块

1. **naked_k_planner.py**
   ```python
   from naked_k_smart_money import analyze_smart_money_signals
   
   def build_trade_plan(...):
       # 现有逻辑...
       
       # 增加主力行为分析
       smart_money = analyze_smart_money_signals(
           daily_df=daily_df,
           zones=zones,
           liquidity_pools=liquidity_pools,
           market_structure=market_structure
       )
       
       report['smart_money_signals'] = smart_money
   ```

2. **naked_k_setups.py**
   - 在 `classify_trade_setup` 中增加主力信号的权重
   - 当出现高质量主力吸筹信号时，提升 `confidence_score`

3. **naked_k_interpreter.py**
   - 在交易员简报中增加主力行为描述

## 输出示例

```markdown
### 主力行为分析

**吸筹信号**: ✅ 强
- 8月14-15日连续2日放量（均量2.3倍），价格维持在48.50-49.20窄幅震荡
- 收盘均在K线上半部分，显示低位承接强劲

**流动性扫荡**: ✅ 高质量
- 8月16日击穿47.80支撑后快速收回，长下影线占全天波幅92%
- 扫荡K成交量是后续回收K的1.8倍，洗盘充分

**卖压衰竭**: ✅ 确认
- 价格跌至46.50创10日新低，但成交量萎缩至20日均量的65%
- 下跌斜率从前期0.8元/日降至0.3元/日

**多周期共振**: ✅ 三重共振
- 日线价格位于周线需求区（45.20-48.60）内
- 周线需求区位于月线需求区（42.00-50.00）内
- 主力可能在此价位带长期布局

**综合评估**: 主力抄底概率 **78%**
```

## 配置选项

在 `naked_k_config.py` 中新增：

```python
@dataclass(frozen=True)
class SmartMoneyConfig:
    """主力行为识别配置"""
    enable_detection: bool = True
    volume_anomaly_threshold: float = 2.0  # 异常成交量倍数
    sweep_recovery_threshold: float = 0.9  # 扫荡后收回比例
    exhaustion_volume_ratio: float = 0.8   # 衰竭成交量比率
    confluence_weight: float = 1.2         # 多周期共振权重加成
```

## 测试策略

### 单元测试用例

```python
class TestSmartMoneyDetection(unittest.TestCase):
    def test_accumulation_volume_pattern(self):
        """测试吸筹成交量模式识别"""
        df = create_fake_accumulation_pattern()
        signals = detect_accumulation_volume(df)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['type'], 'accumulation')
        self.assertGreater(signals[0]['volume_ratio'], 2.0)
    
    def test_liquidity_sweep_quality(self):
        """测试流动性扫荡质量评估"""
        sweep = {'Low': 47.0, 'Close': 49.0, 'High': 49.5, 'Volume': 1000000}
        recovery = [
            {'Close': 49.2, 'Volume': 500000},
            {'Close': 49.5, 'Volume': 450000}
        ]
        zone = {'upper': 49.0}
        
        result = analyze_sweep_quality(sweep, recovery, zone)
        self.assertEqual(result['quality'], 'strong')
        self.assertGreater(result['confidence_score'], 70)
    
    def test_selling_exhaustion(self):
        """测试卖压衰竭识别"""
        df = create_fake_exhaustion_pattern()
        signal = detect_selling_exhaustion(df)
        self.assertEqual(signal['signal'], 'selling_exhaustion')
        self.assertLess(signal['volume_ratio'], 0.8)
```

### 回测验证

使用 `naked_k_backtest.py` 回测增强后的信号：
- 对比增强前后的胜率变化
- 统计主力信号出现后的5日/10日收益
- 计算假阳性率

## 风险提示

1. **成交量数据质量**: 不同数据源的成交量可能有差异
2. **并非万能**: 主力也会失败，信号只是概率优势
3. **需要结合其他条件**: 不能单独作为入场依据
4. **A股特殊性**: A股主力行为可能与美股/港股不同

## 实施步骤

1. ✅ 完成设计文档（本文档）
2. ⏳ 实现 `naked_k_smart_money.py` 核心函数
3. ⏳ 编写完整的单元测试
4. ⏳ 集成到 `naked_k_planner.py`
5. ⏳ 更新报告输出格式
6. ⏳ 回测验证效果
7. ⏳ 文档更新和示例

## 参考资料

- Wyckoff Method: Accumulation/Distribution schematics
- Smart Money Concepts (SMC): Liquidity sweep, order blocks
- Volume Spread Analysis (VSA): Effort vs Result
