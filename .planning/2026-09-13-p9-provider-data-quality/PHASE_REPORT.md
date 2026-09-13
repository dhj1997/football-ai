# P9 Phase Report — Provider / Data Quality Platform

日期：2026-09-13。分支：`main`（直接开发，无 feature branch）。

## Audit 结论

- 后端无 Competition Registry；联赛身份存在三套词汇（browse 小写键、P5 大写 CSL/EPL/LAL、各 provider 硬编码映射）。
- P4 `assess_data_quality` 仅覆盖历史路径；`data_sync_runs` 遥测已落库但无聚合查询。
- identity map 已有 conflict 标志但仅用于 P5 历史链路；live 合并路径（dongqiudi/schedule）冲突静默解决。
- 无 stage/knockout 语义，无 `/api/competitions`，无 provider health 聚合 API。

## Changed files

- 新增 `apps/api/app/competition_registry.py`：六赛事 CompetitionDefinition + capability matrix（supported/partial/unavailable/unknown）+ `require` 门禁 + `normalize_competition_key` 统一三套词汇 + season policy。
- 新增 `apps/api/app/data_quality_engine.py`：canonical stage/fixture 规范化（P9 canonical fixture contract）、11 条质量规则（pass/warn/fail/not_applicable，freshness 与 completeness 分列）、`record_fixture_conflicts`、`provider_reliability` 聚合。
- `apps/api/app/database.py`：新增 `competition_registry`、`fixture_conflicts` 表（additive）+ 读写方法。
- `apps/api/app/historical_validation.py`：`canonical_league_id` 补 `LAL`→`laliga` 别名（additive，使 P5 码与 browse 码收敛同一 canonical 身份）。
- `apps/api/app/league_sync.py`：standings 同步按 registry capability 门禁；`sync_competition` 对 unsupported capability 返回 `unsupported_capability` 且不调用 provider。
- `apps/api/app/dongqiudi_sync.py`：赛程合并与比分更新路径接入 `record_fixture_conflicts`。
- `apps/api/app/main.py`：启动时持久化 competition registry；新增 `GET /api/competitions`、`GET /api/admin/provider-health`。
- 新增测试 `tests/test_p9_competition_registry.py`、`test_p9_canonical.py`、`test_p9_quality_engine.py`、`test_p9_api.py`（36 个用例）。

## Compatibility

- 未修改任何既有 endpoint 的请求/响应契约；`/api/competitions`、`/api/admin/provider-health` 为纯新增。
- `LeagueSyncService` 构造函数新增可选 `registry` 参数，默认行为与原逻辑一致（三个 standings-capable 联赛）。
- `dongqiudi_sync` 合并语义不变，仅新增冲突留痕。
- P5 `SUPPORTED_LEAGUES` 与大写码、`P5ProviderRegistry` 原样保留（Protected Baseline）。

## Tests

- 全量 `pytest -q`：352 passed（316 既有 + 36 新增），无回归。
- 覆盖：capability matrix 诚实性、门禁异常、三套词汇归一、六赛事 canonical fixture（含杯赛/洲际 stage 语义）、跨 provider canonical 身份一致性、缺身份返回 None 不虚构、冲突记录幂等与确定性、11 条质量规则各状态、freshness/completeness 分列、reliability 聚合、as-of snapshot 排除未来赔率、API 契约与 admin 鉴权。

## Data integrity / Leakage

- canonical 身份为确定性哈希；缺失身份字段返回 None，不虚构。
- 冲突记录保留 source_a/source_b/value_a/value_b + `configured_source_priority_then_manual_review`，不静默最后写入覆盖。
- 质量规则 `odds_timestamp_ordering` 与 `filter_as_of`/`build_historical_snapshot` 组合验证：未来赔率不进入历史快照。
- provider reliability 仅为运维遥测，不进入模型概率路径。
- GPT/DeepSeek 预测失败语义未被触碰（本 phase 未改任何预测链路代码）。

## Migration / Rollback

- 两张新表由 `initialize()` 自动 `CREATE TABLE IF NOT EXISTS`，无需数据迁移；P0-P7 历史表与 prediction provenance 未做任何迁移。
- 回滚：revert 本 commit 即可；新表残留无害。

## Risks / 已知限制

- `cfa_cup`/`ucl`/`acl` 当前为 fixture-only（standings/historical/prediction 声明为 unavailable），与真实 provider 能力一致；后续 phase 补齐时只需更新 registry 声明。
- reliability 聚合基于最近最多 300 条 `data_sync_runs`（reader 上限）。
- `data_quality_engine` 的质量评估为按需计算（读时评估），未持久化逐场质量结果；如数据量增长可再加持久化。
- Frontend 未改动；P8 UI 契约无变化，web build/lint 不受影响。
