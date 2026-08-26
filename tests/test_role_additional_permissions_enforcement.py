"""Role Additional Permissions tab (Admin > Master Data): 4 new "Edit" toggles
(Devices/IQC/Lot/GRN) plus "Add New Data" split into Add Lot/Add IQC/Add GRN.

Unlike the per-module Permission Matrix's own Edit/Add checkboxes — which
has_perm() never actually reads (it only checks each module's overall
"enable" bit, per its own docstring) — these ARE real, enforced gates via
require_additional_perm()/require_any_additional_perm(), default-permissive
so nothing changes for a role until an admin explicitly unchecks one.

These tests build their own TestClient AFTER seeding the DB, rather than
using the app_client fixture: the permission cache (_ADDITIONAL_PERM_CACHE)
loads once at app startup, so a row inserted after the fixture's own
TestClient already started would never be seen — same staleness the
production incident earlier this session ran into.
"""
import pathlib
import subprocess
import sys
import uuid

from fastapi.testclient import TestClient

from tests.test_iqc_new_user import _login  # noqa: F401

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


_SEED_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from auth.dependencies import hash_password
from database import AsyncSessionLocal
from models.role_permissions import RoleAdditionalPermission
from models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        db.add(RoleAdditionalPermission(role_name="{role}", {field}=False))
        db.add(User(username="{username}", password_hash=hash_password("{password}"),
                    full_name="ITest", role="{role}", status=True))
        await db.commit()

asyncio.run(main())
"""

_SEED_NO_ROW_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from auth.dependencies import hash_password
from database import AsyncSessionLocal
from models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        db.add(User(username="{username}", password_hash=hash_password("{password}"),
                    full_name="ITest", role="{role}", status=True))
        await db.commit()

asyncio.run(main())
"""

_CLEANUP_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select, delete
from database import AsyncSessionLocal
from models.role_permissions import RoleAdditionalPermission
from models.user import User, LoginLog
from models.engines import AuditLog

async def main():
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(RoleAdditionalPermission).where(
            RoleAdditionalPermission.role_name == "{role}"))).scalar_one_or_none()
        if row:
            await db.delete(row)
        users = (await db.execute(select(User).where(User.role == "{role}"))).scalars().all()
        for u in users:
            # Test activity (login, any action that succeeded) wrote rows FK'd
            # to this throwaway user — clear them first or the delete 409s.
            await db.execute(delete(LoginLog).where(LoginLog.user_id == u.id))
            await db.execute(delete(AuditLog).where(AuditLog.user_id == u.id))
            await db.delete(u)
        await db.commit()

asyncio.run(main())
"""


def _client_after_seeding(seed_src):
    """A fresh TestClient whose startup (and permission-cache load) happens
    strictly AFTER the seed subprocess commits — order matters here."""
    _run(seed_src)
    import main
    return TestClient(main.app)


def test_additional_perms_list_has_the_new_toggles_and_dropped_add_new_data():
    from routers.master import ADDITIONAL_PERMS

    keys = [k for k, _ in ADDITIONAL_PERMS]
    for expected in ("can_add_lot", "can_add_iqc", "can_add_grn",
                      "can_edit_devices", "can_edit_iqc", "can_edit_lot", "can_edit_grn"):
        assert expected in keys, f"{expected} missing from ADDITIONAL_PERMS"
    assert "can_add_new_data" not in keys


def test_edit_devices_false_blocks_device_edit():
    role = f"itest_role_{uuid.uuid4().hex[:6]}"
    username = f"itest_{role}"
    password = "TestPass1234"
    try:
        with _client_after_seeding(_SEED_SRC.format(
                root=ROOT, role=role, field="can_edit_devices", username=username, password=password)) as client:
            _login(client, username, password)
            csrf = client.cookies.get("csrf_token") or "dummy"

            import re
            listing = client.get("/devices/data", follow_redirects=True).text
            m = re.search(r'/devices/([A-Za-z0-9_.\-]+)/edit', listing)
            assert m, "no device edit link found to test against"
            barcode = m.group(1)

            r = client.post(f"/devices/{barcode}/edit", data={"csrf_token": csrf}, follow_redirects=False)
            assert r.status_code == 403, r.text[:300]
    finally:
        _run(_CLEANUP_SRC.format(root=ROOT, role=role))


def test_add_lot_false_blocks_lot_creation():
    role = f"itest_role_{uuid.uuid4().hex[:6]}"
    username = f"itest_{role}"
    password = "TestPass1234"
    try:
        with _client_after_seeding(_SEED_SRC.format(
                root=ROOT, role=role, field="can_add_lot", username=username, password=password)) as client:
            _login(client, username, password)
            csrf = client.cookies.get("csrf_token") or "dummy"

            r = client.post("/lots/new", data={
                "csrf_token": csrf, "lot_number": f"ITEST{uuid.uuid4().hex[:6]}",
                "supplier_name": "Test", "purchase_date": "2026-01-01",
            }, follow_redirects=False)
            assert r.status_code == 403, r.text[:300]
    finally:
        _run(_CLEANUP_SRC.format(root=ROOT, role=role))


def test_permissive_by_default_when_no_row_configured():
    """A role with NO RoleAdditionalPermission row at all must still pass —
    matching the "permissive default" convention used everywhere else."""
    role = f"itest_role_{uuid.uuid4().hex[:6]}"
    username = f"itest_{role}"
    password = "TestPass1234"
    try:
        with _client_after_seeding(_SEED_NO_ROW_SRC.format(
                root=ROOT, role=role, username=username, password=password)) as client:
            _login(client, username, password)
            csrf = client.cookies.get("csrf_token") or "dummy"

            import re
            listing = client.get("/devices/data", follow_redirects=True).text
            m = re.search(r'/devices/([A-Za-z0-9_.\-]+)/edit', listing)
            assert m
            barcode = m.group(1)
            r = client.post(f"/devices/{barcode}/edit", data={"csrf_token": csrf}, follow_redirects=False)
            assert r.status_code != 403, r.text[:300]
    finally:
        _run(_CLEANUP_SRC.format(root=ROOT, role=role))
