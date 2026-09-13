# P16 Ultra Specification — Observability

## Goal
让任何异常都能从用户/API/job 定位到 competition、provider、fixture、model、dataset、version。

## Telemetry dimensions
API latency/error rate；DB latency/error；provider success/freshness/coverage；scheduler duration/status/retry；prediction success/failure；historical accumulation；model health；data quality；leakage alerts。

## Correlation
所有 request/job/prediction/evaluation run 使用 correlation_id/job_id/run_id。日志必须结构化，错误包含 code、reason、component、retryable。

## SLO
定义 API availability、p95 latency、provider freshness、scheduled job completion、prediction success rate、leakage incident response。SLO 按业务重要度分级。

## Model monitoring
监控 probability distribution、calibration、Brier/log loss、missing evidence、model disagreement、provider dependency。漂移告警不能自动修改模型。

## Data monitoring
检测 row count、duplicate、null、status/score contradiction、future timestamp、late capture、provider conflict。

## Alerting
critical：leakage、历史数据污染、DB loss、prediction provenance missing；warning：provider stale、low coverage、job retry。告警必须能关联 runbook。

## Retention
metrics/logs/traces 与 prediction/evaluation 数据分别定义 retention；不能因为 observability retention 删除研究必需 provenance。
