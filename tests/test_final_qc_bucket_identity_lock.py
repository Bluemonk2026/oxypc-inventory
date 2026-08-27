"""Final QC Fail form — Bucket Name identity lock (routers/cosmetic.py
advance_stage, Bucket.fail_reason/fail_engineer_*):

 - A bucket name's (failure reason, resolved engineer) pair is set by
   whichever device first fails into it.
 - Every later device failing into the SAME bucket name must match BOTH
   exactly, or the submission is rejected with:
   "You cant use same bucket with same reason for multiple Engineer Name.
   So change Bucket Name." — same reason + different engineer is rejected,
   and different reason + same engineer is rejected too.
 - A rejected submission leaves nothing half-applied: the device stays at
   Final QC, its bucket_id/failure_reason are unchanged.
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


def _bucket_and_device_state(barcode):
    out = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.bucket import Bucket

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        b = (await db.execute(select(Bucket).where(Bucket.id == dev.bucket_id))).scalar_one_or_none()
        print("device.current_stage=" + dev.current_stage.value)
        print("device.bucket_id=" + str(dev.bucket_id))
        print("device.fqc_failure_reason=" + str(dev.fqc_failure_reason))
        print("bucket.fail_reason=" + str(b.fail_reason if b else None))
        print("bucket.fail_engineer_username=" + str(b.fail_engineer_username if b else None))

asyncio.run(main())
""")
    return dict(l.split("=", 1) for l in out.splitlines() if "=" in l)


def _submit_fail(app_client, barcode, failure_reason, bucket_name):
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    return app_client.post("/cosmetic/advance", data={
        "csrf_token": csrf, "barcode": barcode, "final_qc_status": "fail",
        "failure_reason": failure_reason, "bucket_name": bucket_name,
    }, follow_redirects=False)


def test_first_fail_into_new_bucket_always_succeeds(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITLOCKA{suffix}"
    bucket_name = f"ITestLockA{suffix}"
    eng_username, _ = make_user("l1_engineer")

    _seed_device_at_final_qc(barcode)
    _seed_workorder(barcode, "l1", eng_username)
    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    try:
        r = _submit_fail(app_client, barcode, "Hardware", bucket_name)
        assert r.status_code == 302, r.text[:400]
        state = _bucket_and_device_state(barcode)
        assert state["bucket.fail_reason"] == "Hardware"
        assert state["bucket.fail_engineer_username"] == eng_username
    finally:
        _cleanup_device(barcode)


def test_same_reason_same_engineer_reuses_bucket_fine(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode_1 = f"ITLOCKB1{suffix}"
    barcode_2 = f"ITLOCKB2{suffix}"
    bucket_name = f"ITestLockB{suffix}"
    eng_username, _ = make_user("l1_engineer")

    _seed_device_at_final_qc(barcode_1)
    _seed_workorder(barcode_1, "l1", eng_username)
    _seed_device_at_final_qc(barcode_2)
    _seed_workorder(barcode_2, "l1", eng_username)

    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    try:
        r1 = _submit_fail(app_client, barcode_1, "Hardware", bucket_name)
        assert r1.status_code == 302, r1.text[:400]
        r2 = _submit_fail(app_client, barcode_2, "Hardware", bucket_name)
        assert r2.status_code == 302, r2.text[:400]

        state2 = _bucket_and_device_state(barcode_2)
        assert state2["device.current_stage"] == "final_qc_fail_hold"
        assert state2["bucket.fail_engineer_username"] == eng_username
    finally:
        _cleanup_device(barcode_1)
        _cleanup_device(barcode_2)


def test_same_reason_different_engineer_is_rejected(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode_1 = f"ITLOCKC1{suffix}"
    barcode_2 = f"ITLOCKC2{suffix}"
    bucket_name = f"ITestLockC{suffix}"
    eng_a, _ = make_user("l1_engineer")
    eng_b, _ = make_user("l1_engineer")

    _seed_device_at_final_qc(barcode_1)
    _seed_workorder(barcode_1, "l1", eng_a)
    _seed_device_at_final_qc(barcode_2)
    _seed_workorder(barcode_2, "l1", eng_b)

    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    try:
        r1 = _submit_fail(app_client, barcode_1, "Hardware", bucket_name)
        assert r1.status_code == 302, r1.text[:400]

        r2 = _submit_fail(app_client, barcode_2, "Hardware", bucket_name)
        assert r2.status_code == 400
        assert "You cant use same bucket with same reason for multiple Engineer Name" in r2.text
        assert "change Bucket Name" in r2.text

        # Nothing half-applied on the rejected device.
        state2 = _bucket_and_device_state(barcode_2)
        assert state2["device.current_stage"] == "final_qc"
        assert state2["device.bucket_id"] == "None"
        assert state2["device.fqc_failure_reason"] == "None"
    finally:
        _cleanup_device(barcode_1)
        _cleanup_device(barcode_2)


def test_different_reason_same_engineer_is_rejected(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode_1 = f"ITLOCKD1{suffix}"
    barcode_2 = f"ITLOCKD2{suffix}"
    bucket_name = f"ITestLockD{suffix}"
    eng_username, _ = make_user("qc_inspector")

    _seed_device_at_final_qc(barcode_1)
    _seed_workorder(barcode_1, "qc", eng_username)
    _seed_device_at_final_qc(barcode_2)
    # "comp" (Cosmetic's own source stage) with the SAME engineer — same
    # resolved engineer as barcode_1, but the reason differs (Cosmetic, not
    # Software), which alone must still be enough to reject.
    _seed_workorder(barcode_2, "comp", eng_username)

    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    try:
        r1 = _submit_fail(app_client, barcode_1, "Software", bucket_name)
        assert r1.status_code == 302, r1.text[:400]

        r2 = _submit_fail(app_client, barcode_2, "Cosmetic", bucket_name)
        assert r2.status_code == 400
        assert "You cant use same bucket with same reason for multiple Engineer Name" in r2.text
    finally:
        _cleanup_device(barcode_1)
        _cleanup_device(barcode_2)
