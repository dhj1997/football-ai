#!/usr/bin/env bash
# MySQL 备份 + 可恢复性验证（docs/ROLLBACK.md 第 3 节）。
# 在应用服务器上执行：bash deploy/backup-verify.sh [backup [existing_dump.gz]]
#   无参数        ：仅输出 readiness 门禁与数据库元数据
#   backup        ：mysqldump（single-transaction）到 /opt/football-ai/backups/，
#                   恢复到临时库 football_ai_restore_check，逐表行数指纹比对，
#                   验证后自动删除临时库
#   backup <file> ：复用已有 dump 文件做恢复验证
# 密钥仅在本脚本进程内使用，不回显。
set -euo pipefail

APP_DIR=/opt/football-ai/app
BACKUP_DIR=/opt/football-ai/backups
VERIFICATION_MARKER="$BACKUP_DIR/last-verified.json"
API_SERVICE=${BACKUP_API_SERVICE:-football-ai-api}
API_WAS_ACTIVE=0
cd "$APP_DIR"

WORK_DIR=$(mktemp -d /tmp/football-ai-backup-verify.XXXXXX)
case "$WORK_DIR" in
  /tmp/football-ai-backup-verify.*) ;;
  *) echo "invalid temporary directory: $WORK_DIR" >&2; exit 1 ;;
esac
READINESS_JSON="$WORK_DIR/readiness.json"
MYSQLDUMP_ERROR="$WORK_DIR/mysqldump.err"
RESTORE_ERROR="$WORK_DIR/restore.err"
FINGERPRINT_PROD="$WORK_DIR/fp-prod.txt"
FINGERPRINT_CHECK="$WORK_DIR/fp-check.txt"
cleanup() {
  STATUS=$?
  trap - EXIT
  case "$WORK_DIR" in
    /tmp/football-ai-backup-verify.*)
      rm -f -- "$READINESS_JSON" "$MYSQLDUMP_ERROR" "$RESTORE_ERROR" \
        "$FINGERPRINT_PROD" "$FINGERPRINT_CHECK"
      rmdir -- "$WORK_DIR" 2>/dev/null || true
      ;;
  esac
  if [ "$API_WAS_ACTIVE" -eq 1 ]; then
    echo "== restart API writer =="
    if ! systemctl start "$API_SERVICE"; then
      echo "failed to restart $API_SERVICE" >&2
      STATUS=1
    fi
  fi
  exit "$STATUS"
}
trap cleanup EXIT

KEY=$(grep -E '^ADMIN_API_KEY=' .env | head -1 | cut -d= -f2- | tr -d '"')
URL=$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2- | tr -d '"')
CREDS=$(echo "$URL" | sed -E 's|^mysql(\+pymysql)?://||; s|@.*||')
HOSTPORT=$(echo "$URL" | sed -E 's|^mysql(\+pymysql)?://[^@]+@||; s|/.*||')
DB=$(echo "$URL" | sed -E 's|.*/||; s|\?.*||')
DBUSER=$(echo "$CREDS" | cut -d: -f1)
export MYSQL_PWD=$(echo "$CREDS" | cut -d: -f2-)
DBHOST=$(echo "$HOSTPORT" | cut -d: -f1)
DBPORT=$(echo "$HOSTPORT" | cut -d: -f2)
[ -z "$DBPORT" ] && DBPORT=3306
M() { mysql -h "$DBHOST" -P "$DBPORT" -u "$DBUSER" "$@"; }

echo "== readiness =="
if curl -fsS -m 30 -H "x-admin-key: $KEY" http://127.0.0.1:8000/api/production/readiness > "$READINESS_JSON"; then
  python3 - "$READINESS_JSON" <<'PYEOF' 2>/dev/null || head -c 800 "$READINESS_JSON"
import json
import sys

data = json.load(open(sys.argv[1], encoding='utf-8'))
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

echo "== quiesce API writer =="
if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl is required to quiesce $API_SERVICE" >&2
  exit 1
fi
if systemctl is-active --quiet "$API_SERVICE"; then
  API_WAS_ACTIVE=1
  systemctl stop "$API_SERVICE"
fi
if systemctl is-active --quiet "$API_SERVICE"; then
  echo "failed to stop $API_SERVICE" >&2
  exit 1
fi

echo "== backup =="
STAMP=$(date +%Y%m%d-%H%M%S)
DUMP="$BACKUP_DIR/db-$STAMP.sql"
if [ -n "${2:-}" ] && [ -f "${2}" ]; then
  DUMP="$2"
  echo "reusing existing dump: $DUMP"
else
  mkdir -p "$BACKUP_DIR"
  mysqldump -h "$DBHOST" -P "$DBPORT" -u "$DBUSER" --single-transaction --quick --routines --triggers --events "$DB" > "$DUMP" 2>"$MYSQLDUMP_ERROR"
  DUMP_RC=$?
  if [ $DUMP_RC -ne 0 ]; then
    echo "mysqldump FAILED: $(head -c 200 "$MYSQLDUMP_ERROR")"
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
if ! "${RESTORE_CMD[@]}" | M "$CHECKDB" > "$RESTORE_ERROR" 2>&1; then
  echo "restore FAILED: $(head -c 300 "$RESTORE_ERROR")"
  M -e "DROP DATABASE IF EXISTS $CHECKDB;"
  exit 1
fi

ALL_TABLE_LIST=$(M -N -e "SELECT table_name FROM information_schema.tables WHERE table_schema='$DB' AND table_type='BASE TABLE';")
TABLE_LIST="$ALL_TABLE_LIST"
MATCH=0; MISMATCH=0; MISSING=0; QUERY_ERROR=0
: > "$FINGERPRINT_PROD"; : > "$FINGERPRINT_CHECK"
for T in $ALL_TABLE_LIST; do
  PRESENT=$(M -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$CHECKDB' AND table_name='$T';" 2>/dev/null)
  if [ "$PRESENT" != "1" ]; then
    MISSING=$((MISSING+1))
  fi
done
if [ $MISSING -ne 0 ]; then
  M -e "DROP DATABASE IF EXISTS $CHECKDB;"
  echo "RESTORE_MISMATCH missing_tables=$MISSING"
  exit 1
fi
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
  echo "RESTORE_VERIFIED tables=$MATCH"
else
  echo "RESTORE_MISMATCH match=$MATCH mismatch=$MISMATCH missing=$MISSING query_error=$QUERY_ERROR"
  diff "$FINGERPRINT_PROD" "$FINGERPRINT_CHECK" | head -10
  exit 1
fi
echo "backup_file=$DUMP"

DUMP_SHA256=$(sha256sum "$DUMP" | awk '{print $1}')
VERIFIED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
mkdir -p "$BACKUP_DIR"
python3 - "$VERIFICATION_MARKER" "$DB" "$(basename "$DUMP")" "$DUMP_SHA256" "$VERIFIED_AT" "$MATCH" <<'PYEOF'
import json
import os
import sys

path, database, backup_file, sha256, verified_at, tables = sys.argv[1:]
temporary = f"{path}.tmp"
with open(temporary, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "status": "verified",
            "database": database,
            "backup_file": backup_file,
            "backup_sha256": sha256,
            "verified_at": verified_at,
            "verified_tables": int(tables),
        },
        handle,
        ensure_ascii=True,
    )
    handle.write("\n")
os.replace(temporary, path)
PYEOF

echo "== retention (keep 14 days) =="
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-14}
find "$BACKUP_DIR" -name 'db-*.sql.gz' -mtime "+$RETENTION_DAYS" -print -delete | sed 's/^/pruned /'
echo "done"
