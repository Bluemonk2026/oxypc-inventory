"""Cosmetic Received..Completed pages — Move-modal assignment, Group Config
Manager/Member visibility, split Permission Matrix modules:

 - Every forward Move now requires an assignee (engineer_user_id) and issues
   a fresh WorkID (WorkOrder), same mechanism as Fail — shows as the WorkID
   first column and on /workid-status.
 - A Group Config manager (AttendanceGroup.manager_username) sees every tag
   and the stage nav tabs; anyone else sees only tags whose latest WorkID on
   that page is assigned to them, tabs hidden.
 - Breadcrumb removed from all pages; Cleaning lost "Move to Final QC"/Fail;
   Water Sanding lost Fail.
 - The Permission Matrix's single "cosmetic" module is now 8 keys
   (routers/master.py PERM_MODULES), enforced per-stage in advance_stage.
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


def _seed_device_at(stage, barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        db.add(Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.{stage}))
        await db.commit()

asyncio.run(main())
""")


def _cleanup_device(barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device, StageMovement
from models.work_order import WorkOrder

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for wo in (await db.execute(select(WorkOrder).where(WorkOrder.device_id == dev.id))).scalars().all():
                await db.delete(wo)
            for m in (await db.execute(select(StageMovement).where(
                    StageMovement.device_id == dev.id))).scalars().all():
                await db.delete(m)
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
""")


def _seed_group(group_name, manager_username, member_usernames):
    members_py = repr(list(member_usernames))
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from database import AsyncSessionLocal
from models.attendance_group import AttendanceGroup, AttendanceGroupMember

async def main():
    async with AsyncSessionLocal() as db:
        g = AttendanceGroup(name="{group_name}", manager_username="{manager_username}", is_active=True)
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


def test_move_without_engineer_is_rejected(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITMVNOENG{suffix}"
    _seed_device_at("cleaning", barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post("/cosmetic/advance", data={"csrf_token": csrf, "barcode": barcode})
        assert r.status_code == 400, r.text[:300]
    finally:
        _cleanup_device(barcode)


def test_move_with_engineer_creates_workid_and_stays_json(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITMVOK{suffix}"
    _seed_device_at("cleaning", barcode)
    try:
        username, password = make_user("cosmetic_manager")
        eng_username, _ = make_user("cosmetic_manager")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        eng_id = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == "{eng_username}"))).scalar_one()
        print(u.id)

asyncio.run(main())
""")

        r = app_client.post("/cosmetic/advance", data={
            "csrf_token": csrf, "barcode": barcode, "engineer_user_id": eng_id,
        })
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["ok"] is True
        assert body["moved_to"] == "putty"
        assert body["work_id"] and len(body["work_id"]) == 12

        check = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.work_order import WorkOrder

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        wo = (await db.execute(select(WorkOrder).where(
            WorkOrder.device_id == dev.id, WorkOrder.stage == "putty"))).scalar_one()
        print(dev.current_stage.value)
        print(wo.assigned_username)
        print(wo.work_id)

asyncio.run(main())
""")
        lines = check.splitlines()
        assert lines[0] == "putty"
        assert lines[1] == eng_username
        assert lines[2] == body["work_id"]
    finally:
        _cleanup_device(barcode)


def test_group_manager_sees_all_tabs_and_devices_member_sees_own_only(app_client, make_user):  # noqa: F811
    # qc_inspector, not cosmetic_manager: cosmetic_manager is now ALWAYS
    # treated as a page manager (wired directly to role — see
    # routers/cosmetic.py _is_cosmetic_stage_role / _COSMETIC_HUB_ROLES), so
    # it can no longer stand in for a Group-Config-only "member" here.
    # qc_inspector is a general-purpose supervisor role excluded from that
    # override, so its manager/member status here is driven purely by
    # Group Config membership, same as before this feature.
    suffix = uuid.uuid4().hex[:6]
    manager_username, manager_password = make_user("qc_inspector")
    member_username, member_password = make_user("qc_inspector")
    other_username, _ = make_user("qc_inspector")
    group_id = _seed_group(f"ITestCosmeticTeam{suffix}", manager_username, [member_username])

    barcode_mine = f"ITGRPMINE{suffix}"
    barcode_others = f"ITGRPOTHER{suffix}"
    _seed_device_at("putty", barcode_mine)
    _seed_device_at("putty", barcode_others)
    # Give barcode_mine a putty-stage WorkOrder assigned to member_username,
    # and barcode_others one assigned to a different user.
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.work_order import WorkOrder

async def main():
    async with AsyncSessionLocal() as db:
        d1 = (await db.execute(select(Device).where(Device.barcode == "{barcode_mine}"))).scalar_one()
        d2 = (await db.execute(select(Device).where(Device.barcode == "{barcode_others}"))).scalar_one()
        db.add(WorkOrder(work_id="ITWGM1{suffix}", device_id=d1.id, barcode=d1.barcode,
                         stage="putty", assigned_username="{member_username}", status="pending"))
        db.add(WorkOrder(work_id="ITWGM2{suffix}", device_id=d2.id, barcode=d2.barcode,
                         stage="putty", assigned_username="{other_username}", status="pending"))
        await db.commit()

asyncio.run(main())
""")
    try:
        # Manager view: sees both tags + tabs. href="/cosmetic/all_tags" is
        # used (not "/cosmetic/cleaning") because qc_inspector also gets
        # that SAME href from the sidebar's own dynamic "Cosmetic Stage"
        # link regardless of manager/member status — the in-page manager
        # tab bar is the only place href="/cosmetic/all_tags" appears (no
        # such sidebar entry exists), so it unambiguously signals the tab
        # bar itself.
        _login(app_client, manager_username, manager_password)
        html_mgr = app_client.get("/cosmetic/putty", follow_redirects=True).text
        assert barcode_mine in html_mgr
        assert barcode_others in html_mgr
        assert "Cosmetic Pipeline" not in html_mgr  # breadcrumb removed
        assert 'href="/cosmetic/all_tags"' in html_mgr  # tabs visible

        # Member view: sees only their own tag, no tabs.
        app_client.cookies.clear()
        _login(app_client, member_username, member_password)
        html_mem = app_client.get("/cosmetic/putty", follow_redirects=True).text
        assert barcode_mine in html_mem
        assert barcode_others not in html_mem
        assert 'href="/cosmetic/all_tags"' not in html_mem  # tabs hidden
    finally:
        _cleanup_device(barcode_mine)
        _cleanup_device(barcode_others)
        _cleanup_group(group_id)


def test_cleaning_page_no_longer_has_move_to_final_qc_or_fail():
    src = open(pathlib.Path(ROOT) / "templates" / "cosmetic" / "stage.html", encoding="utf-8").read()
    assert "openFailModal(" not in src
    assert "cosmeticFailModal" not in src
    assert "Fail — Assign to L1/L2 Engineer" not in src
    assert "Done & Move to Final QC" not in src
    assert "final_qc" not in src.lower()


def test_breadcrumb_removed_from_all_three_templates():
    for name in ("stage.html", "received.html", "completed.html"):
        src = open(pathlib.Path(ROOT) / "templates" / "cosmetic" / name, encoding="utf-8").read()
        assert "Cosmetic Pipeline</a>" not in src, name
        assert "breadcrumb" not in src, name


def test_received_and_completed_still_have_fail_but_final_qc_moves_skip_modal():
    for name in ("received.html", "completed.html"):
        src = open(pathlib.Path(ROOT) / "templates" / "cosmetic" / name, encoding="utf-8").read()
        assert "openFailModal(" in src, name
        assert "<th>WorkID</th>" in src, name
    # received.html's "Move to Cleaning" still goes through the assignee
    # modal, like every other regular cosmetic-line Move — but its "skip
    # cosmetic stages" button (also landing on Final QC) is now direct too.
    received_src = open(pathlib.Path(ROOT) / "templates" / "cosmetic" / "received.html", encoding="utf-8").read()
    assert "openMoveModal(" in received_src
    assert "directMoveToFinalQC(" in received_src
    # completed.html's "Move to Final QC" is the one Move that does NOT use a
    # modal — it moves straight through with no assignee (Final QC has its
    # own page-level permission model, not a per-device WorkID handoff).
    completed_src = open(pathlib.Path(ROOT) / "templates" / "cosmetic" / "completed.html", encoding="utf-8").read()
    assert "openMoveModal(" not in completed_src
    assert "directMoveToFinalQC(" in completed_src


def test_perm_modules_split_into_eight_cosmetic_keys():
    src = open(pathlib.Path(ROOT) / "routers" / "master.py", encoding="utf-8").read()
    block = src.split("PERM_MODULES = [", 1)[1].split("\n]", 1)[0]
    for key in ("cosmetic_received", "cosmetic_cleaning", "cosmetic_putty",
                "cosmetic_dry_sanding", "cosmetic_masking", "cosmetic_painting",
                "cosmetic_water_sanding", "cosmetic_completed"):
        assert f'"{key}"' in block, key
    assert '("cosmetic",' not in block

# test_split_permission_blocks_only_the_specific_stage lives in its own file
# (test_cosmetic_split_permission_isolated.py) — it seeds a RoleModulePermission
# row BEFORE constructing its own fresh TestClient, which must not share a
# pytest process with the app_client-fixture tests above (asyncpg cross-event-
# loop RuntimeError — same class of issue documented in
# test_role_additional_permissions_enforcement.py).
