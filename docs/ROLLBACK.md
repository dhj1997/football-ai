# Rollback 手册（P15）

原则：**应用回滚与数据回滚分开**。禁止为回滚代码而直接删除历史 prediction、历史 odds 或 evaluation run；所有数据修正必须走 versioned migration / reprocessing job（P0-P14 的 provenance 与 point-in-time 保证不可被回滚操作破坏）。

## 1. 应用回滚

1. 服务器保留最近版本包：`/opt/football-ai/backups/app-<STAMP>.tar.gz`（由 `deploy/deploy.sh` 第 3 步自动创建）。
2. 回滚步骤：
   ```bash
   tar -xzf /opt/football-ai/backups/app-<STAMP>.tar.gz -C /opt/football-ai/
   chown -R football-ai:football-ai /opt/football-ai/app
   systemctl restart football-ai-api football-ai-web
   curl -fsS http://127.0.0.1:8000/health
   curl -fsS http://127.0.0.1:8000/api/production/readiness -H "x-admin-key: $ADMIN_KEY"
   ```
3. 回滚后必须确认 `environment contract` 与 `smoke checks` 全部 pass。

## 2. 数据回滚

- 迁移全部为 **additive**（`app/production.py::MIGRATIONS`，记录于 `schema_migrations`）。回滚代码不需要回滚 schema：旧版本代码忽略新增表即可（兼容读取原则）。
- 如需撤销某个 additive migration：新增一个反向 versioned migration，禁止手工 `DROP TABLE` 历史数据表。
- 生产环境禁止手工修改历史预测、历史 odds、evaluation run；任何修正通过 versioned reprocessing job 执行并留下审计记录。

## 3. 备份与恢复

- 备份必须**验证可恢复**才算成功。在应用服务器上执行 `bash deploy/backup-verify.sh backup`：mysqldump（single-transaction）到 `/opt/football-ai/backups/`，恢复到临时库 `football_ai_restore_check`，逐表行数指纹比对（`RESTORE_VERIFIED`），验证后自动删除临时库。数据库凭据从 `/opt/football-ai/app/.env` 读取，不回显。
- 验证成功后脚本写入非敏感标记 `/opt/football-ai/backups/last-verified.json`；`POST /api/admin/production/backup` 只读取并返回该标记，不从 Web 进程执行数据库备份或恢复。
- 已验证记录：2026-09-13，32/32 表行数一致，dump 文件 `/opt/football-ai/backups/db-20260913-190755.sql.gz`（27.7MB）。
- 提示：运行中的系统在 dump 后会继续写入（job_runs/odds_snapshots 等），旧 dump 的指纹比对出现少量落后属正常漂移；严格验证用新 dump 立即比对。
- 恢复测试记录验证时间、备份文件名/SHA-256 和通过比较的冷表数量。

## 4. Migration

- 干跑（不提交）：`POST /api/admin/production/migrations/dry-run`。MySQL 不支持事务化 DDL，返回 `not_supported` 时必须先在 MySQL staging 副本验证。
- 应用：`POST /api/admin/production/migrations/apply`（先备份再执行；`schema_migrations` 记录版本，重复执行幂等跳过）。
- **禁止把破坏性 migration 与应用部署合并在同一次发布中。**

## 5. 环境与密钥

- `local → test → staging → production` 通过 `ENVIRONMENT` 环境变量区分；只有 `test` 允许 SQLite，其他环境必须使用 MySQL。production 的 contract 校验（默认 admin key、demo 数据、显式 DATABASE_URL/CORS）见 `GET /api/production/readiness`。
- Secrets 只经环境变量 / secret manager 注入；仓库不保存真实 secret（`.env` 已在 `.gitignore`）。
