"""/workid-status — backfilled rows for StageMovements with NO WorkOrder
(2026-09-02):

Reported: tags that completed Cleaning / Water Sanding on specific dates
were still invisible on /workid-status even after Stage/Completed
Date/Assigned Engineer started reading Asset History — because the page
only ever showed one row per WorkOrder, and a WorkOrder is only created
when advance_stage assigns an engineer. Most stage transitions (bulk moves,
IQC intake, any advance_stage call with no engineer) never create one, so
those StageMovements had no row to appear on at all, regardless of what
those rows displayed.

Fix: when the request is bounded (a specific tag, or a Stage narrowed by at
least one Completed Date bound), StageMovements with no matching WorkOrder
are added as their own rows (WorkID column shows "— No WorkID —"). An
unfiltered page load does NOT run this — production has 131k+ StageMovements
against under 5k WorkOrders ever created, so an unbounded query would be
enormous.
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


def _seed_movement_with_no_work_order(barcode, mover_username, moved_at_iso, from_stage, to_stage):
    """A device with exactly one StageMovement and NO WorkOrder at all —
    mirrors a bulk/no-engineer advance_stage call."""
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from datetime import datetime
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage, StageMovement

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.{to_stage})
        db.add(dev)
        await db.flush()
        db.add(StageMovement(device_id=dev.id, from_stage=DeviceStage.{from_stage},
                             to_stage=DeviceStage.{to_stage}, moved_by="{mover_username}",
                             moved_at=datetime.fromisoformat("{moved_at_iso}")))
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


def test_movement_with_no_workorder_is_invisible_unfiltered_but_shows_via_tag_search(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITWIDNOWO{suffix}"
    mover = f"itest_nowo_{suffix}"
    _seed_movement_with_no_work_order(barcode, mover, "2026-08-29T11:00:00", "cleaning", "putty")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)

        # Searching by tag surfaces it even with no WorkOrder.
        html = app_client.get(f"/workid-status?tag={barcode}", follow_redirects=True).text
        assert barcode in html
        assert "Cleaning" in html
        assert "29-08-2026" in html
        assert mover in html
        assert "No WorkID" in html
    finally:
        _cleanup_device(barcode)


def test_movement_with_no_workorder_shows_via_stage_and_date_filter(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITWIDNOWO2{suffix}"
    mover = f"itest_nowo2_{suffix}"
    _seed_movement_with_no_work_order(barcode, mover, "2026-08-31T09:30:00", "water_sanding", "cosmetic_completed")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)

        html = app_client.get(
            "/workid-status?cosmetic_stage=water_sanding&completed_from=2026-08-31&completed_to=2026-08-31",
            follow_redirects=True).text
        assert barcode in html
        assert "Water Sanding" in html
        assert "31-08-2026" in html
    finally:
        _cleanup_device(barcode)


def test_unfiltered_page_load_does_not_backfill_movement_only_rows(app_client, make_user):  # noqa: F811
    """The expensive backfill query must only run when bounded — confirmed
    indirectly: a tag seeded with no WorkOrder must NOT appear on an
    unfiltered page load (only a tag/stage+date-bounded one)."""
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITWIDNOWO3{suffix}"
    mover = f"itest_nowo3_{suffix}"
    _seed_movement_with_no_work_order(barcode, mover, "2026-08-30T10:00:00", "putty", "dry_sanding")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get("/workid-status", follow_redirects=True).text
        assert barcode not in html
    finally:
        _cleanup_device(barcode)
