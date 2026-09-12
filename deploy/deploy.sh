#!/usr/bin/env bash
# 一键部署：本地打包 -> workbench 上传 -> 服务器解压覆盖 -> 重建前端 -> 重启服务 -> 健康检查。
# 用法：在仓库根目录执行  ./deploy/deploy.sh
# 依赖：阿里云 Workbench CLI（~/.workbench/config.json 已配置凭据）。
set -euo pipefail

INSTANCE_ID="i-bp1eqjmg6qtfa2lfzmpv"
REGION="cn-hangzhou"
REMOTE_APP_DIR="/opt/football-ai/app"
NODE_BIN_DIR="/opt/node-v22.23.2-linux-x64/bin"
WB="${LOCALAPPDATA:-$HOME/AppData/Local}/Programs/workbench/workbench.exe"
STAMP="$(date +%Y%m%d-%H%M%S)"
PKG="football-ai-deploy-${STAMP}.tar.gz"

cd "$(dirname "$0")/.."
echo "[1/6] 打包本地代码（排除 .venv / node_modules / .next / .env / 数据库）"
tar -czf "/tmp/${PKG}" \
  --exclude='.git' --exclude='.venv' --exclude='node_modules' --exclude='.next' \
  --exclude='.env' --exclude='*.db' --exclude='.planning' --exclude='dist' \
  apps deploy docs AGENTS.md DESIGN.md PRODUCT.md README.md package.json pnpm-workspace.yaml 2>/dev/null \
  || tar -czf "/tmp/${PKG}" --exclude='.git' --exclude='.venv' --exclude='node_modules' --exclude='.next' \
      --exclude='.env' --exclude='*.db' --exclude='.planning' --exclude='dist' \
      apps deploy AGENTS.md README.md package.json pnpm-workspace.yaml

echo "[2/6] 上传到服务器"
# MSYS_NO_PATHCONV=1 阻止 Git Bash 把远端 /tmp 路径改写成 Windows 路径；本地路径需显式转成 Windows 格式
MSYS_NO_PATHCONV=1 "$WB" upload "$(cygpath -w "/tmp/${PKG}")" "/tmp/${PKG}" -f -i "$INSTANCE_ID" -r "$REGION"

echo "[3/6] 服务器端：备份当前版本并解压覆盖"
"$WB" exec -i "$INSTANCE_ID" -r "$REGION" --timeout 120 -c "
set -e
mkdir -p /opt/football-ai/backups
tar -czf /opt/football-ai/backups/app-${STAMP}.tar.gz -C /opt/football-ai \
  --exclude='app/apps/api/.venv' --exclude='app/apps/web/node_modules' --exclude='app/apps/web/.next' app
tar -xzf /tmp/${PKG} -C ${REMOTE_APP_DIR}
chown -R football-ai:football-ai ${REMOTE_APP_DIR}
rm -f /tmp/${PKG}
echo extracted
"

echo "[4/6] 服务器端：安装后端依赖 + 构建前端"
"$WB" exec -i "$INSTANCE_ID" -r "$REGION" --timeout 600 -c "
set -e
# 服务器 venv 无 pip（依赖由其他方式安装）；依赖未变时跳过是安全的，pyproject 变更后需手动补装
sudo -u football-ai ${REMOTE_APP_DIR}/apps/api/.venv/bin/python -m pip install -q -e ${REMOTE_APP_DIR}/apps/api \
  || echo 'pip 不可用，跳过依赖同步（依赖未变化时无影响）'
export PATH=${NODE_BIN_DIR}:\$PATH
cd ${REMOTE_APP_DIR}/apps/web
sudo -u football-ai env PATH=\$PATH pnpm install --prefer-offline || echo 'pnpm install skipped'
sudo -u football-ai env PATH=\$PATH pnpm build
"

echo "[5/6] 重启服务"
"$WB" exec -i "$INSTANCE_ID" -r "$REGION" --timeout 120 -c "
systemctl restart football-ai-api football-ai-web
sleep 6
systemctl --no-pager --lines=3 status football-ai-api football-ai-web | head -30
"

echo "[6/6] 健康检查"
"$WB" exec -i "$INSTANCE_ID" -r "$REGION" --timeout 60 -c "
curl -fsS http://127.0.0.1:8000/health | head -c 200; echo
curl -fsS -o /dev/null -w 'web:%{http_code}\n' http://127.0.0.1:3200/
"

echo "部署完成：${PKG}（服务器备份 /opt/football-ai/backups/app-${STAMP}.tar.gz）"
