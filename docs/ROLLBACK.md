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

- 备份必须**验证可恢复**才算成功：`POST /api/admin/production/backup` 执行 SQLite backup API 备份 + 恢复到临时副本 + 行数指纹比对，返回 `status: verified`。
- 恢复测试记录时间、耗时、表行数指纹（`source_fingerprint` / `restore_fingerprint`）。
- MySQL 部署时备份验证使用 staging 副本（迁移干跑同理，见下）。

## 4. Migration

- 干跑（不提交）：`POST /api/admin/production/migrations/dry-run`（SQLite 上在回滚事务内验证 DDL；MySQL 不支持事务化 DDL，干跑返回 `not_supported`，需在 staging 副本验证）。
- 应用：`POST /api/admin/production/migrations/apply`（先备份再执行；`schema_migrations` 记录版本，重复执行幂等跳过）。
- **禁止把破坏性 migration 与应用部署合并在同一次发布中。**

## 5. 环境与密钥

- `local → test → staging → production` 通过 `ENVIRONMENT` 环境变量区分；production 的 contract 校验（默认 admin key、demo 数据、显式 DATABASE_URL/CORS）见 `GET /api/production/readiness`。
- Secrets 只经环境变量 / secret manager 注入；仓库不保存真实 secret（`.env` 已在 `.gitignore`）。
