"""Final QC "Pick This" resets when a tag leaves and later returns
(routers/cosmetic.py advance_stage, fqc_pick, cosmetic_stage_list):

 - Leaving Final QC (pass or fail) closes out any pending "fqc" WorkOrder
   for that device (status -> completed) — a tag that later comes back
   around to Final QC (e.g. after Assign routes it through L1/L2 or Stress
   Test for rework) must show up unpicked again, not still "Picked by"
   whoever picked it on the earlier visit.
 - The SAME user who picked it the first time can pick it again on the
   return visit — this isn't a "can't repick, ever" rule, it's a per-visit
   lock.
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


def _return_device_to_final_qc(barcode):
    """Simulate the device having gone through a full rework loop (fail ->
    L1/L2 -> ... -> back to Final QC) by just resetting current_stage — the
    actual routing back is exercised elsewhere; this test is only about the
    Pick state, not the full journey."""
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device, DeviceStage

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        dev.current_stage = DeviceStage.final_qc
        dev.bucket_id = None
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


def _fqc_workorder_statuses(barcode):
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
        wos = (await db.execute(select(WorkOrder).where(
            WorkOrder.device_id == dev.id, WorkOrder.stage == "fqc")
            .order_by(WorkOrder.assigned_at))).scalars().all()
        print(",".join(wo.status for wo in wos))

asyncio.run(main())
""")


def test_fail_closes_pending_fqc_workorder(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITPICKRST{suffix}"
    picker_username, picker_password = make_user("admin")
    _seed_device_at_final_qc(barcode)
    try:
        _login(app_client, picker_username, picker_password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r_pick = app_client.post("/cosmetic/final-qc/pick", data={"csrf_token": csrf, "barcode": barcode})
        assert r_pick.status_code == 200, r_pick.text[:300]

        r_fail = app_client.post("/cosmetic/advance", data={
            "csrf_token": csrf, "barcode": barcode, "final_qc_status": "fail",
            "failure_reason": "Hardware", "bucket_name": f"ITestPickBkt{suffix}",
        }, follow_redirects=False)
        assert r_fail.status_code == 302, r_fail.text[:300]

        assert _fqc_workorder_statuses(barcode) == "completed"
    finally:
        _cleanup_device(barcode)


def test_repick_allowed_after_tag_returns_to_final_qc(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITPICKRET{suffix}"
    picker_username, picker_password = make_user("admin")
    _seed_device_at_final_qc(barcode)
    try:
        _login(app_client, picker_username, picker_password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        app_client.post("/cosmetic/final-qc/pick", data={"csrf_token": csrf, "barcode": barcode})
        app_client.post("/cosmetic/advance", data={
            "csrf_token": csrf, "barcode": barcode, "final_qc_status": "fail",
            "failure_reason": "Hardware", "bucket_name": f"ITestPickBkt2{suffix}",
        }, follow_redirects=False)

        # Tag comes back around to Final QC after rework.
        _return_device_to_final_qc(barcode)

        html = app_client.get("/cosmetic/final_qc", follow_redirects=True).text
        # Scope to this device's own card — Final QC can legitimately list
        # other real tags too.
        card = html.split(f'href="/devices/{barcode}"', 1)[1][:1200]
        assert "Picked by" not in card
        assert 'class="btn btn-sm btn-outline-primary fqc-pick-btn"' in card

        # The SAME user who picked it before can pick it again — this is a
        # per-visit lock, not a permanent one.
        r_repick = app_client.post("/cosmetic/final-qc/pick", data={"csrf_token": csrf, "barcode": barcode})
        assert r_repick.status_code == 200, r_repick.text[:300]

        statuses = _fqc_workorder_statuses(barcode)
        assert statuses == "completed,pending"
    finally:
        _cleanup_device(barcode)
