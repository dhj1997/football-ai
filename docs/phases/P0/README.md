# P0 — Prediction Integrity

## Goal
分离 Prediction、Market Decision、Execution，确保模型预测不被资金/下注逻辑反向污染。

## Acceptance
- prediction 与 market decision 独立
- 赔率/资金变化不改变预测事实
- 现有 P0 测试全部通过
- provenance 保留

## Codex
先审计现有 prediction.py、prediction_service.py、market_decision.py、dual_prediction_service.py、bankroll.py、settlement.py，再做最小修改。