"""
OxyPC Database Backup Script
Run manually or schedule via Windows Task Scheduler / cron.

Usage:
    python backup_db.py

Creates: backups/oxypc_db_YYYY-MM-DD_HHMMSS.sql.gz
Keeps last 30 backups, deletes older ones automatically.

Schedule (Windows Task Scheduler):
    - Trigger: Daily at 11:00 PM
    - Action: python C:\path\to\oxypc-inventory\backup_db.py
    - Start in: C:\path\to\oxypc-inventory
"""
import os, subprocess, gzip, shutil, sys
from datetime import datetime
from pathlib import Path

# Load .env so secrets don't need to be hardcoded here
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# ── Config — read from environment (set via .env or OS env vars) ──────────────
DB_HOST = os.environ.get("OXYPC_DB_HOST", "localhost")
DB_PORT = os.environ.get("OXYPC_DB_PORT", "5432")
DB_NAME = os.environ.get("OXYPC_DB_NAME", "oxypc_db")
DB_USER = os.environ.get("OXYPC_DB_USER", "oxypc")
DB_PASS = os.environ.get("OXYPC_BACKUP_DB_PASS", "")
if not DB_PASS:
    print("ERROR: OXYPC_BACKUP_DB_PASS environment variable is not set.")
    print("  Set it in .env or as an OS environment variable before running this script.")
    sys.exit(1)
BACKUP_DIR  = Path(__file__).parent / "backups"
KEEP_DAYS   = 30   # keep last 30 backups

def run():
    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dump_file  = BACKUP_DIR / f"oxypc_db_{ts}.sql"
    gz_file    = BACKUP_DIR / f"oxypc_db_{ts}.sql.gz"

    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASS

    print(f"[{ts}] Starting backup of {DB_NAME}...")

    # Run pg_dump
    result = subprocess.run(
        ["pg_dump", "-h", DB_HOST, "-p", DB_PORT, "-U", DB_USER,
         "-F", "p", "--no-password", "-f", str(dump_file), DB_NAME],
        env=env, capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"  ERROR: pg_dump failed: {result.stderr}")
        sys.exit(1)

    # Compress
    with open(dump_file, 'rb') as f_in:
        with gzip.open(gz_file, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    dump_file.unlink()

    size_mb = gz_file.stat().st_size / 1024 / 1024
    print(f"  Backup saved: {gz_file.name} ({size_mb:.2f} MB)")

    # Prune old backups (keep last KEEP_DAYS)
    backups = sorted(BACKUP_DIR.glob("oxypc_db_*.sql.gz"))
    if len(backups) > KEEP_DAYS:
        for old in backups[:-KEEP_DAYS]:
            old.unlink()
            print(f"  Deleted old backup: {old.name}")

    print(f"  Done. Total backups: {len(list(BACKUP_DIR.glob('*.sql.gz')))}")

if __name__ == "__main__":
    run()
