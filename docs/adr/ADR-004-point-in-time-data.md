# ADR-004 Point-in-Time Data

## Status
Accepted

## Decision
历史预测只读取 prediction_timestamp 时刻可见的数据：`captured_at <= prediction_timestamp < kickoff`。

## Consequence
历史重建复杂度增加，但可避免未来信息泄漏。