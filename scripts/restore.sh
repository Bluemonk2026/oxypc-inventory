#!/usr/bin/env bash
# ============================================================
# OxyPC PostgreSQL Restore Script
# ============================================================
# Usage: bash scripts/restore.sh backups/oxypc_20260426_020000.sql.gz
#
# WARNING: This will DROP all tables and restore from backup.
#          Always test in a separate DB first.
# ============================================================

set -e

BACKUP_FILE="$1"
DB_NAME="${OXYPC_DB_NAME:-oxypc_db}"
DB_USER="${OXYPC_DB_USER:-oxypc}"
DB_HOST="${OXYPC_DB_HOST:-localhost}"
DB_PORT="${OXYPC_DB_PORT:-5432}"

if [ -z "$BACKUP_FILE" ]; then
    echo "Usage: bash scripts/restore.sh <backup_file.sql.gz>"
    echo ""
    echo "Available backups:"
    ls -lht backups/oxypc_*.sql.gz 2>/dev/null | head -10 || echo "  No backups found in backups/"
    exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: File not found: $BACKUP_FILE"
    exit 1
fi

echo "============================================================"
echo "OxyPC Database Restore"
echo "============================================================"
echo "Backup file : $BACKUP_FILE"
echo "Target DB   : $DB_NAME @ $DB_HOST:$DB_PORT"
echo ""
echo "WARNING: This will replace ALL data in $DB_NAME with the backup."
echo "         The app must be stopped before running this."
echo ""
read -p "Type RESTORE to confirm: " confirm

if [ "$confirm" != "RESTORE" ]; then
    echo "Aborted."
    exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting restore from $BACKUP_FILE ..."

gunzip -c "$BACKUP_FILE" | PGPASSWORD="${PGPASSWORD:-}" psql \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restore complete. Run 'alembic upgrade head' to ensure migrations are current."
