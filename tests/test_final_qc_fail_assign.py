"""Final QC "Devices Failed" tab + Assign (routers/cosmetic.py):

 - Submitting a Final QC Fail resolves an engineer from this tag's own most
   recent WorkOrder at the stage the failure reason implies (Hardware ->
   L1/L2 "l1", Software -> Stress Test "qc", Cosmetic -> Cosmetic Completed
   "comp") and stores it on the bucket (Bucket.fail_engineer_*) — overwritten
   by whichever device fails into the bucket most recently.
 - The Devices Failed table shows that name in a new "Engineer Name" column;
   its Action button is relabelled "Assign" (was "Move to Production").
 - Assign routes the WHOLE bucket to the page its (single) failure reason
   implies, to the stored engineer, each tag getting a fresh WorkID — and
   refuses with a clear error if no engineer was resolved, the engineer is
   no longer active, or (Hardware/Software only) their role no longer
   matches.
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


def _get_bucket_and_device(barcode):
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
        print("bucket.id=" + str(b.id if b else None))
        print("bucket.fail_engineer_name=" + str(b.fail_engineer_name if b else None))
        print("bucket.fail_engineer_username=" + str(b.fail_engineer_username if b else None))

asyncio.run(main())
""")
    return dict(l.split("=", 1) for l in out.splitlines() if "=" in l)


def _set_user_status(username, active):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == "{username}"))).scalar_one()
        u.status = {active}
        await db.commit()

asyncio.run(main())
""")


def _submit_fail(app_client, barcode, failure_reason, bucket_name):
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    r = app_client.post("/cosmetic/advance", data={
        "csrf_token": csrf, "barcode": barcode, "final_qc_status": "fail",
        "failure_reason": failure_reason, "bucket_name": bucket_name,
    }, follow_redirects=False)
    assert r.status_code == 302, r.text[:500]


def test_hardware_fail_resolves_l1l2_engineer_onto_bucket(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITFQCHW{suffix}"
    bucket_name = f"ITestHWBkt{suffix}"
    eng_username, _ = make_user("l1_engineer")

    _seed_device_at_final_qc(barcode)
    _seed_workorder(barcode, "l1", eng_username)

    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    _submit_fail(app_client, barcode, "Hardware", bucket_name)

    info = _get_bucket_and_device(barcode)
    assert info["bucket.fail_engineer_username"] == eng_username


def test_software_fail_resolves_stress_test_engineer_onto_bucket(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITFQCSW{suffix}"
    bucket_name = f"ITestSWBkt{suffix}"
    eng_username, _ = make_user("qc_inspector")

    _seed_device_at_final_qc(barcode)
    _seed_workorder(barcode, "qc", eng_username)

    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    _submit_fail(app_client, barcode, "Software", bucket_name)

    info = _get_bucket_and_device(barcode)
    assert info["bucket.fail_engineer_username"] == eng_username


def test_cosmetic_fail_resolves_cosmetic_completed_engineer_onto_bucket(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITFQCCOS{suffix}"
    bucket_name = f"ITestCosBkt{suffix}"
    eng_username, _ = make_user("cosmetic_manager")

    _seed_device_at_final_qc(barcode)
    _seed_workorder(barcode, "comp", eng_username)

    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    _submit_fail(app_client, barcode, "Cosmetic", bucket_name)

    info = _get_bucket_and_device(barcode)
    assert info["bucket.fail_engineer_username"] == eng_username


def test_devices_failed_table_shows_engineer_name_and_assign_button(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITFQCTBL{suffix}"
    bucket_name = f"ITestTblBkt{suffix}"
    eng_username, _ = make_user("l1_engineer")

    _seed_device_at_final_qc(barcode)
    _seed_workorder(barcode, "l1", eng_username)

    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    _submit_fail(app_client, barcode, "Hardware", bucket_name)

    info = _get_bucket_and_device(barcode)
    expected_name = info["bucket.fail_engineer_name"]

    html = app_client.get("/cosmetic/final_qc", follow_redirects=True).text
    assert "Engineer Name" in html
    assert ">Assign<" in html
    assert "Move to Production" not in html
    row = html.split(bucket_name, 1)[1].split("</tr>", 1)[0]
    assert expected_name in row


def test_assign_moves_hardware_bucket_to_l1_with_fresh_workorder(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITASGHW{suffix}"
    bucket_name = f"ITestAsgHW{suffix}"
    eng_username, _ = make_user("l1_engineer")

    _seed_device_at_final_qc(barcode)
    _seed_workorder(barcode, "l1", eng_username)

    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    _submit_fail(app_client, barcode, "Hardware", bucket_name)

    info = _get_bucket_and_device(barcode)
    bucket_id = info["bucket.id"]
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    r = app_client.post(f"/cosmetic/final-qc/move-to-production/{bucket_id}", data={"csrf_token": csrf})
    assert r.status_code == 200, r.text[:500]
    body = r.json()
    assert body["ok"] is True
    assert body["moved"] == 1

    after = _get_bucket_and_device(barcode)
    assert after["device.current_stage"] == "l1"

    wo_stage = _run(f"""
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
            WorkOrder.device_id == dev.id, WorkOrder.stage == "l1",
            WorkOrder.assigned_username == "{eng_username}"))).scalars().all()
        print(len(wos))

asyncio.run(main())
""")
    assert wo_stage == "2", "the original history WorkOrder plus the fresh one Assign creates"


def test_assign_moves_software_bucket_to_stress_test(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITASGSW{suffix}"
    bucket_name = f"ITestAsgSW{suffix}"
    eng_username, _ = make_user("qc_inspector")

    _seed_device_at_final_qc(barcode)
    _seed_workorder(barcode, "qc", eng_username)

    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    _submit_fail(app_client, barcode, "Software", bucket_name)

    info = _get_bucket_and_device(barcode)
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    r = app_client.post(f"/cosmetic/final-qc/move-to-production/{info['bucket.id']}",
                        data={"csrf_token": csrf})
    assert r.status_code == 200, r.text[:500]

    after = _get_bucket_and_device(barcode)
    assert after["device.current_stage"] == "qc_check"


def test_assign_moves_cosmetic_bucket_to_cosmetic_received(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITASGCOS{suffix}"
    bucket_name = f"ITestAsgCos{suffix}"
    eng_username, _ = make_user("cosmetic_manager")

    _seed_device_at_final_qc(barcode)
    _seed_workorder(barcode, "comp", eng_username)

    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    _submit_fail(app_client, barcode, "Cosmetic", bucket_name)

    info = _get_bucket_and_device(barcode)
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    r = app_client.post(f"/cosmetic/final-qc/move-to-production/{info['bucket.id']}",
                        data={"csrf_token": csrf})
    assert r.status_code == 200, r.text[:500]

    after = _get_bucket_and_device(barcode)
    assert after["device.current_stage"] == "cosmetic_received"


def test_assign_blocked_when_no_engineer_resolved(app_client, make_user):  # noqa: F811
    # No WorkOrder history at all for this tag at "l1" -> nothing to resolve.
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITASGNONE{suffix}"
    bucket_name = f"ITestAsgNone{suffix}"

    _seed_device_at_final_qc(barcode)

    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    _submit_fail(app_client, barcode, "Hardware", bucket_name)

    info = _get_bucket_and_device(barcode)
    assert info["bucket.fail_engineer_username"] == "None"
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    r = app_client.post(f"/cosmetic/final-qc/move-to-production/{info['bucket.id']}",
                        data={"csrf_token": csrf})
    # No Accept: application/json header on this plain form POST, so the
    # app's global HTTPException handler renders an HTML error page (see
    # main.py http_exception_handler) rather than a JSON body — check the
    # rendered text, not r.json(), matching every other 400-path test in
    # this suite (e.g. test_move_without_engineer_is_rejected).
    assert r.status_code == 400
    assert "No engineer" in r.text


def test_assign_blocked_when_resolved_engineer_now_inactive(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITASGINACT{suffix}"
    bucket_name = f"ITestAsgInact{suffix}"
    eng_username, _ = make_user("l1_engineer")

    _seed_device_at_final_qc(barcode)
    _seed_workorder(barcode, "l1", eng_username)

    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    _submit_fail(app_client, barcode, "Hardware", bucket_name)

    _set_user_status(eng_username, False)
    try:
        info = _get_bucket_and_device(barcode)
        csrf = app_client.cookies.get("csrf_token") or "dummy"
        r = app_client.post(f"/cosmetic/final-qc/move-to-production/{info['bucket.id']}",
                            data={"csrf_token": csrf})
        assert r.status_code == 400
        assert "no longer an active user" in r.text
    finally:
        _set_user_status(eng_username, True)


def test_assign_blocked_when_engineer_role_no_longer_eligible(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITASGROLE{suffix}"
    bucket_name = f"ITestAsgRole{suffix}"
    eng_username, _ = make_user("l1_engineer")

    _seed_device_at_final_qc(barcode)
    _seed_workorder(barcode, "l1", eng_username)

    admin_username, admin_password = make_user("admin")
    _login(app_client, admin_username, admin_password)
    _submit_fail(app_client, barcode, "Hardware", bucket_name)

    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == "{eng_username}"))).scalar_one()
        u.role = "sales"
        await db.commit()

asyncio.run(main())
""")
    info = _get_bucket_and_device(barcode)
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    r = app_client.post(f"/cosmetic/final-qc/move-to-production/{info['bucket.id']}",
                        data={"csrf_token": csrf})
    assert r.status_code == 400
    assert "no longer eligible" in r.text
