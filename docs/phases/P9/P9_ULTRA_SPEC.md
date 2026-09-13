# P9 Ultra Specification — Provider / Data Quality Platform

## 1. Objective

P9 把 P8 的 Competition Domain 真正落到数据层。核心不是增加更多 API，而是让六类赛事都能通过统一的 Competition + Provider + Canonical Data 进入后续 Feature、Prediction、Evaluation 链路。

目标链：
`Competition Registry → Provider Capability → Raw Response → Canonical Entity → Data Quality → Snapshot → Feature Inputs`

六类赛事：CSL、CFA Cup、EPL、La Liga、UCL、ACL。

## 2. Non-negotiable invariants

1. Provider 不能声明未实现的 capability。
2. Provider 数据必须保留 `source`, `source_record_id`, `fetched_at`, `captured_at`。
3. Canonical 数据不得覆盖原始 provenance。
4. 同一 fixture 不允许静默产生两个不同 canonical identity。
5. 冲突必须记录 conflict，不允许最后写入者覆盖。
6. freshness 与 completeness 分开计算。
7. Provider failure 不等于 model fallback；fallback 只允许发生在数据源层，并且必须留下审计记录。
8. 历史数据必须遵守 point-in-time；当前数据不能回写历史 snapshot。

## 3. Capability model

每个 CompetitionDefinition 至少声明：fixture、standings、stage、team、lineup、injury、odds、historical、prediction、evaluation。

Capability 状态使用 `supported | partial | unavailable | unknown`。`unknown` 禁止作为 `supported` 使用。

## 4. Canonical entities

### Fixture
`fixture_id`, `competition_key`, `season_id`, `stage_id`, `kickoff_at`, `home_team_id`, `away_team_id`, `status`, `score`, `venue_id`, `source_refs`, `captured_at`。

### Team
稳定 canonical team id；保存 provider mappings，不使用队名作为唯一键。

### Stage
league round、group、knockout round、leg、aggregate state 等统一表达。

### OddsSnapshot
`fixture_id`, `market`, `selection`, `decimal_odds`, `bookmaker`, `captured_at`, `source`, `is_locked`。

## 5. Data quality rules

- identity uniqueness
- kickoff validity
- team identity completeness
- score completeness for finished fixtures
- status/score consistency
- stage validity
- duplicate detection
- cross-provider conflict detection
- freshness SLA
- source coverage
- odds timestamp ordering

质量结果统一为 `pass | warn | fail | not_applicable`，禁止用一个总分掩盖具体失败原因。

## 6. Provider reliability

按 provider × competition × capability 计算：success rate、latency、freshness、coverage、conflict rate、schema error rate。

可靠性只用于数据源选择和运维，不得直接修改模型概率。

## 7. Implementation sequence

B1 Registry；B2 Provider interface；B3 canonical normalization；B4 quality engine；B5 freshness/conflict tracking；B6 admin health API；B7 historical snapshot integration；B8 tests。

每一步先加测试，再接入生产 provider。不得一次性替换现有 league pipeline。

## 8. Migration policy

P0-P7 历史表和 prediction provenance 不迁移破坏。新增字段 additive-first；旧 endpoint 保留 compatibility wrapper；删除旧逻辑必须有独立 phase 和 migration note。
