# Football AI v2 Round 2 Report

日期：2026-09-15

## 范围

本轮只实现 P0 Data Integrity、逐特征 Feature Snapshot、Future Data Leakage 检测、Prediction Revision History、Prediction Freeze、Retention 保护和可重现性引用链。没有引入 XGBoost、Transformer、新的 ML 模型、LLM 重构、UI 大改或 Live Prediction，也没有建立平行数据系统。

## 1. 修改了哪些文件

### 持久化、迁移和审计

- `apps/api/app/database.py`：在现有 `PredictionRepository` 中增加 feature snapshot/value、prediction revision、leakage audit 的表、索引、读写、原子写入、不可变校验、retention 保护和 reproduce bundle。
- `apps/api/app/production.py`：增加 `0005-round2-data-integrity` additive migration，并保留 dry-run/apply/idempotency 记录机制。
- `apps/api/app/leakage_audit.py`：新增统一 `LeakageAuditService`，支持 feature snapshot 和 prediction 级审计。
- `apps/api/app/main.py`：保留现有管理入口，修正文案以反映 retention 现在是非破坏性的。

### 特征和预测链

- `apps/api/app/prediction_intelligence.py`：逐特征字段、确定性 snapshot ID、cutoff-safe model input、数据源可用时间和 leakage manifest。
- `apps/api/app/recent_form.py`：结果可用时间、last 3/5/8/10、season average 和 cutoff/season 过滤。
- `apps/api/app/team_stats.py`、`apps/api/app/elo.py`、`apps/api/app/clubeelo_provider.py`：按 prediction cutoff 读取并区分缓存边界。
- `apps/api/app/prediction_service.py`：feature snapshot 持久化、模型前 leakage gate、原子 prediction+revision 写入和 kickoff freeze。
- `apps/api/app/prediction.py`、`apps/api/app/dual_prediction_service.py`：沿用现有模型/组合层，保持 Round 2 审计引用，不覆盖赛前预测。
- `apps/api/app/historical_backfill.py`、`apps/api/app/historical_multimodel.py`、`apps/api/app/model_fitting.py`：历史回放写入隔离、模型版本/特征版本引用保持完整。

### 测试和规划

- `apps/api/tests/test_round2_repository.py`：新增 schema、逐特征边界、append-only、原子门禁、retention、freeze/live、reproduce、leakage 和伪造 PASS 回归测试。
- 更新相关 API、PredictionService、RecentForm、历史、多模型、retention、生产迁移和 intelligence 测试。
- `.planning/2026-09-15-football-ai-v2-round2/`：保存本轮计划、发现和验证进度。

## 2. 数据库是否发生变化

发生了 additive schema 变化，仍在现有 repository/database 内：

- `feature_snapshots`：snapshot 级身份、fixture、cutoff、feature version、leakage 状态。
- `feature_values`：每个 feature 的 `feature_name`、`feature_value`、`source`、`source_record_id`、`computed_at`、`available_at`、`prediction_cutoff_at`、`feature_version`、`snapshot_id`。
- `prediction_revisions`：append-only revision 及概率、预期进球、不确定性、数据质量、模型一致性和所有快照引用。
- `leakage_audits`：PASS/FAIL/WARN 结果、违规项和计数。

`PredictionRepository.initialize()` 使用幂等 DDL；没有删除或覆盖旧 prediction/evidence 数据。Feature snapshot 是内容寻址的，同一个 cutoff 的不同模型可以共享；revision 和 audit 负责建立具体预测的关联。

## 3. migration 如何执行

版本迁移为 `0005-round2-data-integrity`。生产流程使用现有 `run_migrations(repository, dry_run=...)`：

```python
run_migrations(repository, dry_run=True)   # SQLite pre-flight，事务回滚
run_migrations(repository, dry_run=False)  # 应用并写入 schema_migrations
```

第二次 apply 会跳过已经记录的 migration。SQLite 的 dry-run 测试、apply 幂等测试和从 P0-P17 旧库升级测试均通过。MySQL DDL 可能自动提交，因此代码对非 SQLite dry-run 返回 `not_supported`；生产应先在 staging 数据库副本执行验证，再 apply 正式库。迁移只增加表，不承担半成品 schema 的破坏性修复。

## 4. 如何证明没有 future leakage

1. 每个非空 feature value 必须带 `available_at`，并与 snapshot 的 `prediction_cutoff_at` 一起进入 `LeakageAuditService`。
2. `available_at <= prediction_cutoff_at` 才能成为 `available`；缺失、非法、未来时间或 `future/unverifiable` 状态都会形成 violation。
3. snapshot 会先持久化，审计失败后不会进入 production prediction。标准 prediction 写入必须在同一事务中引用真实 feature/evidence snapshot，并有对应 PASS audit。
4. revision admission 会再次运行 canonical leakage audit，而不是信任调用方写入的 PASS 行；因此伪造 PASS 不能绕过未来特征检查，失败事务会回滚。
5. rolling 3/5/8/10 和 season average 只从 cutoff 之前可用的已完成比赛计算。结果优先使用 `result_captured_at`/`completed_at`；date-only 结果在次日才可用，并记录 `availability_basis`。没有 provider 完成时间的旧数据使用保守的 kickoff+3h 推断，真实 provider 完成时间补齐留给 Round 3。
6. 已覆盖 `test_feature_available_at_boundary`、`test_future_feature_is_rejected`、`test_rolling_features_do_not_use_future_matches` 以及伪造 PASS 回归；全量 API 测试为 `540 passed`。

统一服务返回结构包括 `status`、`prediction_cutoff_at`、`violations`、`features_checked`、`features_passed`、`features_failed`，并以 `audit_prediction(prediction_id)` 复核完整链。

## 5. retention 为什么不会删除 prediction history

`prune_prediction_history()` 现在只生成 retention plan/summary，返回受保护的 prediction、revision、evidence、feature snapshot、leakage audit 和结算链计数，不再删除 superseded prediction 或其审计引用。`prediction_retention_preview` 与 run endpoint 的文案也已改为非破坏性策略。

因此 T-24h、T-12h、T-6h、T-1h、T-30m、Confirmed XI 等 revision 都以 append-only 行保留。旧 P0-P17 的 legacy bare prediction 仍可读取，但没有被伪造补成 Round 2 revision；新 production prediction 必须走完整链。

## 6. prediction 如何 reproduce

使用：

```python
repository.reproduce_prediction(prediction_id, revision_number)
```

返回并校验 `match_id`、`prediction_id`、revision、`model_version`、`feature_version`、`feature_snapshot_id`、`evidence_snapshot_id`，并解析 immutable feature/evidence payload、可用的 model registry artifact 和模型输入特征。prediction、revision、feature snapshot、evidence snapshot 的 fixture/cutoff/version/ID 不一致会返回 `FAIL`。

revision 编号按 `competition_id + fixture_id + model_key` 分配，prediction revision 本身保持 append-only；当前生产写入为每次 revision 生成新的 prediction ID，避免 current prediction 行覆盖历史内容。

如果模型 artifact 已登记，bundle 会返回对应 registry 记录；未登记时会明确返回 `artifact_status=not_registered`，这意味着本轮保证的是输入、版本和证据可解释/可定位，不声称已经重新执行模型得到数值相同结果。缺少 Round 2 snapshot/evidence 的 legacy prediction 会明确返回缺失引用而不是伪造 PASS。

## 7. 留给 Round 3 的问题

- 为所有 provider 补齐真实、统一时区的 `available_at`/完成时间，逐步减少 kickoff+3h 推断。
- 对 migration 半成品表做 schema fingerprint/列索引校验和可恢复修复流程。
- 为 Elo、Poisson、Dixon-Coles 等透明统计引擎建立公式版本、状态和显式配置 bundle hash，并支持 deterministic replay；同时完善旧 revision 选择和跨时区 timestamp canonicalization。
- 基于现有 `feature_snapshots`/`feature_values` 扩展 Feature Engine 和 Feature Registry，不建立平行 Feature Store；完善 point-in-time Temporal Backtest，但不建立 OOF、训练集或参数搜索流程。
- 保留 Calibration Framework、Calibration Evaluation、Calibration Version Protocol、Probability Audit 和 Historical Reliability Analysis；校准仅允许显式公式、可解释、可版本化、可回测的确定性规则。Platt Scaling、Isotonic Calibration、temperature fitting 及其他历史样本拟合型校准暂停，且不属于当前 v2 no-ML 范围。
- XGBoost、LightGBM、Random Forest、Transformer/LSTM/GNN、Stacking/Meta Model、SHAP/Optuna、learned/adaptive weights 及任何需要训练参数的 ML 组件永久退出 Football AI v2 路线。后续以“统计模型 + 规则系统 + 市场信息 + LLM 解释”为唯一架构边界；Live Prediction、LLM 重构和 UI 改造不属于 Round 3。
- Round 3 必须关闭 legacy learned/calibration 路径已有的 v2 production 选择与执行入口，并增加 fail-closed deny gate；旧 artifact 只允许作为历史 revision 的只读审计引用。该 gate 同时拒绝 LLM 生成的概率、权重、期望进球和仓位进入 v2 production，但保留经过 evidence 审计的结构化证据与只读解释。Market Prior 在每个 revision 中只允许融合一次。

## 验证记录

- `pytest tests -q -p no:cacheprovider`：`540 passed, 5 warnings`。
- `pytest tests/test_round2_repository.py`：`26 passed`。
- `pytest tests/test_p15_production.py -k migration`：`3 passed`。
- `compileall -q app`：通过。
- `git diff --check`：最终收尾阶段执行。

本轮未提交、未推送、未部署。
