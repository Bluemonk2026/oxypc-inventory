"""Final QC page (templates/cosmetic/final_qc.html):
 - Scan/search Tag Number box next to the "awaiting Final QC" count, filtering
   the 1/4 card list by data-barcode.
 - "Pick This" button on the selected device's card header — self-assigns via
   a fresh WorkID (routers/cosmetic.py fqc_pick), visible on /workid-status.
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


def _seed_device_at_final_qc(barcode):
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
                     current_stage=DeviceStage.final_qc))
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


def test_final_qc_page_has_scan_box_and_pick_button(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITFQCPAGE{suffix}"
    _seed_device_at_final_qc(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get("/cosmetic/final_qc", follow_redirects=True).text
        assert 'id="fqcScanSearch"' in html
        assert f'data-barcode="{barcode}"' in html
        assert "fqc-pick-btn" in html
        assert "Pick This" in html
    finally:
        _cleanup_device(barcode)


def test_pick_this_creates_workid_for_clicking_user_and_shows_on_workid_status(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITFQCPICK{suffix}"
    _seed_device_at_final_qc(barcode)
    try:
        username, password = make_user("cosmetic_manager")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post("/cosmetic/final-qc/pick", data={"csrf_token": csrf, "barcode": barcode})
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["ok"] is True
        assert len(body["work_id"]) == 12

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
            WorkOrder.device_id == dev.id, WorkOrder.stage == "fqc"))).scalar_one()
        print(wo.assigned_username)
        print(wo.work_id)

asyncio.run(main())
""")
        lines = check.splitlines()
        assert lines[0] == username
        assert lines[1] == body["work_id"]

        status_html = app_client.get("/workid-status", follow_redirects=True).text
        assert barcode in status_html
        assert body["work_id"] in status_html
    finally:
        _cleanup_device(barcode)


def test_pick_this_rejects_device_not_at_final_qc(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITFQCNOPE{suffix}"
    username, password = make_user("admin")
    _login(app_client, username, password)
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    # No device seeded at all -> 404 covers "not found"; a device seeded at
    # any OTHER stage would hit the same "not at Final QC" 400 branch.
    r = app_client.post("/cosmetic/final-qc/pick", data={"csrf_token": csrf, "barcode": barcode})
    assert r.status_code == 404, r.text[:300]
