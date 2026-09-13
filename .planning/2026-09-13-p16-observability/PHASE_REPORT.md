# P16 Phase Report — Observability

日期：2026-09-13。分支：`main`。

## Audit 结论

- 已有遥测：`data_sync_runs`（P9 provider reliability 聚合）、`job_runs`（automation）、P9 质量引擎、P14 leakage audit、P15 readiness/smoke。
- 缺失：请求/任务关联 ID、结构化日志（含脱敏）、有界请求指标、SLO 目录、告警规则（critical/warning + runbook）、观测聚合 API。

## Changed files

- 新增 `apps/api/app/observability.py`：
  - `new_correlation_id`（req/job/run 前缀化）+ HTTP 中间件：每个请求注入/透传 `X-Correlation-ID`，记录有界延迟/错误指标与结构化日志。
  - `redact`/`_scrub_text`：递归按键脱敏（api_key/token/password/authorization/prompt/messages 等）+ 正则清洗文本内嵌 `KEY=value` 型密钥；结构化日志事件含 code/reason/component/retryable。
  - `MetricsRegistry`：500 条环形缓冲（p95 延迟、error rate），开销有界。
  - `SLO_CATALOG`（tier1/tier2 六项，含目标/责任组件/runbook 锚点）+ `ALERT_RULES`（4 critical：leakage/数据污染/DB 不可用/provenance 缺失；3 warning：provider 过期/低覆盖/job 重试）。
  - `observe_system_state`：从持久化遥测聚合 jobs/providers/models/data_quality/leakage（有界读取，只读不落库）；`evaluate_alerts` 输出触发的告警与证据。
- `apps/api/app/main.py`：correlation 中间件、`GET /api/admin/observability`。
- 新增 `docs/RUNBOOKS.md`（每条告警的 runbook；SLO 分级）。
- 测试：`tests/test_p16_observability.py`、`tests/test_p16_api.py`（12 个用例）。

## Compatibility

- 中间件仅追加 header/日志/指标，不改变任何端点行为；指标不进入业务决策（仅 admin 端点暴露）。

## Tests

- 全量 `pytest -q`：451 passed（439 + 12）。
- 覆盖：按键与文本内嵌密钥双路脱敏（含日志行内容断言无 secret）、correlation id 前缀/唯一/透传、指标环有界（1000 次请求窗口仍为 100）、provider×competition 新鲜度可观测、模型维度结算计数、泄漏违规触发 critical 告警且带 runbook、警告类告警（stale/低覆盖/job 失败）、SLO 分级与 runbook 完整性、观测端点响应不含 admin key。

## Integrity / Safety

- 漂移/告警不自动修改模型（evaluate_alerts 纯函数，只读）。
- 观测读取全部有界（job_runs≤100、sync_runs≤300、conflicts≤100、research_runs≤20），不影响研究 provenance 保留。

## Migration / Rollback

- 无 schema 变更；回滚 revert 本 commit。

## Risks / 已知限制

- 指标为进程内存态（单实例语义），多副本部署需外接 metrics backend（留待需要时接入，不提前抽象）。
- 日志输出到应用 logger（stdout）；集中采集由部署环境（systemd/journald）承接。
