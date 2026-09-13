# P6 — Model Evaluation

## Goal
60/20/20 chronological split；train-only weights；validation-only calibration；CSL/EPL/LAL + GLOBAL。

## Metrics
Brier、Log Loss、RPS、ECE、CLV、Hit Rate；betting metrics 只有执行链完整时计算。

## Acceptance
dataset fingerprint frozen；leakage audit 通过；样本不足不制造指标。