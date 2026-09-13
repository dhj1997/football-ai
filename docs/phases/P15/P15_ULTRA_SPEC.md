# P15 Ultra Specification — Production

## Goal
让 Football AI 从开发环境进入可恢复、可发布、可审计的生产系统。

## Environments
`local → test → staging → production`。配置与 secrets 严格分离；代码不写真实 secret。

## Deployment
容器化 API/Web/worker；database migration 必须 versioned；migration 前备份，失败可 rollback。生产发布采用 smoke test + health check + migration verification。

## CI gates
lint、unit、integration、frontend build、API contract、data quality、leakage audit、migration dry-run、smoke test。

## Backup/restore
数据库备份必须验证可恢复，不以“备份文件存在”作为成功标准。恢复测试记录时间、版本、数据 fingerprint。

## Security
API keys/secrets 使用环境变量或 secret manager；admin endpoints require authentication/authorization；日志禁止输出 token、完整 prompt secret、用户敏感信息。

## Rollback
应用 rollback 与数据 rollback 分开。禁止为了回滚代码而直接删除历史 prediction。数据采用 additive migration 和兼容读取。

## Production invariant
生产环境禁止手工修改历史预测、历史 odds、evaluation run；所有修正走 versioned migration/reprocessing job。
