"""Assign Bucket modal, Final QC Fail (Bucket) table (Production Manager /
Repair Line): "QC or Stress" (was "Stress Test") and "Cosmetic Repair" no
longer require an engineer — they just move the bucket's tags to a stage.
"L1/L2 Repair" (and the Bucket Allocation tab's own Assign flow, which still
always sends an engineer) is unchanged.

routers/buckets.py DEPT_TO_STAGE: "Cosmetic Repair" now targets
cosmetic_received (the cosmetic pipeline's holding stage) instead of
cleaning directly.
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


def _seed_bucket_with_device(bucket_no, barcode):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.bucket import Bucket

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        bucket = Bucket(bucket_number="{bucket_no}", name="ITest Bucket")
        db.add(bucket)
        await db.flush()
        d = Device(barcode="{barcode}", lot_id=lot.id, brand="X", model="Y",
                   current_stage=DeviceStage.final_qc_fail_hold, bucket_id=bucket.id)
        db.add(d)
        await db.commit()
        print(bucket.id)

asyncio.run(main())
""")


def _cleanup(barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device, StageMovement
from models.work_order import WorkOrder
from models.stock_transfer import StockTransfer

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for wo in (await db.execute(select(WorkOrder).where(WorkOrder.device_id == dev.id))).scalars().all():
                await db.delete(wo)
            for m in (await db.execute(select(StageMovement).where(
                    StageMovement.device_id == dev.id))).scalars().all():
                await db.delete(m)
            for t in (await db.execute(select(StockTransfer).where(
                    StockTransfer.device_id == dev.id))).scalars().all():
                await db.delete(t)
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
""")


def test_cosmetic_repair_with_no_engineer_moves_to_cosmetic_received(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITBKTCOSM{suffix}"
    bucket_id = _seed_bucket_with_device(f"BKTCOSM{suffix}", barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post(f"/buckets/{bucket_id}/assign", data={
            "csrf_token": csrf, "department": "Cosmetic Repair",
        })
        assert r.status_code == 200, r.text[:300]

        check = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select, func
from database import AsyncSessionLocal
from models.device import Device
from models.work_order import WorkOrder

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        n = (await db.execute(select(func.count(WorkOrder.id)).where(
            WorkOrder.device_id == dev.id))).scalar_one()
        print(dev.current_stage.value)
        print(n)

asyncio.run(main())
""")
        lines = check.splitlines()
        assert lines[0] == "cosmetic_received"
        assert lines[1] == "0"  # no engineer -> no WorkOrder
    finally:
        _cleanup(barcode)


def test_qc_or_stress_with_no_engineer_moves_to_qc_check(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITBKTSTRESS{suffix}"
    bucket_id = _seed_bucket_with_device(f"BKTSTRESS{suffix}", barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post(f"/buckets/{bucket_id}/assign", data={
            "csrf_token": csrf, "department": "Stress Test",
        })
        assert r.status_code == 200, r.text[:300]

        check = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        print(dev.current_stage.value)

asyncio.run(main())
""")
        assert check.strip() == "qc_check"
    finally:
        _cleanup(barcode)


def test_l1l2_repair_with_engineer_still_creates_workid(app_client, make_user):  # noqa: F811
    """Backward-compat: the Bucket Allocation tab's own Assign flow always
    sends an engineer for every radio, and L1/L2 Repair keeps requiring one
    even from the Final QC Fail Bucket modal — unchanged behavior."""
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITBKTL1{suffix}"
    bucket_id = _seed_bucket_with_device(f"BKTL1{suffix}", barcode)
    try:
        username, password = make_user("admin")
        eng_username, _ = make_user("l1_engineer")
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

        r = app_client.post(f"/buckets/{bucket_id}/assign", data={
            "csrf_token": csrf, "department": "L1/L2 Repair", "assigned_user_id": eng_id,
        })
        assert r.status_code == 200, r.text[:300]

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
        wo = (await db.execute(select(WorkOrder).where(WorkOrder.device_id == dev.id))).scalar_one()
        print(dev.current_stage.value)
        print(wo.assigned_username)

asyncio.run(main())
""")
        lines = check.splitlines()
        assert lines[0] == "l1"
        assert lines[1] == eng_username
    finally:
        _cleanup(barcode)


def test_assign_bucket_modal_template_reflects_new_label_and_context_flag():
    src = open(pathlib.Path(ROOT) / "templates" / "lots" / "trc_production.html", encoding="utf-8").read()
    assert '<label class="form-check-label" for="asgLevelStress">QC or Stress</label>' in src
    assert 'id="asgBktContext"' in src
    assert 'id="asgEngineerGroup"' in src
    # Bucket Allocation tab's own trigger clears the context flag; the Final
    # QC Fail Bucket trigger sets it to "fqc_fail".
    assert "document.getElementById('asgBktContext').value = '';" in src
    assert "document.getElementById('asgBktContext').value = 'fqc_fail';" in src
