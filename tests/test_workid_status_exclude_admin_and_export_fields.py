"""/workid-status — "Exclude Admin" filter + narrowed CSV export (2026-09-02):

- New "Exclude Admin" checkbox (exclude_admin query param) drops rows whose
  engineer resolves to an admin-role User, checked by the underlying
  username (StageMovement.moved_by / WorkOrder.assigned_username), not a
  string match on the rendered display name.
- CSV export columns changed to exactly: Tag Number, Lot Number, Make,
  Model, Engineer Name, Stage, Assigned Date, Completed Date. Lot Number is
  new — Device.lot_id -> Lot.lot_number, looked up once for every device in
  the filtered item list.
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


def _seed_movement(barcode, mover_username, moved_at_iso, from_stage="cleaning", to_stage="putty"):
    return _run(f"""
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
        print(lot.lot_number)

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


def test_exclude_admin_drops_rows_moved_by_an_admin_user(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITWIDEXA{suffix}"
    admin_username, admin_password = make_user("admin")
    _seed_movement(barcode, admin_username, "2026-08-20T10:00:00")
    try:
        _login(app_client, admin_username, admin_password)

        # Without the checkbox: visible. Checked via the device-link marker,
        # not a bare "barcode in html" — the Search Tag Number input always
        # echoes the tag filter's own value regardless of what the table shows.
        row_marker = f'/devices/{barcode}"'
        html_without = app_client.get(f"/workid-status?tag={barcode}", follow_redirects=True).text
        assert row_marker in html_without

        # With the checkbox: excluded, since the mover is an admin-role user.
        html_with = app_client.get(f"/workid-status?tag={barcode}&exclude_admin=1", follow_redirects=True).text
        assert row_marker not in html_with
    finally:
        _cleanup_device(barcode)


def test_exclude_admin_keeps_rows_moved_by_a_non_admin_user(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITWIDEXB{suffix}"
    mover_username, _ = make_user("cosmetic_cleaning")
    admin_username, admin_password = make_user("admin")
    _seed_movement(barcode, mover_username, "2026-08-20T11:00:00")
    try:
        _login(app_client, admin_username, admin_password)
        html = app_client.get(f"/workid-status?tag={barcode}&exclude_admin=1", follow_redirects=True).text
        assert barcode in html
    finally:
        _cleanup_device(barcode)


def test_export_columns_match_the_requested_set(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITWIDEXP{suffix}"
    mover_username, _ = make_user("cosmetic_cleaning")
    out = _seed_movement(barcode, mover_username, "2026-08-21T12:00:00")
    lot_number = out.strip().splitlines()[-1]
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)

        r = app_client.get(f"/workid-status/export?tag={barcode}", follow_redirects=True)
        assert r.status_code == 200
        lines = [ln for ln in r.text.splitlines() if ln.strip()]
        header = lines[0].lstrip("﻿")  # utf-8-sig BOM, by design (Excel compat)
        assert header == "Tag Number,Lot Number,Make,Model,Engineer Name,Stage,Assigned Date,Completed Date"
        assert "WorkID" not in header
        assert "Aging" not in header
        assert "Notes" not in header
        assert "Final QC" not in header

        assert len(lines) == 2
        row = lines[1]
        assert barcode in row
        assert lot_number in row
        assert "ITestBrand" in row
        assert "ITestModel" in row
        assert "Cleaning" in row
    finally:
        _cleanup_device(barcode)


def test_exclude_admin_param_threaded_through_export_link(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/workid-status?exclude_admin=1", follow_redirects=True).text
    assert "exclude_admin=1" in html
    assert 'id="excludeAdminChk"' in html
    assert "checked" in html.split('id="excludeAdminChk"', 1)[1].split(">", 1)[0]
