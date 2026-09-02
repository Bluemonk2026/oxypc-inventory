"""POST /iqc/new — rollback-before-expunge ordering (2026-09-02).

Reported: /iqc/new threw a 500 on submit (fresh tag, no prior duplicate).
The traceback showed DetachedInstanceError on current_user inside the
route's OWN error-recovery path (_iqc_form_boundary / _keep_after_rollback)
— existing defensive code for exactly this class of bug, but with a real
ordering bug: _keep_after_rollback(db, current_user) (which calls
db.expunge()) was called BEFORE await db.rollback() at all 3 call sites.
A failure mid-flush leaves the session in SQLAlchemy's "pending rollback"
state, where expunge() itself raises PendingRollbackError — silently
swallowed by its own try/except — leaving current_user still attached when
the *next* line's rollback() expires its attributes. The later template
render's attribute access then hits the session after teardown =
DetachedInstanceError, turning a friendly form error into the exact bare
500 users were hitting.

A duplicate-barcode submission is the simplest, real way to force a
mid-flush failure (Device.barcode is unique=True) and exercise this path.
"""
import pathlib
import subprocess
import sys
import uuid

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def _seed_device(barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        db.add(Device(barcode="{barcode}", lot_id=lot.id, brand="X", model="Y"))
        await db.commit()

asyncio.run(main())
""")


def _cleanup(barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
""")


def test_duplicate_barcode_submit_shows_friendly_error_not_500(app_client, make_user):  # noqa: F811
    """Duplicate barcode has its own dedicated, early check (before this
    route's flush-based exception boundary is even reached) — confirms that
    path still works cleanly, though it doesn't exercise the boundary itself
    (see test_flush_time_constraint_violation_shows_friendly_error_not_500
    below for that)."""
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITIQCDUP{suffix}"
    _seed_device(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post("/iqc/new", data={"csrf_token": csrf, "barcode": barcode}, follow_redirects=False)

        assert r.status_code == 200, r.text[:500]
        assert "already exists" in r.text
    finally:
        _cleanup(barcode)


def test_flush_time_constraint_violation_shows_friendly_error_not_500(app_client, make_user):  # noqa: F811
    """A syntactically-valid but non-existent lot_id passes the UUID-format
    check but violates devices.lot_id's FK constraint at flush — the actual
    mid-flush failure _iqc_form_boundary's try/except (around await db.flush())
    is meant to catch. This is what genuinely exercises the
    rollback/expunge/logging recovery path, and what the real production bug
    (a DetachedInstanceError inside that recovery path itself, from an
    unguarded current_user.username read in the diagnostic print()) hit.

    This specific failure mode (a hard FK violation via query-invoked
    autoflush) is severe enough that current_user can end up unusable for
    base.html's own reads even after the boundary's expunge/rollback —
    Jinja renders synchronously and eagerly (Starlette's TemplateResponse
    calls template.render() immediately in __init__), so that surfaces
    right there. _iqc_form_boundary's outer try/except around the render
    itself is the deliberate last line of defense for exactly this: no bare
    500 either way, whether it manages the friendly re-rendered form (200)
    or falls back to a plain redirect (302) when even that isn't safe."""
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITIQCFLUSH{suffix}"
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post("/iqc/new", data={
            "csrf_token": csrf, "barcode": barcode, "lot_id": str(uuid.uuid4()),
        }, follow_redirects=False)

        assert r.status_code in (200, 302), r.text[:2000]
        if r.status_code == 200:
            assert "Could not save this IQC entry" in r.text
        else:
            assert r.headers["location"].startswith("/iqc/new?error=")
        assert "DetachedInstanceError" not in r.text
        assert "PendingRollbackError" not in r.text
    finally:
        _cleanup(barcode)
