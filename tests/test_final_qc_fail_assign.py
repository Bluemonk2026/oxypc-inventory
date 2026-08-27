"""Final QC "Devices Failed" tab + Assign (2026-08-27 redesign):

 - The Assign button now opens the SAME "Assign Bucket" modal Production
   Manager's Repair Line uses (templates/lots/trc_production.html), backed
   by the SAME /buckets/{bucket_id}/assign endpoint (routers/buckets.py) —
   no more auto-resolved-by-failure-reason routing.
 - Submitting the modal with "L1/L2 Repair" selected requires an engineer
   and moves every tag in the bucket to L1/L2.
 - Submitting with "QC or Stress" moves tags to Stress Test (qc_check);
   with "Cosmetic Repair" moves tags to Cosmetic Received — an engineer is
   optional for both.
 - The devices failed table shows "recent L1/L2 Engineer" in each device's
   own header card (informational only, not tied to routing).
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


def _seed_workorder(barcode, stage_code, username):
    work_id = uuid.uuid4().hex[:12]
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.user import User
from models.work_order import WorkOrder

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        u = (await db.execute(select(User).where(User.username == "{username}"))).scalar_one()
        db.add(WorkOrder(work_id="{work_id}", device_id=dev.id, barcode="{barcode}",
                         stage="{stage_code}", assigned_role=u.role.value,
                         assigned_user_id=u.id, assigned_username=u.username,
                         assigned_name=u.full_name, status="completed", created_by="itest"))
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


def _bucket_id_and_state(barcode):
    out = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.work_order import WorkOrder

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        wo = (await db.execute(select(WorkOrder).where(WorkOrder.device_id == dev.id)
              .order_by(WorkOrder.assigned_at.desc()))).scalars().first()
        print("bucket_id=" + str(dev.bucket_id))
        print("stage=" + dev.current_stage.value)
        print("assigned_username=" + str(wo.assigned_username if wo else None))

asyncio.run(main())
""")
    return dict(l.split("=", 1) for l in out.splitlines() if "=" in l)


def _submit_fail(app_client, barcode, failure_reason, bucket_name):
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    r = app_client.post("/cosmetic/advance", data={
        "csrf_token": csrf, "barcode": barcode, "final_qc_status": "fail",
        "failure_reason": failure_reason, "bucket_name": bucket_name,
    }, follow_redirects=False)
    assert r.status_code == 302, r.text[:400]


def test_devices_failed_table_shows_assign_button_and_l1l2_engineer_panel(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITFQCTBL{suffix}"
    bucket_name = f"ITestTblBkt{suffix}"
    eng_username, _ = make_user("l1_engineer")

    _seed_device_at_final_qc(barcode)
    _seed_workorder(barcode, "l1", eng_username)
    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    try:
        _submit_fail(app_client, barcode, "Hardware", bucket_name)

        html = app_client.get("/cosmetic/final_qc", follow_redirects=True).text
        assert 'class="fqc-assign-bkt"' in html or "fqc-assign-bkt" in html
        assert "Move to Production" not in html
        assert "L1/L2 Engineer:" in html
    finally:
        _cleanup_device(barcode)


def test_assign_modal_l1l2_repair_requires_engineer_and_moves_to_l1(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITASGL1{suffix}"
    bucket_name = f"ITestAsgL1{suffix}"
    eng_username, _ = make_user("l1_engineer")

    _seed_device_at_final_qc(barcode)
    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    try:
        _submit_fail(app_client, barcode, "Hardware", bucket_name)
        info = _bucket_id_and_state(barcode)

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
        r = app_client.post(f"/buckets/{info['bucket_id']}/assign", data={
            "csrf_token": csrf, "department": "L1/L2 Repair", "assigned_user_id": eng_id,
        })
        assert r.status_code == 200, r.text[:400]
        assert r.json()["ok"] is True

        after = _bucket_id_and_state(barcode)
        assert after["stage"] == "l1"
        assert after["assigned_username"] == eng_username
    finally:
        _cleanup_device(barcode)


def test_assign_modal_qc_or_stress_moves_to_stress_test_engineer_optional(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITASGQC{suffix}"
    bucket_name = f"ITestAsgQC{suffix}"

    _seed_device_at_final_qc(barcode)
    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    try:
        _submit_fail(app_client, barcode, "Software", bucket_name)
        info = _bucket_id_and_state(barcode)

        r = app_client.post(f"/buckets/{info['bucket_id']}/assign", data={
            "csrf_token": csrf, "department": "Stress Test",
        })
        assert r.status_code == 200, r.text[:400]

        after = _bucket_id_and_state(barcode)
        assert after["stage"] == "qc_check"
        assert after["assigned_username"] == "None"
    finally:
        _cleanup_device(barcode)


def test_assign_modal_cosmetic_repair_moves_to_cosmetic_received(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITASGCOS{suffix}"
    bucket_name = f"ITestAsgCos{suffix}"

    _seed_device_at_final_qc(barcode)
    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    try:
        _submit_fail(app_client, barcode, "Cosmetic", bucket_name)
        info = _bucket_id_and_state(barcode)

        r = app_client.post(f"/buckets/{info['bucket_id']}/assign", data={
            "csrf_token": csrf, "department": "Cosmetic Repair",
        })
        assert r.status_code == 200, r.text[:400]

        after = _bucket_id_and_state(barcode)
        assert after["stage"] == "cosmetic_received"
    finally:
        _cleanup_device(barcode)


def test_assign_modal_moves_every_tag_in_the_bucket(app_client, make_user):  # noqa: F811
    """Multiple tags in one bucket — Assign acts on all of them at once."""
    suffix = uuid.uuid4().hex[:6]
    barcode_1 = f"ITASGMULTI1{suffix}"
    barcode_2 = f"ITASGMULTI2{suffix}"
    bucket_name = f"ITestAsgMulti{suffix}"

    _seed_device_at_final_qc(barcode_1)
    _seed_device_at_final_qc(barcode_2)
    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    try:
        _submit_fail(app_client, barcode_1, "Software", bucket_name)
        _submit_fail(app_client, barcode_2, "Hardware", bucket_name)
        info = _bucket_id_and_state(barcode_1)
        assert info["bucket_id"] == _bucket_id_and_state(barcode_2)["bucket_id"]

        r = app_client.post(f"/buckets/{info['bucket_id']}/assign", data={
            "csrf_token": csrf, "department": "Stress Test",
        })
        assert r.status_code == 200, r.text[:400]
        assert r.json()["assigned"] == 2

        assert _bucket_id_and_state(barcode_1)["stage"] == "qc_check"
        assert _bucket_id_and_state(barcode_2)["stage"] == "qc_check"
    finally:
        _cleanup_device(barcode_1)
        _cleanup_device(barcode_2)
