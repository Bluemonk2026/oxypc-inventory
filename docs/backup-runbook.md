# OxyPC Backup & Recovery Runbook

## Quick Start

### 1. Set your DB password
On Windows (Git Bash):
```bash
export PGPASSWORD=your_db_password
```
Or add to your `.env` file:
```
PGPASSWORD=your_db_password
```

### 2. Run a manual backup
```bash
bash scripts/backup.sh
```
Backup files are saved to `backups/oxypc_YYYYMMDD_HHMMSS.sql.gz`

### 3. Schedule nightly backup (Windows Task Scheduler)
1. Open Task Scheduler -> Create Basic Task
2. Name: "OxyPC Nightly Backup"
3. Trigger: Daily at 2:00 AM
4. Action: Start a program
   - Program: `C:\Program Files\Git\bin\bash.exe`
   - Arguments: `-c "export PGPASSWORD=yourpassword && cd /c/Users/Pankaj.sehgal/Claude/Oxypc/oxypc-inventory && bash scripts/backup.sh >> logs/backup.log 2>&1"`
5. Finish

### 4. Schedule nightly backup (Linux/Mac cron)
```bash
crontab -e
# Add this line:
0 2 * * * cd /path/to/oxypc-inventory && PGPASSWORD=yourpassword bash scripts/backup.sh >> logs/backup.log 2>&1
```

---

## Restore Procedure

**Always test restore in a separate DB first.**

```bash
# Stop the application first
# Then:
export PGPASSWORD=your_db_password
bash scripts/restore.sh backups/oxypc_20260426_020000.sql.gz
# Then run migrations:
alembic upgrade head
# Then restart the application
```

---

## Offsite Copy (Recommended)

Backups on the same machine are not safe from hardware failure.

**Option A — Network drive:**
```bash
# Add to end of backup.sh (after the main backup):
cp "$BACKUP_FILE" "//NETWORKSERVER/backups/oxypc/"
```

**Option B — Cloud (rclone to Google Drive / S3):**
```bash
# Install rclone, configure once, then:
rclone copy "$BACKUP_FILE" gdrive:oxypc-backups/
```

---

## Backup Verification (Monthly)

Test that backups actually restore:
```bash
# Create test DB
createdb oxypc_test -U postgres

# Restore to test DB
OXYPC_DB_NAME=oxypc_test bash scripts/restore.sh backups/latest_backup.sql.gz

# Check row counts
psql -U oxypc -d oxypc_test -c "SELECT COUNT(*) FROM devices; SELECT COUNT(*) FROM sales;"

# Drop test DB
dropdb oxypc_test -U postgres
```

---

## Retention Policy
- Daily backups kept for **30 days** (configurable via `OXYPC_RETENTION_DAYS`)
- At 30-day retention and ~5MB compressed per backup, total storage ~= 150MB
