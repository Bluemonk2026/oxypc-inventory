"""/workid-status — Completed Date filter fix + Stage filter expansion
(2026-09-02):

Completed From/To previously filtered WorkOrder.completed_at at the SQL
level, but the Completed Date COLUMN (since the 2026-09-01 Asset History
change) shows the device's latest StageMovement.moved_at instead — a
different field, so the filter silently narrowed against a value nobody
could see, and rows outside [from, to] on the *displayed* date could still
appear ("not applying properly"). Both Completed Date and the renamed
"Stage" filter (was "Cosmetic Stage", now offers every DeviceStage, not just
the cosmetic-line subset) now filter the SAME Asset-History-sourced values
the Stage/Completed Date columns display.
"""
import pathlib
import subprocess
import sys
import uuid
from datetime import timedelta

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def _seed(barcode, work_id, from_stage, to_stage, moved_at_iso):
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
                     current_stage=DeviceStage.{to_stage})
        db.add(dev)
        await db.flush()
        db.add(WorkOrder(work_id="{work_id}", device_id=dev.id, barcode="{barcode}",
                         stage="clean", assigned_role="cosmetic_manager",
                         assigned_username="itest_cdf", assigned_name="ITest CDF",
                         status="pending", created_by="itest"))
        db.add(StageMovement(device_id=dev.id, from_stage=DeviceStage.{from_stage},
                             to_stage=DeviceStage.{to_stage}, moved_by="itest_cdf",
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


def test_completed_date_filter_matches_the_displayed_column(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITWIDCDF{suffix}"
    work_id = f"WIDCDF{suffix}"
    # Moved on a fixed, distant date — well outside "today".
    _seed(barcode, work_id, "iqc", "cleaning", "2020-01-15T10:00:00")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)

        # A range that INCLUDES the movement date must show the row.
        html_in = app_client.get(
            f"/workid-status?workid={work_id}&completed_from=2020-01-01&completed_to=2020-01-31",
            follow_redirects=True).text
        assert work_id in html_in

        # A range that EXCLUDES it must not show the row — checked via the
        # row's own id, not a bare "work_id in html" check, since the
        # WorkID search box always echoes back its own filter value
        # (value="{{ f_workid }}") regardless of what the table shows.
        html_out = app_client.get(
            f"/workid-status?workid={work_id}&completed_from=2021-01-01&completed_to=2021-01-31",
            follow_redirects=True).text
        assert f'id="wo-{work_id}"' not in html_out
    finally:
        _cleanup_device(barcode)


def test_stage_filter_matches_asset_history_from_value(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITWIDSTG{suffix}"
    work_id = f"WIDSTG{suffix}"
    # From=iqc, To=cleaning — Stage column shows "From" (iqc), not the
    # device's live current_stage (cleaning).
    _seed(barcode, work_id, "iqc", "cleaning", "2026-01-01T10:00:00")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)

        html_iqc = app_client.get(f"/workid-status?workid={work_id}&cosmetic_stage=iqc",
                                  follow_redirects=True).text
        assert work_id in html_iqc

        html_cleaning = app_client.get(f"/workid-status?workid={work_id}&cosmetic_stage=cleaning",
                                       follow_redirects=True).text
        assert f'id="wo-{work_id}"' not in html_cleaning
    finally:
        _cleanup_device(barcode)


def test_stage_dropdown_includes_non_cosmetic_stages(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/workid-status", follow_redirects=True).text
    assert ">Stage<" in html
    assert ">Cosmetic Stage<" not in html
    # "sold" and "iqc" are not in the cosmetic-line pipeline — must now be
    # offered as dropdown options.
    assert 'value="sold"' in html
    assert 'value="iqc"' in html
