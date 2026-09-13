# P4 — Historical Validation

## Goal
保证 as_of reconstruction、captured_at cutoff、odds timeline 与 backtest 正确。

## Hard Rules
`captured_at <= as_of`；预测时间必须早于 kickoff；赔率使用时间锁定 snapshot。

## Acceptance
历史快照可重建、无未来数据、回测结果可复现。