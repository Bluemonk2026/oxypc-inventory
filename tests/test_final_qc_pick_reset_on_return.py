"""Final QC re-visits (routers/cosmetic.py advance_stage, 2026-09-01):

The old "Pick This" claim button could get stuck showing "Picked by <name>"
for a tag that left Final QC through some path other than the normal
Pass/Fail submission (leaving a stale "pending" WorkOrder behind) and later
came back — nobody could re-pick it. That whole class of bug is retired:
there is no more claim step. Each time a tag is decided at Final QC (first
visit, or any later return-trip after rework), submitting the decision
creates its OWN completed "fqc" WorkID for whoever submitted it — visits
never block each other and there's no persistent "picked" state to get
stuck.
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
    actual routing back is exercised elsewhere; this test is only about
    what happens to WorkID attribution across visits."""
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
        dev.final_qc_status = None
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


def test_decision_creates_a_completed_workorder(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITPICKRST{suffix}"
    username, password = make_user("admin")
    _seed_device_at_final_qc(barcode)
    try:
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r_fail = app_client.post("/cosmetic/advance", data={
            "csrf_token": csrf, "barcode": barcode, "final_qc_status": "fail",
            "failure_reason": "Hardware", "bucket_name": f"ITestPickBkt{suffix}",
        }, follow_redirects=False)
        assert r_fail.status_code == 302, r_fail.text[:300]

        assert _fqc_workorder_statuses(barcode) == "completed"
    finally:
        _cleanup_device(barcode)


def test_second_visit_after_rework_gets_its_own_workorder(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITPICKRET{suffix}"
    username, password = make_user("admin")
    _seed_device_at_final_qc(barcode)
    try:
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        app_client.post("/cosmetic/advance", data={
            "csrf_token": csrf, "barcode": barcode, "final_qc_status": "fail",
            "failure_reason": "Hardware", "bucket_name": f"ITestPickBkt2{suffix}",
        }, follow_redirects=False)

        # Tag comes back around to Final QC after rework.
        _return_device_to_final_qc(barcode)

        # No "Pick This" state to block a second decision — the SAME user
        # (or anyone else permitted) can decide it again immediately.
        r_pass = app_client.post("/cosmetic/advance", data={
            "csrf_token": csrf, "barcode": barcode, "final_qc_status": "pass",
        }, follow_redirects=False)
        assert r_pass.status_code == 302, r_pass.text[:300]

        # Two visits, two independently completed WorkOrders — neither
        # blocked the other.
        assert _fqc_workorder_statuses(barcode) == "completed,completed"
    finally:
        _cleanup_device(barcode)
