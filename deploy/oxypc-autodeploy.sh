#!/bin/bash
# OxyPC auto-deploy — install to /usr/local/bin/oxypc-autodeploy
#
#   sudo cp deploy/oxypc-autodeploy.sh /usr/local/bin/oxypc-autodeploy
#   sudo chmod 755 /usr/local/bin/oxypc-autodeploy
#
# Polls origin/main and deploys when it moves. Polling rather than a webhook
# because this box has a private address (10.199.206.109) that GitHub cannot
# reach; the poll is an OUTBOUND fetch, so it works behind NAT with no inbound
# firewall rule and no public exposure.
#
# Exits silently and cheaply when there is nothing to do — a `git fetch` with
# no new commits is a few KB, so a short poll interval costs nothing.
#
# Watch it:  journalctl -u oxypc-autodeploy -f
set -uo pipefail

APP=/opt/oxypc
cd "$APP" || { echo "FATAL: $APP missing"; exit 1; }

git fetch --quiet origin main 2>/dev/null || { echo "fetch failed — network or deploy key problem"; exit 1; }

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0                      # up to date — say nothing, keep the journal readable
fi

# Refuse to deploy over uncommitted local edits. Someone hand-editing a file on
# the server is either debugging or has made a change that exists nowhere else;
# silently overwriting it would destroy work and hide the divergence.
if [ -n "$(git status --porcelain)" ]; then
    echo "REFUSING TO DEPLOY: working tree has uncommitted changes."
    git status --porcelain | head -10
    echo "Resolve by committing, or discarding deliberately, then the next poll will deploy."
    exit 1
fi

echo "deploying ${LOCAL:0:7} -> ${REMOTE:0:7}"
git log --oneline "$LOCAL..$REMOTE" | sed 's/^/  incoming: /'

# Record the previous SHA so a rollback is one obvious command rather than
# archaeology. Deliberately NOT auto-rolling-back on failure: a rollback loop
# would flap every poll and mask the real fault. Fail loudly instead.
echo "$LOCAL" > /var/lib/oxypc-last-good-sha 2>/dev/null || true

CHANGED=$(git diff --name-only "$LOCAL" "$REMOTE")

git merge --ff-only origin/main --quiet || { echo "FATAL: fast-forward failed"; exit 1; }

# Only reinstall dependencies when they actually changed — pip is slow and
# running it on every deploy would turn a 15s restart into minutes.
if echo "$CHANGED" | grep -qx 'requirements.txt'; then
    echo "requirements.txt changed — installing"
    "$APP/venv/bin/pip" install --quiet -r requirements.txt || { echo "FATAL: pip install failed"; exit 1; }
fi

# This project evolves its schema through the additive auto-provisioner rather
# than hand-written migrations (see .github/workflows/deploy.yml). Run it so a
# new model column exists in the DB before code that reads it starts serving —
# otherwise every page touching that column 500s.
if echo "$CHANGED" | grep -qE '^(models/|alembic/)'; then
    echo "models changed — reconciling schema"
    "$APP/venv/bin/python" -c "
import asyncio
from database import engine
from db_validator import validate_and_fix
s = asyncio.run(validate_and_fix(engine, auto_fix=True))
print('  schema: fixed', s['issues_fixed'], 'issue(s)')
" || echo "  WARNING: schema reconcile failed — check before trusting this deploy"
fi

chown -R www-data:www-data "$APP"
chmod 600 "$APP/.env"

systemctl restart oxypc
sleep 12

CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 http://127.0.0.1:8000/health || echo 000)
if [ "$CODE" = "200" ]; then
    echo "DEPLOYED OK: now at $(git log -1 --format='%h %s')"
else
    echo "DEPLOY UNHEALTHY: /health returned $CODE after restart"
    echo "Last known-good commit: $LOCAL"
    echo "Roll back with:  cd $APP && git reset --hard $LOCAL && systemctl restart oxypc"
    journalctl -u oxypc -n 20 --no-pager | tail -20
    exit 1
fi
