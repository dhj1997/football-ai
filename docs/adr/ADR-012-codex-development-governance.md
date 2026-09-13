# ADR-012 Codex Development Governance

## Status
Accepted

## Decision
Codex 每次任务必须先读取 Master Architecture、Current Baseline、相关 ADR，先 audit 再实施；默认直接处理 main；每个 Phase 必须通过 tests、data quality、leakage audit（适用）和 acceptance。

## Consequence
减少 Brownfield 回归和架构漂移，但要求更严格的任务报告。