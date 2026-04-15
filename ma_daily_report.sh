#!/bin/bash
# 每日早报: 双均线 + 裸K
# 跑7只股票

MA_SCRIPT="/root/.openclaw/workspace/scripts/ma_analysis.py"
NK_SCRIPT="/root/.openclaw/workspace/scripts/naked_k_analysis.py"
TICKERS="0700.HK 1810.HK NVDA TSLA QQQ 9992.HK PDD"
TF="4h,daily,weekly"
PYTHON="/usr/bin/python3"

echo "===== 📊 Part 1: 双均线分析 ====="
echo "MA20/60/120 + EMA20/60/120 | 4h+日线+周线"
echo "生成时间: $(TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M')"
echo ""

for t in $TICKERS; do
    $PYTHON "$MA_SCRIPT" "$t" "$TF" 2>/dev/null
    sleep 2
done

echo ""
echo "===== 🔮 Part 2: 裸K分析 ====="
echo ""

$PYTHON "$NK_SCRIPT" 2>/dev/null

echo ""
echo "===== 早报结束 ====="
