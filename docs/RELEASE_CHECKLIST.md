# Release Checklist（P17）

发布前逐项确认；任何一项失败即阻塞发布。

## 1. 质量门禁（CI 自动）
- [ ] backend `pytest -q` 全量通过（含 P0 integrity、P9 quality、P13 grounding、P14 research、P15 production、P16 observability）
- [ ] 泄漏/完整性显式门禁通过（test_p0_integrity、test_p1_evaluation_integrity、test_p9_quality_engine、test_p13_explainability、test_p14_research_engine）
- [ ] migration dry-run 门禁通过
- [ ] frontend `pnpm lint` 与 `pnpm build` 通过

## 2. 数据与模型
- [ ] 无数据泄漏违规（`GET /api/admin/observability` → leakage.live_audit passed）
- [ ] 无未解决的关键质量规则 fail（`/api/data-quality`、provider-health conflicts）
- [ ] 历史评价结果未因非 dataset/model 版本原因发生变化
- [ ] 新模型 artifact 已在 Model Registry 注册并通过晋升门禁（candidate → champion 需四门禁证据）

## 3. 生产部署
- [ ] `GET /api/production/readiness` 返回 ready（环境契约无 violation、smoke pass、migration dry-run validated）
- [ ] 部署前备份已完成且 `POST /api/admin/production/backup` 返回 verified
- [ ] 破坏性操作与本次发布解耦（additive-only）
- [ ] 回滚准备：`docs/ROLLBACK.md` 流程可用，上一版本包存在于 `/opt/football-ai/backups/`

## 4. 治理
- [ ] 本次发布涉及的架构决策已记录为 ADR（docs/adr/）
- [ ] 新增赛事/模型/提供方通过 platform kit 校验（capability、provenance、leakage）
- [ ] 告警 runbook（docs/RUNBOOKS.md）与新增组件同步更新
- [ ] Phase report 已写入 `.planning/<date>-<phase>/PHASE_REPORT.md`（changed files/compatibility/tests/migration/rollback/risks）
