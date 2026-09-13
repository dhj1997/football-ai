# P15 Phase Report — Production

日期：2026-09-13。分支：`main`。

## Audit 结论

- 已有：pydantic-settings 环境配置（`.env` 已 gitignore，secrets 不入库）、`deploy/deploy.sh`（打包→上传→版本备份→重启→健康检查）、`require_admin` 鉴权、预测/赔率不可变写路径、P4/P10/P13/P14 审计能力。
- 缺失：四环境契约与 production 校验、versioned migration + 干跑、备份可恢复性验证、自动化 smoke、CI 门禁、回滚手册。

## Changed files

- 新增 `apps/api/app/production.py`：
  - `EnvironmentContract`（local/test/staging/production；production 拒绝默认 admin key、demo 数据、缺省 DATABASE_URL/CORS）。
  - `run_migrations`（versioned additive migrations + `schema_migrations` 记录 + 干跑模式；SQLite 干跑在回滚事务内验证 DDL，MySQL 诚实返回 `not_supported`——DDL 无法事务化，需 staging 副本验证）。
  - `sqlite_backup_and_verify`（backup API 备份 → 恢复到临时副本 → 行数指纹比对；"备份文件存在"不算成功）。
  - `run_smoke_checks`（数据库连通/查询、competition registry、reader 可用性、环境契约；异常不外溢）。
- `apps/api/app/config.py`：新增 `environment` 字段（默认 local）。
- `apps/api/app/main.py`：`GET /api/production/readiness`（部署门禁）、`POST /api/admin/production/migrations/dry-run|apply`、`POST /api/admin/production/backup`、`POST /api/admin/production/smoke`（全部 admin 鉴权）。
- 新增 `.github/workflows/ci.yml`（backend pytest 全量 + 泄漏/完整性显式门禁 + migration 干跑门禁；frontend lint + build）。
- 新增 `docs/ROLLBACK.md`（应用回滚与数据回滚分离、additive migration 原则、备份验证、secrets 管理）。
- 测试：`tests/test_p15_production.py`、`tests/test_p15_api.py`（10 个用例）。

## Compatibility

- `deploy/deploy.sh` 未改动；health check 之外新增 readiness 深度检查。
- 迁移内容与 `initialize()` 的既有建表一致（IF NOT EXISTS 幂等）；无破坏性变更。

## Tests

- 全量 `pytest -q`：439 passed（429 + 10）。
- 覆盖：四环境契约与 production 违规项、干跑不落版本记录、apply 幂等且 recorded、备份恢复指纹一致 + 缺文件 unavailable、smoke 正常/production 违规均不崩溃、API 401/200 契约。

## Security / Integrity

- Secrets 不入库（`.env` gitignore 已验证）；代码无真实密钥。
- production contract 拒绝默认 admin key 与 demo 数据；admin 端点全部鉴权。
- 历史预测/odds/evaluation run 无任何手工修改路径暴露；迁移全部 additive。

## Migration / Rollback

- `schema_migrations` 表新增（additive）；回滚见 `docs/ROLLBACK.md`，revert 本 commit 即可。

## Risks / 已知限制

- 自动备份验证当前仅支持 SQLite（本项目实际部署形态）；MySQL 备份/干跑需 staging 副本，已显式 `not_supported`。
- CI 的 frontend build 依赖 pnpm registry 可达（同 deploy.sh 的 npmmirror 约束，CI 内走官方源）。
