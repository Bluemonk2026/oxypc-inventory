#!/usr/bin/env bash
# ============================================================
# OxyPC PostgreSQL Backup Script
# ============================================================
# Usage:     bash scripts/backup.sh
# Windows:   Run via Git Bash or WSL
# Linux:     bash scripts/backup.sh
#
# Schedule (Linux cron — runs 2am daily):
#   0 2 * * * cd /path/to/oxypc-inventory && bash scripts/backup.sh >> logs/backup.log 2>&1
#
# Schedule (Windows Task Scheduler):
#   Program: C:\Program Files\Git\bin\bash.exe
#   Args:    -c "cd /c/path/to/oxypc-inventory && bash scripts/backup.sh"
#
# Environment variables (override defaults):
#   OXYPC_DB_NAME   — default: oxypc_db
#   OXYPC_DB_USER   — default: oxypc
#   OXYPC_DB_HOST   — default: localhost
#   OXYPC_DB_PORT   — default: 5432
#   PGPASSWORD      — set to your DB password (required)
#   OXYPC_BACKUP_DIR — default: backups
# ============================================================

set -e

DB_NAME="${OXYPC_DB_NAME:-oxypc_db}"
DB_USER="${OXYPC_DB_USER:-oxypc}"
DB_HOST="${OXYPC_DB_HOST:-localhost}"
DB_PORT="${OXYPC_DB_PORT:-5432}"
BACKUP_DIR="${OXYPC_BACKUP_DIR:-backups}"
RETENTION_DAYS="${OXYPC_RETENTION_DAYS:-30}"

mkdir -p "$BACKUP_DIR"
mkdir -p "logs"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/oxypc_${TIMESTAMP}.sql.gz"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] =============================="
echo "[$(date '+%Y-%m-%d %H:%M:%S')] OxyPC Backup Starting"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Database : $DB_NAME @ $DB_HOST:$DB_PORT"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Output   : $BACKUP_FILE"

if [ -z "$PGPASSWORD" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: PGPASSWORD not set — pg_dump may prompt for password"
fi

pg_dump \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    --no-password \
    | gzip > "$BACKUP_FILE"

SIZE=$(du -h "$BACKUP_FILE" 2>/dev/null | cut -f1 || echo "?")
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup complete: $BACKUP_FILE ($SIZE)"

# Cleanup old backups
DELETED=$(find "$BACKUP_DIR" -name "oxypc_*.sql.gz" -mtime +$RETENTION_DAYS 2>/dev/null | wc -l)
find "$BACKUP_DIR" -name "oxypc_*.sql.gz" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleaned up $DELETED backup(s) older than $RETENTION_DAYS days"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] =============================="
