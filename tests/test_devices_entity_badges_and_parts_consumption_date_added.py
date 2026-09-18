"""2026-09-18:

/devices ("All Tags Inventory") — the per-entity summary badges above the
table are now clickable, filtering the table to that entity (single-value,
click again to clear). "Unassigned" (the badge for a null Device.entity) is
special-cased server-side in _device_search_filters, since a literal
`Device.entity == 'Unassigned'` would never match a NULL column.

Parts Master's Parts Consumption tab:
 - New "Date Added" column, before "Part Name Used" — the timestamp the
   engineer hit Verify on Device Detail's Parts Consumed table
   (PartRequest.actioned_at, set in routers/part_requests.py::validate_receiving).
 - The page's global Added From/To filter now also narrows this tab, against
   that same per-row timestamp.
 - The table itself is now a Global Table (initGlobalTable).
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


def _cleanup_device(barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
""")


def test_devices_page_renders_clickable_entity_badges(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/devices", follow_redirects=True).text
    assert 'class="entity-filter-badge' in html or "entity-filter-badge" in html
    assert 'data-entity="' in html


def test_devices_data_unassigned_entity_filter_matches_null(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITENTNULL{suffix}"
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
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.stock_in, entity=None)
        db.add(dev)
        await db.commit()

asyncio.run(main())
""")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        r = app_client.get("/devices/data?start=0&length=500&entity=Unassigned")
        assert r.status_code == 200
        body = r.json()
        assert any(barcode in str(row) for row in body["data"]), \
            "Unassigned badge filter should match a device with a null entity"
    finally:
        _cleanup_device(barcode)


def test_devices_data_named_entity_filter_still_exact_match(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITENTNAMED{suffix}"
    entity_name = f"ITestEntity{suffix}"
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
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.stock_in, entity="{entity_name}")
        db.add(dev)
        await db.commit()

asyncio.run(main())
""")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        r = app_client.get(f"/devices/data?start=0&length=500&entity={entity_name}")
        assert r.status_code == 200
        body = r.json()
        assert any(barcode in str(row) for row in body["data"])
        # A different real entity must not also match.
        r2 = app_client.get("/devices/data?start=0&length=500&entity=SomeOtherEntity")
        body2 = r2.json()
        assert not any(barcode in str(row) for row in body2["data"])
    finally:
        _cleanup_device(barcode)


def _seed_verified_part_request(barcode, part_code, actioned_at_iso):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from datetime import datetime
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.spare_parts import SparePart
from models.part_request import PartRequest

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.l1)
        db.add(dev)
        sp = SparePart(part_code="{part_code}", name="ITest Screen", category="Screen",
                       unit_price=750, qty_in_stock=10)
        db.add(sp)
        await db.flush()
        db.add(PartRequest(device_id=dev.id, barcode="{barcode}", part_id=sp.id, part_name=sp.name,
                           request_type="replace", status="received", qty_handed_over=1,
                           actioned_at=datetime.fromisoformat("{actioned_at_iso}")))
        await db.commit()
        print(str(dev.id))

asyncio.run(main())
""")


def _cleanup_part_consumption(barcode, part_code):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.spare_parts import SparePart
from models.part_request import PartRequest

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for pr in (await db.execute(select(PartRequest).where(
                    PartRequest.device_id == dev.id))).scalars().all():
                await db.delete(pr)
            await db.delete(dev)
        sp = (await db.execute(select(SparePart).where(SparePart.part_code == "{part_code}"))).scalar_one_or_none()
        if sp:
            await db.delete(sp)
        await db.commit()

asyncio.run(main())
""")


def test_parts_consumption_date_added_column_shows_actioned_at(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    barcode = f"ITPCDATE{suffix}"
    part_code = f"ITPCDPART{suffix}"
    _seed_verified_part_request(barcode, part_code, "2026-06-15T10:00:00")
    try:
        username, password = make_user("spare_parts_manager")
        _login(app_client, username, password)
        html = app_client.get("/spare-parts", follow_redirects=True).text
        section = html.split('id="partsConsumptionTab"', 1)[1].split("</table>", 1)[0]
        assert "15-06-2026" in section
    finally:
        _cleanup_part_consumption(barcode, part_code)


def test_parts_consumption_added_date_filter_excludes_out_of_range_row(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    barcode = f"ITPCFILT{suffix}"
    part_code = f"ITPCFPART{suffix}"
    _seed_verified_part_request(barcode, part_code, "2026-01-10T10:00:00")
    try:
        username, password = make_user("spare_parts_manager")
        _login(app_client, username, password)

        # In range: row present.
        html_in = app_client.get(
            "/spare-parts?added_from=2026-01-01&added_to=2026-01-31", follow_redirects=True).text
        assert barcode in html_in.split('id="partsConsumptionTab"', 1)[1].split("</table>", 1)[0]

        # Out of range: row absent.
        html_out = app_client.get(
            "/spare-parts?added_from=2026-03-01&added_to=2026-03-31", follow_redirects=True).text
        assert barcode not in html_out.split('id="partsConsumptionTab"', 1)[1].split("</table>", 1)[0]
    finally:
        _cleanup_part_consumption(barcode, part_code)
