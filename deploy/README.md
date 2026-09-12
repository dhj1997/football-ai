# 部署说明

本机安装阿里云 Workbench CLI 后（`~/.workbench/config.json` 已配置凭据），在仓库根目录执行：

```bash
bash deploy/deploy.sh
```

流程：本地打包（排除 .venv / node_modules / .next / .env / 数据库）→ 上传服务器 `/tmp` → 备份当前版本到 `/opt/football-ai/backups/` → 解压覆盖 `/opt/football-ai/app` → 装后端依赖（无 pip 时跳过）→ `pnpm build` 前端 → `systemctl restart football-ai-api football-ai-web` → 健康检查。

服务器布局：代码 `/opt/football-ai/app`（非 git 仓库），环境变量 `/opt/football-ai/app/.env`（MySQL），systemd 单元 `football-ai-api`（uvicorn :8000）与 `football-ai-web`（next start :3200），nginx :9000 反代。

注意事项：
- 部署包不含 `.env` 与数据库，解压覆盖不会破坏运行配置。
- 服务器 venv 无 pip；`pyproject.toml` 依赖变更时需手动处理。
- 出问题可回滚：`tar -xzf /opt/football-ai/backups/app-<时间戳>.tar.gz -C /opt/football-ai` 后重启服务。
