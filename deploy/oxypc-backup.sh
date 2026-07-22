#!/bin/bash
# OxyPC nightly backup wrapper — install to /usr/local/bin/oxypc-backup
#
#   sudo cp deploy/oxypc-backup.sh /usr/local/bin/oxypc-backup
#   sudo chmod 755 /usr/local/bin/oxypc-backup
#
# Why this exists instead of calling `python scripts/backup_db.py` directly:
# that script's main() ALWAYS prunes backups older than RETENTION_DAYS (30).
# Deleting backups on a schedule is a decision the operator should make
# explicitly, not something a cron job does silently. This wrapper calls
# run_backup() only, and prunes solely when OXYPC_BACKUP_PRUNE=1 is set.
#
# Keeping everything costs almost nothing here: a gzipped dump of this
# database is ~2MB, so a decade of nightly backups is under 8GB. The far more
# expensive mistake is discovering that the backup you needed was pruned.
set -euo pipefail
cd /opt/oxypc
exec /opt/oxypc/venv/bin/python - <<'PY'
import sys, importlib.util
sys.path.insert(0, "/opt/oxypc")

# Load backup_db.py as a module rather than running it. Because __name__ is
# "bk" and not "__main__", its main() (which would prune) never fires.
spec = importlib.util.spec_from_file_location("bk", "/opt/oxypc/scripts/backup_db.py")
bk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bk)

path = bk.run_backup()

import os
if os.environ.get("OXYPC_BACKUP_PRUNE") == "1":
    bk.prune_old_backups()
else:
    files = sorted(bk.BACKUP_DIR.glob("oxypc_*.sql.gz"))
    total = sum(f.stat().st_size for f in files) / (1024 * 1024)
    print(f"Retained {len(files)} backup(s), {total:.1f} MB total (pruning disabled)")
PY
