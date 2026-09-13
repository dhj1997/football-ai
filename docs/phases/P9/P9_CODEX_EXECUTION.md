# P9 Codex Execution Contract

直接在 `main` 工作。禁止创建 feature branch。

## Execution order

1. 读取 P0-P8 文档和现有实现。
2. 建立 capability tests。
3. 完善 Competition Registry。
4. 抽象 Provider interface 与 adapter。
5. 建立 canonical normalization。
6. 接入 quality/freshness/conflict engine。
7. 改造 sync service，使其按 competition capability 工作。
8. 增加 admin data-source health API/UI。
9. 验证历史 snapshot 不被污染。

## Required behavior

- 不支持 standings 的赛事不能调用 standings provider。
- knockout 赛事必须使用 stage/round 语义。
- provider 缺失数据必须返回 readiness 状态，不得伪造。
- provider 层允许 data-source fallback，但必须记录 primary/secondary source 与原因。
- GPT/DeepSeek prediction failure 不得因为 P9 被改成模型 fallback。

## Required tests

unit：normalization、identity、capability、quality rules。
integration：每个六赛事至少 fixture；有 standings 的赛事验证 standings；杯赛验证 stage。
historical：as-of snapshot、capture time、duplicate/conflict。
API：fixture/competition/provider-health contracts。

## Definition of Done

- 六赛事通过 canonical fixture contract。
- unsupported capability 返回明确状态。
- freshness/completeness/conflict 可查询。
- P0-P8 tests 不回归。
- no fabricated data。
- main 工作区 clean。
