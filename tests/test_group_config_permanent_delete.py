"""Group Config (Application Settings) delete: routers/attendance_group_config.py

 - Deleting a group must PERMANENTLY remove it (and its members), not just
   flip is_active=False — a soft-deleted "ghost" row kept blocking the same
   name from being reused ("Group name already exists") even though the
   group was gone from every visible list.
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


def _row_exists(name):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.attendance_group import AttendanceGroup

async def main():
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(AttendanceGroup).where(
            AttendanceGroup.name == "{name}"))).scalar_one_or_none()
        print(row is not None)

asyncio.run(main())
""")


def test_delete_permanently_removes_row_and_members(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    name = f"ITestDelGrp{suffix}"
    manager_username, _ = make_user("qc_inspector")
    member_username, _ = make_user("qc_inspector")

    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    csrf = app_client.cookies.get("csrf_token") or "dummy"

    r = app_client.post("/admin/attendance-config/create", data={
        "csrf_token": csrf, "name": name, "manager_username": manager_username,
        "members": [member_username],
    }, follow_redirects=False)
    assert r.status_code == 302, r.text[:300]
    assert _row_exists(name) == "True"

    group_id = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.attendance_group import AttendanceGroup

async def main():
    async with AsyncSessionLocal() as db:
        g = (await db.execute(select(AttendanceGroup).where(
            AttendanceGroup.name == "{name}"))).scalar_one()
        print(g.id)

asyncio.run(main())
""")

    r2 = app_client.post(f"/admin/attendance-config/{group_id}/delete", data={"csrf_token": csrf},
                         follow_redirects=False)
    assert r2.status_code == 302, r2.text[:300]

    assert _row_exists(name) == "False", "delete must permanently remove the row, not soft-delete it"

    members_left = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.attendance_group import AttendanceGroupMember

async def main():
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(AttendanceGroupMember).where(
            AttendanceGroupMember.group_id == "{group_id}"))).scalars().all()
        print(len(rows))

asyncio.run(main())
""")
    assert members_left == "0"


def test_deleting_then_recreating_with_same_name_does_not_error(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    name = f"ITestReuseGrp{suffix}"
    manager_username, _ = make_user("qc_inspector")

    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    csrf = app_client.cookies.get("csrf_token") or "dummy"

    r1 = app_client.post("/admin/attendance-config/create", data={
        "csrf_token": csrf, "name": name, "manager_username": manager_username, "members": [],
    }, follow_redirects=True)
    assert "already exists" not in r1.text

    group_id = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.attendance_group import AttendanceGroup

async def main():
    async with AsyncSessionLocal() as db:
        g = (await db.execute(select(AttendanceGroup).where(
            AttendanceGroup.name == "{name}"))).scalar_one()
        print(g.id)

asyncio.run(main())
""")
    app_client.post(f"/admin/attendance-config/{group_id}/delete", data={"csrf_token": csrf})

    # Regression: this used to redirect with error=Group+name+already+exists
    # because delete only flipped is_active=False.
    r2 = app_client.post("/admin/attendance-config/create", data={
        "csrf_token": csrf, "name": name, "manager_username": manager_username, "members": [],
    }, follow_redirects=True)
    assert "already exists" not in r2.text
    assert _row_exists(name) == "True"
