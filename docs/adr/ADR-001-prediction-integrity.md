# ADR-001 Prediction Integrity

## Status
Accepted

## Decision
Prediction、Market Decision、Execution 三层分离。赔率、资金、执行结果不能反向修改预测事实。

## Consequence
系统更可测试、可回测、可审计；需要保持三个 domain contract。