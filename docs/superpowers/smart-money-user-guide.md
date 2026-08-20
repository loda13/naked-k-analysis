# OHLCV 量价代理证据使用指南

## 使用

量价代理证据默认参与技术报告，但每次运行仍需显式提供 ticker：

```bash
python naked_k_analysis.py 0700.HK
python naked_k_analysis.py 0700.HK --config-path config.example.json
```

报告中的 `smart_money_signals` 来自 OHLCV 规则，例如放量窄幅、买卖衰竭和多周期价格区域。它们只能描述价格与成交量行为，不能识别机构、受益所有人或“主力”身份，也不是经过校准的概率。

## 解读边界

- `signals`：保留检测到的规则信号；每条信号的 `stale` 标记表示是否超过当前方向判断的时效窗口。
- `signal_count_3m` / `signal_dates_3m`：近三个月的规则命中记录，不是交易绩效。
- `overall_assessment` / `direction`：只由仍在时效窗口内的规则信号决定。
- 单条信号中的 `confidence` 是未校准的规则强度，不是胜率或概率。
- 缺失的逐笔、持仓或资金流数据表示不可用，不等于零。
- 量价证据不得单独改变触发、止损、仓位或组合暴露。

## 配置

当前 main 对用户稳定承诺的开关只有 `enabled`。禁用：

```json
{
  "smart_money": {
    "enabled": false
  }
}
```

`price_action`、`trade_flow` 和 `short_selling` 阈值属于仍在实验的 dual-evidence 工作；当前 main 的旧 OHLCV 汇总路径不会完整应用这些嵌套阈值，也不应被描述成已获得独立机构资金证据。配置结构见 `config.example.json`，但不要把实验字段写成稳定生效的用户接口。

## 输出检查顺序

1. 先看 `action` 与 `risk_plan.status`。
2. 再看 `suggested_gross_pct` 与 `effective_account_risk_pct`。
3. 最后把量价代理作为辅助解释。

`flat`、零 gross 或尚未触发的计划不是当前持仓；条件计划应表述为“突破后才执行”。
