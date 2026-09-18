# Football AI v2 Round 3.5 Activation Report

验证日期：2026-09-16  
范围：仅验证现有 Round 3 Feature Engine v2 在真实 MySQL 上的激活闭环。未新增 Feature、公式、预测逻辑、概率模型、训练流程或部署变更。

## 1. Activation Summary

Feature Engine v2 已在配置的真实数据库完成小范围激活，闭环如下：

`Data Sources -> Feature Engine v2 -> Feature Snapshot -> Feature Values -> Leakage Audit -> Feature Explanation API`

结果：

- Feature Registry：62 个定义，全部在激活快照中实际发射。
- Feature Snapshot：4 个，均为 append-only 持久化记录。
- Feature Values：448 条，每个快照 112 条。
- Leakage Audit：4 条，全部 `PASS`。
- 既有数据未受影响：fixtures `3546`，predictions `132`。
- 本轮未启动 Round 4，也未引入任何 ML 或概率引擎。

## 2. Migration Result

| 项目 | 结果 |
|---|---|
| migration | `0006-round3-feature-engine` |
| 执行状态 | `APPLIED` |
| 执行时间 | `2026-09-16T03:39:15Z` |
| migration 记录 | 因数据库原先没有 `schema_migrations`，增量 runner 先登记并应用 `0001` 至 `0006`；重复执行会跳过已应用项 |
| 新建表 | `feature_registry`、`player_impact_rules` |
| `feature_values` 新增列 | `registry_id`、`entity_type`、`entity_id`、`value_type`、`calculation_version`、`source_record_ids`、`quality_score`、`missing_reason` |
| Round 3 索引 | Repository 初始化时按现有 additive 逻辑补齐 registry/value/snapshot/player-rule 查询索引 |
| rollback | `NOT EXECUTED`；MySQL DDL 自动提交，runner 只对 SQLite 提供事务性 dry-run。回滚需先备份，再手工删除 Round 3 索引、8 个列及两张表，属于破坏性操作，本轮不对真实库执行 |

Migration 应用前后既有 `fixtures`、`predictions` 数量保持不变；没有删除或更新 prediction、evidence、revision、audit 历史。

## 3. Data Scope

本轮采用窄范围激活，不做全量计算：

| 项目 | 范围 |
|---|---|
| competition | `LALIGA`（西甲） |
| fixtures | `sportsdb-2506220`、`sportsdb-2506219`、`sportsdb-2506222` |
| teams | 马德里竞技、奥萨苏纳、巴塞罗那、桑坦德竞技、莱万特、毕尔巴鄂竞技 |
| kickoff 范围 | `2026-09-16T17:00:00Z` 至 `2026-09-16T19:30:00Z` |
| prediction cutoff | `2026-09-16T03:41:21Z` 至 `2026-09-16T03:41:22Z` |

其中 `sportsdb-2506220` 计算了两个不同 cutoff，用于验证历史快照不会被覆盖；coverage 只取每个 fixture 的最新 PASS 快照，因此统计样本为 3 场而不是 4 个快照。

## 4. Feature Generation Result

- Registry definitions：`62`。
- Persisted snapshots：`4`。
- Persisted feature values：`448`。
- 每个 snapshot：`112` 行，包含 entity、source、source record IDs、available time、calculation version 和 quality score。
- 最新 PASS 快照的质量分：`0.6011`（2506220）、`0.5754`（2506219）、`0.6021`（2506222）。

Append-only 与 replay 验证：

- 两个 cutoff 的 `sportsdb-2506220` snapshot ID 均保留在数据库，没有 UPDATE 覆盖。
- 相同 fixture、cutoff、feature version、evidence/odds 引用和 feature 输入重复计算，得到相同 snapshot ID 与 feature 内容，并按幂等语义返回原记录。
- 不同 cutoff 会形成新的哈希 snapshot identity；历史值保持可读。

## 5. Coverage Result

Coverage 详表已更新至 [AI_ROUND3_FEATURE_COVERAGE.md](D:\work\football-ai\docs\AI_ROUND3_FEATURE_COVERAGE.md)。按每场最新 PASS 快照的 336 行统计：

| Feature group | Available | Expected | Coverage |
|---|---:|---:|---:|
| attack | 12 | 12 | 100.00% |
| defense | 12 | 12 | 100.00% |
| elo | 12 | 12 | 100.00% |
| fatigue | 30 | 30 | 100.00% |
| form | 144 | 192 | 75.00% |
| home_away | 6 | 30 | 20.00% |
| player | 0 | 6 | 0.00% |
| strength | 6 | 6 | 100.00% |
| xg | 0 | 36 | 0.00% |

行状态：`available=60`、`insufficient_sample=162`、`missing=114`。所有 448 条持久化 feature value 的 `quality_score` 均非空。

## 6. Leakage Validation

验证结果：

- Leakage audits：`4 PASS`，每个 snapshot `features_checked=112`、`features_failed=0`。
- `available_at > prediction_cutoff_at`：`0` 条。
- `quality_score IS NULL`：`0` 条。
- 已完成比赛历史只在 result availability 不晚于 cutoff 时进入 Elo、form、goals、strength、home/away 和 fatigue；xG/xPoints 另外检查自身字段的 available time。
- `future` 或无法验证时间边界的 feature 会被 fail closed，并不能进入 PASS/API production 选择。

因此本次真实样本没有 future leakage 违规；测试还覆盖了 cutoff 边界、未来结果、未来 xG 和可重现性。

## 7. API Validation

调用 `GET /match/sportsdb-2506220/features` 返回 `200`，并读取真实持久化数据：

- `feature_snapshot_id`：`feature:6da8f4f0cb6f1ebd1f4eadb40486db711cea1a4c27dd7cfb839a89455fe2e7c0`
- `prediction_cutoff_at`：`2026-09-16T03:41:22+00:00`
- `feature_version`：`round3-feature-engine-v2`
- `audit_status`：`PASS`
- feature count：`112`
- groups：`form=64`、`fatigue=10`、`home_away=10`、`xg=12`、`attack=4`、`defense=4`、`elo=4`、`player=2`、`strength=2`

验证时未进入 FastAPI lifespan，automation 未启动；SQL 只读拦截器记录到的语句全部为 `SELECT`，读取对象为 `feature_registry`、`feature_snapshots`、`feature_values`、`leakage_audits`。路由没有临时重算或绕过 Registry。

## 8. Known Issues

- 当前数据源没有可用的真实 xG：`source_xg_unavailable=40`，相关 rolling/venue xG coverage 为 0%。
- 当前数据源没有可用的 xPoints：`source_xpoints_unavailable=48`，performance-vs-expectation coverage 为 0%。
- 部分球队没有足够的历史主客场样本：`no_prior_split_matches=20`，home/away coverage 为 20%。
- 当前没有 cutoff-safe player impact rule/evidence：`player_impact_rule_or_evidence_unavailable=6`。
- 本轮只做 3 场窄范围激活，不能把该 coverage 外推到全部联赛或全部 fixture。
- MySQL rollback 不是事务性 dry-run；如需回滚必须走备份后的人工变更流程。

以上缺失均以显式 `missing_reason` 保存，没有用估算值或 LLM 数值填补。

## 9. Round 4 Readiness

数据链路层面已具备进入下一阶段评估的基础：真实数据库、版本化 Registry、append-only snapshot/value、时间边界和审计链均已验证。

但本轮不启动 Round 4。xG、xPoints、player 等 coverage 缺口仍需在后续获授权阶段评估；任何后续概率引擎必须继续遵守 strict no-ML 架构，不得把 LLM 数值或拟合型模型引入生产路径。

## Verification Executed

本轮收尾仅运行与 Round 3 直接相关的 `apps/api/tests/test_round3_feature_engine.py`、Python `compileall` 和 `git diff --check`；未运行无关的大规模测试，未提交、未推送、未部署。
