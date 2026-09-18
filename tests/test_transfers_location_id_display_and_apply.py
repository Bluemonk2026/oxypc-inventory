"""New Transfer page (/transfers/new), 2026-09-18:

 - All four tabs' Location ID dropdown (shared `transfer_fields` macro in
   templates/transfers/form.html) showed "<unit_id> — <zone label>"; now
   shows only the unit_id.
 - Applying a Location ID from any tab updated Device.location_id but not
   the device's DeviceLocationLog history, so a tag that already had prior
   location history kept displaying its OLD Location ID everywhere else in
   the app (_build_location_map in routers/devices.py reads the device's
   LATEST DeviceLocationLog row first, Device.location_id only as a
   fallback when no log exists at all). Move Item (single device) and Move
   Lot / Move Bucket (bulk, via _move_devices_bulk) now both write a fresh
   DeviceLocationLog row too.
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


def _seed_device_with_prior_location(barcode):
    """A device already assigned to location A via a real DeviceLocationLog
    row (the pickup-placeback flow's own shape) — the scenario where the
    stale-display bug actually shows up, since a device with NO prior log
    at all would already work via the Device.location_id fallback."""
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.location import StorageLocation, DeviceLocationLog, LocationAction
from models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        locs = (await db.execute(select(StorageLocation).where(StorageLocation.is_active == True).limit(2))).scalars().all()
        assert len(locs) >= 2, "fixture DB needs at least 2 active StorageLocations"
        loc_a, loc_b = locs[0], locs[1]
        actor = (await db.execute(select(User).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.stock_in, location_id=loc_a.id)
        db.add(dev)
        await db.flush()
        db.add(DeviceLocationLog(device_id=dev.id, location_id=loc_a.id, action=LocationAction.assigned,
                                  actor_id=actor.id, actor_name=actor.full_name))
        await db.commit()
        print(f"{{dev.id}}|{{loc_a.id}}|{{loc_b.id}}")

asyncio.run(main())
""")


def _current_location_label(app_client, barcode):
    html = app_client.get(f"/devices/{barcode}", follow_redirects=True).text
    idx = html.find("Location ID")
    return html[idx:idx + 400] if idx != -1 else ""


def _cleanup(barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.location import DeviceLocationLog
from models.stock_transfer import StockTransfer
from models.work_order import WorkOrder

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for wo in (await db.execute(select(WorkOrder).where(WorkOrder.device_id == dev.id))).scalars().all():
                await db.delete(wo)
            for t in (await db.execute(select(StockTransfer).where(StockTransfer.device_id == dev.id))).scalars().all():
                await db.delete(t)
            for log in (await db.execute(select(DeviceLocationLog).where(DeviceLocationLog.device_id == dev.id))).scalars().all():
                await db.delete(log)
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
""")


def test_new_transfer_location_dropdown_shows_only_unit_id(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/transfers/new", follow_redirects=True).text
    assert 'id="device-location-id"' in html
    import re
    block = re.search(r'id="device-location-id"[^>]*>.*?</select>', html, re.S)
    assert block, "device tab's Location ID select not found"
    # Every rendered option is the bare unit_id — no " — <zone>" suffix, and
    # no zone label text leaking in from the old format.
    assert " — " not in block.group(0)


def test_move_item_tab_updates_location_even_with_prior_history(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITTRFLOC{suffix}"
    seeded = _seed_device_with_prior_location(barcode)
    device_id, loc_a_id, loc_b_id = seeded.split("|")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        engineer_username, _ = make_user("l1_engineer")

        engineer_id = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == "{engineer_username}"))).scalar_one()
        print(u.id)

asyncio.run(main())
""")

        r = app_client.post("/transfers/new", data={
            "csrf_token": csrf, "barcode": barcode, "transfer_type": "internal",
            "assigned_user_id": engineer_id, "to_location_id": loc_b_id,
        }, follow_redirects=False)
        assert r.status_code == 302, r.text

        unit_id_b, log_count = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select, func
from database import AsyncSessionLocal
from models.device import Device
from models.location import StorageLocation, DeviceLocationLog

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        assert str(dev.location_id) == "{loc_b_id}", f"Device.location_id not updated: {{dev.location_id}}"
        loc_b = (await db.execute(select(StorageLocation).where(StorageLocation.id == dev.location_id))).scalar_one()
        n = (await db.execute(select(func.count()).select_from(DeviceLocationLog).where(
            DeviceLocationLog.device_id == dev.id, DeviceLocationLog.location_id == dev.location_id))).scalar()
        print(f"{{loc_b.unit_id}}|{{n}}")

asyncio.run(main())
""").split("|")
        assert int(log_count) >= 1, "no DeviceLocationLog row written for the new location"

        label = _current_location_label(app_client, barcode)
        assert unit_id_b in label, f"Device Detail still shows the old location: {label!r}"
    finally:
        _cleanup(barcode)
