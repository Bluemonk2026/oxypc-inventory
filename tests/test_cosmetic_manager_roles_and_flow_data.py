"""Cosmetic Manager / Cosmetic User roles + All Tags "Flow Data":

 - Cosmetic Manager (UserRole.cosmetic_manager) is ALWAYS a page manager on
   every cosmetic page — full pipeline hub, every tag on All Tags, stage nav
   tabs — wired directly to role, no Group Config setup required.
 - A genuine single-stage "Cosmetic User" role (e.g. a custom "Cosmetic
   Cleaning" role) is NEVER a page manager, even if an admin makes that user
   a Group Config manager of an unrelated team — see
   routers/cosmetic.py _is_cosmetic_stage_role / _COSMETIC_HUB_ROLES.
 - "Flow Data" (below the main table on All Tags): a saved list of rows,
   one user picked per mid-pipeline stage column. Admin/Cosmetic Manager
   only — both to view the card and to save/delete rows.
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


def _seed_group(name, manager_username, member_usernames):
    members_py = repr(list(member_usernames))
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from database import AsyncSessionLocal
from models.attendance_group import AttendanceGroup, AttendanceGroupMember

async def main():
    async with AsyncSessionLocal() as db:
        g = AttendanceGroup(name="{name}", manager_username="{manager_username}", is_active=True)
        db.add(g)
        await db.flush()
        for uname in {members_py}:
            db.add(AttendanceGroupMember(group_id=g.id, username=uname))
        await db.commit()
        print(g.id)

asyncio.run(main())
""")


def _cleanup_group(group_id):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.attendance_group import AttendanceGroup, AttendanceGroupMember

async def main():
    async with AsyncSessionLocal() as db:
        for m in (await db.execute(select(AttendanceGroupMember).where(
                AttendanceGroupMember.group_id == "{group_id}"))).scalars().all():
            await db.delete(m)
        g = (await db.execute(select(AttendanceGroup).where(AttendanceGroup.id == "{group_id}"))).scalar_one_or_none()
        if g:
            await db.delete(g)
        await db.commit()

asyncio.run(main())
""")


def _cleanup_flow_row(row_id):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.cosmetic_flow import CosmeticFlowRow

async def main():
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(CosmeticFlowRow).where(
            CosmeticFlowRow.id == "{row_id}"))).scalar_one_or_none()
        if row:
            await db.delete(row)
        await db.commit()

asyncio.run(main())
""")


def test_cosmetic_manager_always_sees_full_tabs_and_all_devices(app_client, make_user):  # noqa: F811
    # No Group Config group seeded at all — cosmetic_manager must still be
    # treated as a manager purely from its role.
    username, password = make_user("cosmetic_manager")
    _login(app_client, username, password)
    html = app_client.get("/cosmetic/all_tags", follow_redirects=True).text
    assert 'href="/cosmetic/cleaning"' in html  # tab bar visible


def test_stage_role_is_never_manager_even_as_group_config_manager(app_client, make_user):  # noqa: F811
    # A genuine single-stage custom role, made a Group Config manager of an
    # (empty) team — the OLD rule (role == admin or is_group_manager) would
    # have made this user a page manager; the new rule must not.
    suffix = uuid.uuid4().hex[:6]
    username, password = make_user("cosmetic_cleaning")
    group_id = _seed_group(f"ITestStageMgr{suffix}", username, [])
    try:
        _login(app_client, username, password)
        html = app_client.get("/cosmetic/cleaning", follow_redirects=True).text
        # href="/cosmetic/cleaning" alone is ambiguous — this SAME role also
        # gets that exact href from the sidebar's own dynamic "Cosmetic
        # Stage" link. The in-page manager tab bar is the only place
        # href="/cosmetic/all_tags" appears (no such sidebar entry exists),
        # so its absence unambiguously means the tab bar itself is hidden.
        assert 'href="/cosmetic/all_tags"' not in html
    finally:
        _cleanup_group(group_id)


def test_flow_data_card_hidden_for_qc_inspector(app_client, make_user):  # noqa: F811
    username, password = make_user("qc_inspector")
    _login(app_client, username, password)
    html = app_client.get("/cosmetic/all_tags", follow_redirects=True).text
    assert "Flow Data" not in html


def test_flow_data_card_hidden_for_custom_cosmetic_role(app_client, make_user):  # noqa: F811
    # Regression: role_allowed()'s custom-role backdoor would have shown the
    # card (with Save/Delete controls the backend then 403s on) to any
    # admin-created role — Flow Data must check the role directly instead.
    username, password = make_user("cosmetic_cleaning")
    _login(app_client, username, password)
    html = app_client.get("/cosmetic/all_tags", follow_redirects=True).text
    assert "Flow Data" not in html


def test_flow_data_card_visible_for_admin_and_cosmetic_manager(app_client, make_user):  # noqa: F811
    for role in ("admin", "cosmetic_manager"):
        username, password = make_user(role)
        _login(app_client, username, password)
        html = app_client.get("/cosmetic/all_tags", follow_redirects=True).text
        assert "Flow Data" in html
        assert 'id="flowAddRowBtn"' in html


def test_flow_data_save_then_appears_selected_on_reload(app_client, make_user):  # noqa: F811
    admin_username, admin_password = make_user("admin")
    cleaner_username, _ = make_user("cosmetic_cleaning")

    cleaner_id = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == "{cleaner_username}"))).scalar_one()
        print(u.id)

asyncio.run(main())
""")

    _login(app_client, admin_username, admin_password)
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    row_id = None
    try:
        r = app_client.post("/cosmetic/flow-data/save", data={
            "csrf_token": csrf, "label": "ITest Flow", "cleaning_user_id": cleaner_id,
        })
        assert r.status_code == 200, r.text[:300]
        row_id = r.json()["id"]

        html = app_client.get("/cosmetic/all_tags", follow_redirects=True).text
        assert "ITest Flow" in html
        row_html = html.split(f'data-row-id="{row_id}"', 1)[1].split("</tr>", 1)[0]
        assert f'value="{cleaner_id}" selected' in row_html
    finally:
        if row_id:
            _cleanup_flow_row(row_id)


def test_flow_data_delete_removes_row(app_client, make_user):  # noqa: F811
    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    csrf = app_client.cookies.get("csrf_token") or "dummy"

    r = app_client.post("/cosmetic/flow-data/save", data={"csrf_token": csrf, "label": "ITest Delete Me"})
    row_id = r.json()["id"]

    r2 = app_client.post("/cosmetic/flow-data/delete", data={"csrf_token": csrf, "row_id": row_id})
    assert r2.status_code == 200, r2.text[:300]

    html = app_client.get("/cosmetic/all_tags", follow_redirects=True).text
    assert "ITest Delete Me" not in html


def test_flow_data_save_rejected_for_qc_inspector(app_client, make_user):  # noqa: F811
    username, password = make_user("qc_inspector")
    _login(app_client, username, password)
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    r = app_client.post("/cosmetic/flow-data/save", data={"csrf_token": csrf, "label": "Should Not Save"})
    assert r.status_code == 403


def test_flow_data_save_rejected_for_custom_cosmetic_role(app_client, make_user):  # noqa: F811
    # Regression: require_roles()'s custom-role backdoor would have let ANY
    # admin-created role through a non-admin-only gate — Flow Data has no
    # Permission Matrix module of its own, so this must be blocked directly
    # by role name, not delegate to that backdoor.
    username, password = make_user("cosmetic_cleaning")
    _login(app_client, username, password)
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    r = app_client.post("/cosmetic/flow-data/save", data={"csrf_token": csrf, "label": "Should Not Save"})
    assert r.status_code == 403
