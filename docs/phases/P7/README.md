# P7 — Historical Prediction

## Goal
Recent Form 固定最近 15 场；历史预测 backfill；历史累积任务只补缺。

## Hard Rules
`prediction_timestamp < kickoff`；as_of cutoff；GPT/DeepSeek 失败不得 fallback；历史 prediction 保留 provenance。

## Acceptance
idempotency key 为 fixture + model + version + prediction timestamp；历史预测不可被当前数据重写。