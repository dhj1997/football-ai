#!/usr/bin/env bash
# MySQL 备份 + 可恢复性验证（docs/ROLLBACK.md 第 3 节）。
# 在应用服务器上执行：bash deploy/backup-verify.sh [backup [existing_dump.gz]]
#   无参数        ：仅输出 readiness 门禁与数据库元数据
#   backup        ：mysqldump（single-transaction）到 /opt/football-ai/backups/，
#                   恢复到临时库 football_ai_restore_check，逐表行数指纹比对，
#                   验证后自动删除临时库
#   backup <file> ：复用已有 dump 文件做恢复验证
# 密钥仅在本脚本进程内使用，不回显。
set -uo pipefail

APP_DIR=/opt/football-ai/app
BACKUP_DIR=/opt/football-ai/backups
cd "$APP_DIR"

KEY=$(grep -E '^ADMIN_API_KEY=' .env | head -1 | cut -d= -f2- | tr -d '"')
URL=$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2- | tr -d '"')
CREDS=$(echo "$URL" | sed -E 's|^mysql(://)?||; s|@.*||')
HOSTPORT=$(echo "$URL" | sed -E 's|^mysql(://)?[^@]+@||; s|/.*||')
DB=$(echo "$URL" | sed -E 's|.*/||; s|\?.*||')
DBUSER=$(echo "$CREDS" | cut -d: -f1)
export MYSQL_PWD=$(echo "$CREDS" | cut -d: -f2-)
DBHOST=$(echo "$HOSTPORT" | cut -d: -f1)
DBPORT=$(echo "$HOSTPORT" | cut -d: -f2)
[ -z "$DBPORT" ] && DBPORT=3306
M() { mysql -h "$DBHOST" -P "$DBPORT" -u "$DBUSER" "$@"; }

echo "== readiness =="
if curl -fsS -m 30 -H "x-admin-key: $KEY" http://127.0.0.1:8000/api/production/readiness > /tmp/readiness.json; then
  python3 - <<'PYEOF' 2>/dev/null || head -c 800 /tmp/readiness.json
import json
data = json.load(open('/tmp/readiness.json'))
print('status:', data.get('status'))
print('environment:', data.get('environment'))
print('config_violations:', data.get('config_violations'))
print('migration_dry_run:', {k: data.get('migration_dry_run', {}).get(k) for k in ('status', 'reason')})
print('smoke:', {c['check']: c['status'] for c in data.get('smoke', {}).get('checks', [])})
PYEOF
else
  echo 'readiness FAILED'
fi

echo "== db metadata (host=$DBHOST db=$DB) =="
SIZE=$(M -N -e "SELECT ROUND(SUM(data_length+index_length)/1024/1024,1) FROM information_schema.tables WHERE table_schema='$DB';" 2>/dev/null)
TABLES=$(M -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$DB';" 2>/dev/null)
echo "size_mb=$SIZE tables=$TABLES"

if [ "${1:-}" != "backup" ]; then
  exit 0
fi

echo "== backup =="
STAMP=$(date +%Y%m%d-%H%M%S)
DUMP="$BACKUP_DIR/db-$STAMP.sql"
if [ -n "${2:-}" ] && [ -f "${2}" ]; then
  DUMP="$2"
  echo "reusing existing dump: $DUMP"
else
  mkdir -p "$BACKUP_DIR"
  mysqldump -h "$DBHOST" -P "$DBPORT" -u "$DBUSER" --single-transaction --quick --routines --triggers --events "$DB" > "$DUMP" 2>/tmp/mysqldump.err
  DUMP_RC=$?
  if [ $DUMP_RC -ne 0 ]; then
    echo "mysqldump FAILED: $(head -c 200 /tmp/mysqldump.err)"
    exit 1
  fi
  gzip -f "$DUMP"
  DUMP="$DUMP.gz"
fi
ls -la "$DUMP"

echo "== restore verification =="
CHECKDB=football_ai_restore_check
M -e "DROP DATABASE IF EXISTS $CHECKDB;"
M -e "CREATE DATABASE $CHECKDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
if [[ "$DUMP" == *.gz ]]; then
  RESTORE_CMD=(zcat "$DUMP")
else
  RESTORE_CMD=(cat "$DUMP")
fi
if ! "${RESTORE_CMD[@]}" | M "$CHECKDB" > /tmp/restore.err 2>&1; then
  echo "restore FAILED: $(head -c 300 /tmp/restore.err)"
  M -e "DROP DATABASE IF EXISTS $CHECKDB;"
  exit 1
fi

# 热表在 dump 后仍被自动化写入（job 心跳/赔率同步），其行数漂移不构成
# 恢复失败；严格指纹只比较冷数据表。
HOT_TABLES="job_runs|odds_snapshots|sync_metadata|data_sync_runs"
TABLE_LIST=$(M -N -e "SELECT table_name FROM information_schema.tables WHERE table_schema='$DB' AND table_type='BASE TABLE';" | grep -Ev "^($HOT_TABLES)$")
MATCH=0; MISMATCH=0; MISSING=0; QUERY_ERROR=0
FINGERPRINT_PROD=/tmp/fp-prod.txt; FINGERPRINT_CHECK=/tmp/fp-check.txt
: > "$FINGERPRINT_PROD"; : > "$FINGERPRINT_CHECK"
for T in $TABLE_LIST; do
  PC=$(M -N -D "$DB" -e "SELECT COUNT(*) FROM \`$T\`;" 2>/dev/null)
  CC=$(M -N -e "SELECT COUNT(*) FROM \`$CHECKDB\`.\`$T\`;" 2>/dev/null)
  echo "$T $PC" >> "$FINGERPRINT_PROD"
  echo "$T $CC" >> "$FINGERPRINT_CHECK"
  if [ -z "$PC" ] || [ -z "$CC" ]; then
    QUERY_ERROR=$((QUERY_ERROR+1))
  elif [ "$PC" = "$CC" ]; then
    MATCH=$((MATCH+1))
  else
    MISMATCH=$((MISMATCH+1))
  fi
done
M -e "DROP DATABASE IF EXISTS $CHECKDB;"

echo "== fingerprint =="
if [ $QUERY_ERROR -eq 0 ] && [ $MISSING -eq 0 ] && [ $MISMATCH -eq 0 ]; then
  echo "RESTORE_VERIFIED tables=$MATCH (hot tables excluded: $HOT_TABLES)"
else
  echo "RESTORE_MISMATCH match=$MATCH mismatch=$MISMATCH missing=$MISSING query_error=$QUERY_ERROR"
  diff "$FINGERPRINT_PROD" "$FINGERPRINT_CHECK" | head -10
fi
echo "backup_file=$DUMP"

echo "== retention (keep 14 days) =="
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-14}
find "$BACKUP_DIR" -name 'db-*.sql.gz' -mtime "+$RETENTION_DAYS" -print -delete | sed 's/^/pruned /'
echo "done"
