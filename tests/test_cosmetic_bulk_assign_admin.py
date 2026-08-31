"""Admin-only bulk Assign on Cleaning/Putty/Dry Sanding/Masking/Painting/
Water Sanding (templates/cosmetic/stage.html):
 - Checkbox column + "Assign" button (injected before DataTables' search box)
   only render for admin.
 - Checking rows enables Assign; submitting the modal posts to
   /cosmetic/bulk-assign, which is admin-gated and issues a fresh WorkID per
   selected tag for its CURRENT stage — no stage change.
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


def test_checkboxes_and_assign_only_for_admin(app_client, make_user):  # noqa: F811
    # Checks the actual rendered DOM elements, not just any substring — the
    # helper JS functions (updateAssignButtonState etc.) are defined
    # unconditionally and harmlessly reference these class/id names even on
    # a page with no matching elements, so a bare "not in html" on those
    # names would false-positive on inert script text.
    username, password = make_user("cosmetic_manager")
    _login(app_client, username, password)
    html = app_client.get("/cosmetic/cleaning", follow_redirects=True).text
    assert 'class="cosmeticRowCheck"' not in html
    assert 'id="cosmeticSelectAll"' not in html
    assert 'id="cosmeticAssignModal"' not in html


def test_checkboxes_and_assign_present_for_admin(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/cosmetic/cleaning", follow_redirects=True).text
    assert 'id="cosmeticSelectAll"' in html
    assert "cosmeticRowCheck" in html
    assert 'id="cosmeticAssignModal"' in html
    assert "cosmeticAssignBtn" in html
    assert ".dataTables_filter" in html  # injected before the search box
    assert "openBulkAssignModal" in html
    assert "submitCosmeticBulkAssign" in html


def test_bulk_assign_rejects_non_admin(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITBAREJ{suffix}"
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
        r = app_client.post("/cosmetic/bulk-assign", data={
            "csrf_token": csrf, "barcodes": barcode, "engineer_user_id": eng_id,
        })
        assert r.status_code == 403, r.text[:300]
    finally:
        _cleanup_device(barcode)


def test_bulk_assign_creates_workid_per_tag_without_moving_stage(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode_a = f"ITBAOKA{suffix}"
    barcode_b = f"ITBAOKB{suffix}"
    _seed_device_at("cleaning", barcode_a)
    _seed_device_at("cleaning", barcode_b)
    try:
        username, password = make_user("admin")
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

        r = app_client.post("/cosmetic/bulk-assign", data={
            "csrf_token": csrf, "barcodes": f"{barcode_a},{barcode_b}", "engineer_user_id": eng_id,
        })
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["ok"] is True
        assert body["assigned"] == 2
        assert len(body["work_ids"]) == 2

        check = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.work_order import WorkOrder

async def main():
    async with AsyncSessionLocal() as db:
        for bc in ["{barcode_a}", "{barcode_b}"]:
            dev = (await db.execute(select(Device).where(Device.barcode == bc))).scalar_one()
            wo = (await db.execute(select(WorkOrder).where(
                WorkOrder.device_id == dev.id, WorkOrder.stage == "clean"))).scalar_one()
            print(dev.current_stage.value)
            print(wo.assigned_username)

asyncio.run(main())
""")
        lines = check.splitlines()
        # Neither tag moved off Cleaning; both got the "{eng_username}" assignment.
        assert lines[0] == "cleaning"
        assert lines[1] == eng_username
        assert lines[2] == "cleaning"
        assert lines[3] == eng_username
    finally:
        _cleanup_device(barcode_a)
        _cleanup_device(barcode_b)


def test_bulk_assign_skips_tags_no_longer_on_a_bulk_assign_stage(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode_ok = f"ITBASKIPOK{suffix}"
    barcode_moved = f"ITBASKIPMOVED{suffix}"
    _seed_device_at("cleaning", barcode_ok)
    _seed_device_at("cosmetic_completed", barcode_moved)  # not a BULK_ASSIGN_STAGES member
    try:
        username, password = make_user("admin")
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
        r = app_client.post("/cosmetic/bulk-assign", data={
            "csrf_token": csrf, "barcodes": f"{barcode_ok},{barcode_moved}", "engineer_user_id": eng_id,
        })
        assert r.status_code == 200, r.text[:300]
        assert r.json()["assigned"] == 1

        r2 = app_client.post("/cosmetic/bulk-assign", data={
            "csrf_token": csrf, "barcodes": barcode_moved, "engineer_user_id": eng_id,
        })
        assert r2.status_code == 400, r2.text[:300]
    finally:
        _cleanup_device(barcode_ok)
        _cleanup_device(barcode_moved)
