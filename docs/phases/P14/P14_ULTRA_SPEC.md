# P14 Ultra Specification — Automated Research

## Goal
把历史数据积累、特征刷新、预测、评估和研究报告串成可审计的 Research Engine。

## Research object
`ResearchRun`: hypothesis, dataset fingerprint, competition scope, time window, feature/model/calibration versions, parameters, seed, run status, result summary, conclusion, created_by/job_id。

## Pipeline
`Hypothesis → Dataset Freeze → Experiment → Backtest → Statistical Check → Leakage Audit → Report → Archive`。
任何步骤失败，run 标记 failed/partial，不生成“成功结论”。

## Scheduler
历史 accumulation、prediction refresh、evaluation、report generation 使用独立 jobs；每个 job 有 idempotency key、lock、retry policy、duration、last error。

## Statistical discipline
研究必须区分 exploratory 与 confirmatory。不得因为多次尝试而只保留最佳结果；报告 experiment count、selection rule、sample size。

## Report
自动报告至少包含 dataset/version、method、metrics、uncertainty、limitations、leakage result、结论与不可回答项。

## Governance
Research Engine 不得绕过 P0-P13 的 provenance、point-in-time、model registry、backtest contracts。
