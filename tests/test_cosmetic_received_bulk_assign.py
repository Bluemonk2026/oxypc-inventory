"""Bulk Assign on Cosmetic Received (2026-08-31): ported from the 6
mid-pipeline pages' templates/cosmetic/stage.html pattern into
templates/cosmetic/received.html — checkbox column + "Assign" button
(admin only), same /cosmetic/bulk-assign endpoint, now also accepting
DeviceStage.cosmetic_received (added to BULK_ASSIGN_STAGES)."""
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


def _seed_device_at_received(barcode):
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
                     current_stage=DeviceStage.cosmetic_received))
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
    username, password = make_user("cosmetic_manager")
    _login(app_client, username, password)
    html = app_client.get("/cosmetic/cosmetic_received", follow_redirects=True).text
    assert 'class="cosmeticRecvRowCheck"' not in html
    assert 'id="cosmeticRecvSelectAll"' not in html
    assert 'id="cosmeticRecvAssignModal"' not in html


def test_checkboxes_and_assign_present_for_admin(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/cosmetic/cosmetic_received", follow_redirects=True).text
    assert 'id="cosmeticRecvSelectAll"' in html
    assert "cosmeticRecvRowCheck" in html
    assert 'id="cosmeticRecvAssignModal"' in html
    assert "cosmeticRecvAssignBtn" in html
    assert "openCosmeticRecvBulkAssignModal" in html
    assert "submitCosmeticRecvBulkAssign" in html


def test_bulk_assign_creates_workid_per_tag_without_moving_stage(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode_a = f"ITRECVBAA{suffix}"
    barcode_b = f"ITRECVBAB{suffix}"
    _seed_device_at_received(barcode_a)
    _seed_device_at_received(barcode_b)
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
                WorkOrder.device_id == dev.id, WorkOrder.stage == "recv"))).scalar_one()
            print(dev.current_stage.value)
            print(wo.assigned_username)

asyncio.run(main())
""")
        lines = check.splitlines()
        # Neither tag moved off Cosmetic Received; both got the assignment.
        assert lines[0] == "cosmetic_received"
        assert lines[1] == eng_username
        assert lines[2] == "cosmetic_received"
        assert lines[3] == eng_username
    finally:
        _cleanup_device(barcode_a)
        _cleanup_device(barcode_b)
