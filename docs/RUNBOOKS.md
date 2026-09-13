# Incident Runbooks（P16）

每个告警规则对应一个 runbook 条目：症状 → 诊断 → 处置 → 升级。所有告警的 `component` 字段指明责任组件，`alert_id` 与 `app/observability.py::ALERT_RULES` 一一对应。

## critical

### Leakage incident response {#leakage-incident-response}
- **症状**：`alert-leakage` 触发（leakage audit 报告违规，`prediction_created_at >= settled_at`）。
- **诊断**：`GET /api/admin/observability` 查看 `leakage.live_audit`；定位违规 `prediction_id` 列表。
- **处置**：按 `DATA_LEAKAGE_POLICY` 冻结受影响 prediction/evaluation，保留证据，标记受影响数据集版本；修正数据后通过 versioned reprocessing job 重新评价；在 P14 Research Engine 生成 confirmatory run 验证。
- **升级**：数据负责人；24 小时内完成冻结与审计（SLO slo-leakage-response）。

### Fixture conflicts {#fixture-conflicts}
- **症状**：`alert-data-pollution`（open fixture conflicts > 20）。
- **诊断**：`GET /api/admin/provider-health` 查看 `conflicts`（source_a/source_b/value）。
- **处置**：按 `resolution: configured_source_priority_then_manual_review` 人工复核；修正 provider 配置或别名词典；已解决冲突置 `resolved`。

### Database unavailable {#database-unavailable}
- **症状**：`alert-db-loss`（smoke checks 数据库检查失败）。
- **诊断**：`GET /api/production/readiness`；确认连接串/凭据/网络。
- **处置**：按 `docs/ROLLBACK.md` 第 3 节恢复最近 verified 备份；恢复后必须重跑 `POST /api/admin/production/smoke`。

### Provenance missing {#provenance-missing}
- **症状**：`alert-provenance-missing`（预测缺 evidence snapshot 引用）。
- **诊断**：`GET /api/admin/fixtures/{id}/predictions` 检查 `evidence_snapshot_id`。
- **处置**：重跑该 fixture 的 evidence 同步 job；禁止用当前数据补造历史 provenance。

## warning

### Provider freshness {#provider-freshness}
- **症状**：`alert-provider-stale`（provider×competition 超过 24h 未更新）。
- **诊断**：`GET /api/admin/provider-health` 查看 `freshness`、`error_category`。
- **处置**：手动触发对应 sync job；检查 provider key/额度；连续失败时降级该 provider 优先级（data_sync_runs 留痕）。

### Provider coverage {#provider-coverage}
- **症状**：`alert-provider-low-coverage`（records_rejected > 50%）。
- **诊断**：`data_sync_runs.errors` 的拒绝原因分布。
- **处置**：修复 schema/映射问题；必要时在 P9 registry 调整 capability 声明（必须如实反映能力）。

### Scheduled job completion {#scheduled-job-completion}
- **症状**：`alert-job-retry`（job 近期失败）。
- **诊断**：`GET /api/admin/observability` 的 `jobs` 段（failed、last_error、avg_duration_ms）。
- **处置**：按 `last_error` 修复后 `POST /api/admin/jobs/{job_name}/run` 手动重跑；AutomationRunner 自带失败退避，不手工清 job_runs 历史。

## SLO 参考

SLO 目录与阈值见 `GET /api/admin/observability` 的 `slo_catalog`（tier1：API 可用性/p95 延迟/provider freshness/泄漏响应；tier2：job 完成/预测成功率）。指标只用于观测，不参与业务决策。
