"""/workid-status — each WorkID matched to its OWN Asset History movement,
not the device's overall latest one (2026-09-02 backfill):

Before this fix, movements_by_device kept only the single most-recent
StageMovement per device, and every WorkOrder row for that device showed
that SAME movement's Stage/Completed Date/Assigned Engineer — so a tag with
several historical WorkIDs (Cleaning, then Putty, then Dry Sanding) showed
identical values on all three rows, always the last one's. Each completed
WorkOrder is now matched to the StageMovement whose moved_at is nearest its
own completed_at, out of the device's FULL Asset History, so older WorkIDs
correctly show their own (earlier) Stage/Completed Date/Engineer.
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


def _seed_two_stage_history(barcode, work_id_1, work_id_2, username1, username2):
    """One device with two historical WorkIDs and two StageMovements:
    WorkID 1 closed when the device left cleaning (moved to putty) on an old
    date; WorkID 2 closed when it later left putty (moved to dry_sanding) on
    a later date. Each WorkOrder's own completed_at is stamped to match its
    own closing movement, mirroring how advance_stage actually does it.
    moved_by is deliberately a username with NO matching User row: every
    make_user()-created user shares the identical hardcoded full_name "IQC
    Test User" (tests/test_iqc_new_user.py), so a resolved display name
    couldn't distinguish the two rows anyway — the display-name lookup's
    fallback to the raw username (when no User row matches) is exactly what
    this test relies on to prove each row shows its OWN moved_by."""
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from datetime import datetime
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage, StageMovement
from models.work_order import WorkOrder

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.dry_sanding)
        db.add(dev)
        await db.flush()

        t1 = datetime.fromisoformat("2020-01-10T09:00:00")
        t2 = datetime.fromisoformat("2020-02-20T15:00:00")

        db.add(WorkOrder(work_id="{work_id_1}", device_id=dev.id, barcode="{barcode}",
                         stage="clean", assigned_role="cosmetic_manager",
                         assigned_username="{username1}", assigned_name="Wrong Assignee (WorkOrder-level)",
                         status="completed", completed_at=t1, created_by="itest"))
        db.add(StageMovement(device_id=dev.id, from_stage=DeviceStage.cleaning,
                             to_stage=DeviceStage.putty, moved_by="{username1}", moved_at=t1))

        db.add(WorkOrder(work_id="{work_id_2}", device_id=dev.id, barcode="{barcode}",
                         stage="putty", assigned_role="cosmetic_manager",
                         assigned_username="{username2}", assigned_name="Wrong Assignee (WorkOrder-level)",
                         status="completed", completed_at=t2, created_by="itest"))
        db.add(StageMovement(device_id=dev.id, from_stage=DeviceStage.putty,
                             to_stage=DeviceStage.dry_sanding, moved_by="{username2}", moved_at=t2))

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


def test_each_workid_shows_its_own_movement_not_the_devices_latest(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITWIDBF{suffix}"
    work_id_1 = f"WIDBF1{suffix}"
    work_id_2 = f"WIDBF2{suffix}"
    mover_username_1 = f"itest_bf1_{suffix}"
    mover_username_2 = f"itest_bf2_{suffix}"
    _seed_two_stage_history(barcode, work_id_1, work_id_2, mover_username_1, mover_username_2)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get(f"/workid-status?tag={barcode}", follow_redirects=True).text

        row1 = html.split(f'id="wo-{work_id_1}"', 1)[1].split("</tr>", 1)[0]
        row2 = html.split(f'id="wo-{work_id_2}"', 1)[1].split("</tr>", 1)[0]

        # WorkID 1 (closed when leaving Cleaning) must show Cleaning as its
        # Stage and its OWN mover as engineer — not WorkID 2's (Putty /
        # mover_username_2), and NOT the WorkOrder's own assigned_name
        # ("Wrong Assignee..."), confirming the source really is Asset
        # History, not the WorkOrder row.
        assert "Cleaning" in row1
        assert mover_username_1 in row1
        assert "Putty" not in row1
        assert mover_username_2 not in row1
        assert "Wrong Assignee" not in row1
        assert "10-01-2020" in row1  # Completed Date = its own movement's moved_at (2020-01-10)

        # WorkID 2 (closed when leaving Putty) must show its own values.
        assert "Putty" in row2
        assert mover_username_2 in row2
        assert "Cleaning" not in row2
        assert mover_username_1 not in row2
        assert "Wrong Assignee" not in row2
        assert "20-02-2020" in row2  # Completed Date = its own movement's moved_at (2020-02-20)
    finally:
        _cleanup_device(barcode)
