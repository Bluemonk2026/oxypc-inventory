"""New Cosmetic Received / Cosmetic Completed stages, sandwiching the
existing Cleaning..Water Sanding line:

    Stress Test -> Cosmetic Received -> Cleaning -> ... -> Water Sanding
                 -> Cosmetic Completed -> Final QC

 - Stress Test's "Complete" button (/stress/{barcode}/complete-to-paint) now
   lands the device on Cosmetic Received, not Cleaning directly, and still
   records the WorkOrder(stage="clean") used for the "Assigned to" column.
 - /cosmetic/cosmetic_received and /cosmetic/cosmetic_completed render their
   own templates with the extra columns (Lot/Grade/Brand/Model/Aging/
   Assigned to/Assigned Date) and actions (Move to Cleaning / Move to Final
   QC / Fail, or Move to Final QC / Fail on Completed).
 - Fail from either new stage uses the same "assign to L1/L2 engineer"
   mechanism as Cleaning/Water Sanding.
 - cosmetic_manager can reach these pages (previously not in `allowed`).
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


_SEED_AT_QC_CHECK_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.qc_check)
        db.add(dev)
        await db.commit()

asyncio.run(main())
"""

_SEED_AT_WATER_SANDING_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.work_order import WorkOrder

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.water_sanding)
        db.add(dev)
        await db.flush()
        db.add(WorkOrder(work_id="ITWCC{suffix}", device_id=dev.id, barcode=dev.barcode,
                         stage="clean", assigned_name="Cosmetic Engineer", status="pending"))
        await db.commit()

asyncio.run(main())
"""

_CLEANUP_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device, StageMovement
from models.work_order import WorkOrder

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            wos = (await db.execute(select(WorkOrder).where(WorkOrder.device_id == dev.id))).scalars().all()
            for wo in wos:
                await db.delete(wo)
            movements = (await db.execute(select(StageMovement).where(
                StageMovement.device_id == dev.id))).scalars().all()
            for m in movements:
                await db.delete(m)
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
"""


def test_stress_complete_sends_device_to_cosmetic_received_not_cleaning(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITCRQC{suffix}"

    _run(_SEED_AT_QC_CHECK_SRC.format(root=ROOT, barcode=barcode))
    try:
        username, password = make_user("qc_inspector")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post(f"/stress/{barcode}/complete-to-paint",
                             data={"csrf_token": csrf}, follow_redirects=False)
        assert r.status_code == 302, r.text[:300]
        assert "Cosmetic+Received" in r.headers["location"]

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
        assert check == "cosmetic_received"
    finally:
        _run(_CLEANUP_SRC.format(root=ROOT, barcode=barcode))


def test_cosmetic_received_page_columns_and_move_to_cleaning(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITCRPG{suffix}"

    seed = f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.work_order import WorkOrder

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.cosmetic_received)
        db.add(dev)
        await db.flush()
        db.add(WorkOrder(work_id="ITWCR{suffix}", device_id=dev.id, barcode=dev.barcode,
                         stage="clean", assigned_name="Cosmetic Engineer", status="pending"))
        await db.commit()

asyncio.run(main())
"""
    _run(seed)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)

        html = app_client.get("/cosmetic/cosmetic_received", follow_redirects=True).text
        for header in ["Tag Number", "L1/L2 Engineer", "Lot", "Grade", "Brand", "Model",
                       "Aging", "Assigned to", "Assigned Date", "Action"]:
            assert f"<th>{header}</th>" in html, header

        row = html.split(barcode, 1)[1].split("</tr>", 1)[0]
        assert "Cosmetic Engineer" in row
        assert "Move to Cleaning" in row
        assert "Move to Final QC" in row
        assert "openFailModal(" in row

        csrf = app_client.cookies.get("csrf_token") or "dummy"
        r = app_client.post("/cosmetic/advance", data={"csrf_token": csrf, "barcode": barcode},
                             follow_redirects=False)
        assert r.status_code == 302
        assert "cleaning" in r.headers["location"]

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
        assert check == "cleaning"
    finally:
        _run(_CLEANUP_SRC.format(root=ROOT, barcode=barcode))


def test_water_sanding_advances_to_cosmetic_completed_then_final_qc(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITCC{suffix}"

    _run(_SEED_AT_WATER_SANDING_SRC.format(root=ROOT, barcode=barcode, suffix=suffix))
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post("/cosmetic/advance", data={"csrf_token": csrf, "barcode": barcode},
                             follow_redirects=False)
        assert r.status_code == 302
        assert "cosmetic_completed" in r.headers["location"]

        html = app_client.get("/cosmetic/cosmetic_completed", follow_redirects=True).text
        assert "<th>Cosmetic Stage</th>" in html
        row = html.split(barcode, 1)[1].split("</tr>", 1)[0]
        assert "Cosmetic Completed" in row
        assert "Cosmetic Engineer" in row
        assert "Move to Final QC" in row
        assert "openFailModal(" in row

        r2 = app_client.post("/cosmetic/advance", data={"csrf_token": csrf, "barcode": barcode},
                              follow_redirects=False)
        assert r2.status_code == 302
        assert "final_qc" in r2.headers["location"]

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
        assert check == "final_qc"
    finally:
        _run(_CLEANUP_SRC.format(root=ROOT, barcode=barcode))


def test_fail_from_cosmetic_received_assigns_l1l2_engineer(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITCRFAIL{suffix}"

    _run(_SEED_AT_QC_CHECK_SRC.format(root=ROOT, barcode=barcode))
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device, DeviceStage

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        dev.current_stage = DeviceStage.cosmetic_received
        await db.commit()

asyncio.run(main())
""")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        eng_row = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.user import User, UserRole

async def main():
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(
            User.role == UserRole.l1_engineer, User.status == True))).scalars().first()
        print(u.id if u else "")

asyncio.run(main())
""")
        assert eng_row, "need at least one active l1_engineer in the DB for this test"

        r = app_client.post(f"/cosmetic/{barcode}/fail", data={
            "csrf_token": csrf, "engineer_user_id": eng_row, "notes": "cosmetic defect at receiving",
        }, follow_redirects=False)
        assert r.status_code == 302, r.text[:400]

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
        print(dev.repair_notes)

asyncio.run(main())
""")
        lines = check.splitlines()
        assert lines[0] == "l1"
        assert "Cosmetic Received Failed" in lines[1]
    finally:
        _run(_CLEANUP_SRC.format(root=ROOT, barcode=barcode))


def test_cosmetic_manager_role_can_access_cosmetic_pages(app_client, make_user):  # noqa: F811
    username, password = make_user("cosmetic_manager")
    _login(app_client, username, password)

    r = app_client.get("/cosmetic/cosmetic_received", follow_redirects=False)
    assert r.status_code == 200, r.text[:300]
    r2 = app_client.get("/cosmetic/cleaning", follow_redirects=False)
    assert r2.status_code == 200, r2.text[:300]
    r3 = app_client.get("/cosmetic/cosmetic_completed", follow_redirects=False)
    assert r3.status_code == 200, r3.text[:300]


def test_new_stages_are_in_the_nav_tab_bar_at_the_right_position():
    src = open(pathlib.Path(ROOT) / "routers" / "cosmetic.py", encoding="utf-8").read()
    pipeline_block = src.split("COSMETIC_PIPELINE = [", 1)[1].split("]", 1)[0]
    assert pipeline_block.index("cosmetic_received") < pipeline_block.index("cleaning")
    assert pipeline_block.index("water_sanding") < pipeline_block.index("cosmetic_completed")
