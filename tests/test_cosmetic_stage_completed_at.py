"""Cosmetic pipeline stage WorkOrders now get a Completed Date
(routers/cosmetic.py advance_stage, 2026-09-01):

Previously only Final QC's own "fqc" WorkOrder ever got closed
(status="completed", completed_at=...) when a device left that stage —
every mid-pipeline stage's WorkOrder (Cleaning, Putty, Dry Sanding, ...)
stayed "pending" forever, even long after the tag moved on, so
/workid-status had no "date completed Cleaning stage" / "date completed
Putty stage" to show. Moving a device off ANY cosmetic-pipeline stage now
closes out that stage's own pending WorkOrder the same way Final QC's
always did — its Completed Date now shows on /workid-status.
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


def _seed_device_with_pending_workorder(barcode, stage, stage_code, username):
    work_id = uuid.uuid4().hex[:12]
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.user import User
from models.work_order import WorkOrder

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.{stage})
        db.add(dev)
        await db.flush()
        u = (await db.execute(select(User).where(User.username == "{username}"))).scalar_one()
        db.add(WorkOrder(work_id="{work_id}", device_id=dev.id, barcode="{barcode}",
                         stage="{stage_code}", assigned_role=u.role.value,
                         assigned_user_id=u.id, assigned_username=u.username,
                         assigned_name=u.full_name, status="pending", created_by="itest"))
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


def _workorder_status(barcode, stage_code):
    return _run(f"""
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
            WorkOrder.device_id == dev.id, WorkOrder.stage == "{stage_code}"))).scalar_one()
        print(wo.status)
        print("has_completed_at" if wo.completed_at else "no_completed_at")
        print(wo.work_id)

asyncio.run(main())
""")


def test_moving_off_cleaning_closes_its_workorder_with_completed_at(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITSTGDONE{suffix}"
    cleaner_username, _ = make_user("cosmetic_cleaning")
    putty_username, _ = make_user("cosmetic_putty")
    _seed_device_with_pending_workorder(barcode, "cleaning", "clean", cleaner_username)
    try:
        admin_username, admin_password = make_user("admin")
        _login(app_client, admin_username, admin_password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        putty_id = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == "{putty_username}"))).scalar_one()
        print(u.id)

asyncio.run(main())
""")
        r = app_client.post("/cosmetic/advance", data={
            "csrf_token": csrf, "barcode": barcode, "engineer_user_id": putty_id,
        })
        assert r.status_code == 200, r.text[:400]

        lines = _workorder_status(barcode, "clean").splitlines()
        assert lines[0] == "completed"
        assert lines[1] == "has_completed_at"
        clean_work_id = lines[2]

        # New Putty WorkOrder created fresh, still pending — untouched.
        putty_lines = _workorder_status(barcode, "putty").splitlines()
        assert putty_lines[0] == "pending"
        assert putty_lines[1] == "no_completed_at"

        status_html = app_client.get(f"/workid-status?workid={clean_work_id}", follow_redirects=True).text
        assert clean_work_id in status_html
        assert ">Completed Date<" in status_html
    finally:
        _cleanup_device(barcode)
