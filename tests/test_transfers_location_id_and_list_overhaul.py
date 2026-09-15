"""Transfers — 2026-09-15:

- /transfers/new: a "Location ID" dropdown (to_location_id) added after
  Transfer Date on every tab (shared templates/transfers/form.html macro) —
  the column already existed on stock_transfers but every POST handler
  hardcoded to_location_id=None; now persisted. "Move Bucket" tab hidden
  (d-none on the nav button) per request, not deleted.
- /transfers (list): Global Table applied; Location ID column added before
  Type; From/To/Dept./Quantity columns hidden (d-none, not removed); Lot
  column now live-joins Device -> Lot instead of trusting the denormalized
  StockTransfer.lot_number snapshot, which stays "—" forever if the lookup
  missed at transfer-creation time; new filters (Transfer by, Date Range,
  Location ID) plus a CSV Export button sharing the same filter helper as
  the page so export can't drift from what's on screen.
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


def _seed_location(unit_id):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from database import AsyncSessionLocal
from models.location import StorageLocation, ZoneType, UnitType

async def main():
    async with AsyncSessionLocal() as db:
        loc = StorageLocation(zone=ZoneType.workshop, unit_type=UnitType.rack, unit_id="{unit_id}")
        db.add(loc)
        await db.commit()
        print(loc.id)

asyncio.run(main())
""")


def _seed_transfer_with_stale_lot_snapshot(barcode, unit_id, location_id, lot_number_live):
    """A device whose real (live) lot has lot_number_live, but whose
    StockTransfer row was inserted with a WRONG/blank snapshot — mirrors a
    transfer created before the device's lot lookup resolved correctly.
    Also sets to_location_id so the list page's Location ID column/filter
    has something real to resolve."""
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.stock_transfer import StockTransfer
from utils.timezone import app_now

async def main():
    async with AsyncSessionLocal() as db:
        lot = Lot(lot_number="{lot_number_live}", qty=1, buying_price=1000, supplier_name="ITestSupplier",
                  purchase_date=app_now())
        db.add(lot)
        await db.flush()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.stock_in)
        db.add(dev)
        await db.flush()
        t = StockTransfer(device_id=dev.id, move_kind="device", to_location_id="{location_id}",
                          transfer_type="internal", from_warehouse="TRC 1st Floor",
                          to_warehouse="TRC 1st Floor", transferred_by="itest_sender",
                          barcode=dev.barcode, make=dev.brand, model=dev.model,
                          lot_number=None, transfer_date=app_now(), created_by="itest_sender")
        db.add(t)
        await db.commit()
        print(dev.id)

asyncio.run(main())
""")


def _cleanup(barcode, location_unit_id=None):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.lot import Lot
from models.stock_transfer import StockTransfer
from models.work_order import WorkOrder
from models.location import StorageLocation

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for wo in (await db.execute(select(WorkOrder).where(
                    WorkOrder.device_id == dev.id))).scalars().all():
                await db.delete(wo)
            for t in (await db.execute(select(StockTransfer).where(
                    StockTransfer.device_id == dev.id))).scalars().all():
                await db.delete(t)
            # Only delete the Lot if THIS test created it (marked via
            # supplier_name) — devices seeded against select(Lot).limit(1)
            # share an existing, possibly-production lot with other rows;
            # deleting it cascaded a NOT NULL violation on an unrelated
            # device that still referenced it.
            lot = (await db.execute(select(Lot).where(
                    Lot.id == dev.lot_id, Lot.supplier_name == "ITestSupplier"))).scalar_one_or_none()
            await db.delete(dev)
            if lot:
                await db.delete(lot)
        {"" if not location_unit_id else f'''
        loc = (await db.execute(select(StorageLocation).where(
                StorageLocation.unit_id == "{location_unit_id}"))).scalar_one_or_none()
        if loc:
            await db.delete(loc)
        '''}
        await db.commit()

asyncio.run(main())
""")


def test_new_transfer_form_has_location_id_dropdown_on_every_tab():
    html = (pathlib.Path(ROOT) / "templates" / "transfers" / "form.html").read_text(encoding="utf-8")
    assert 'name="to_location_id"' in html
    assert 'id="{{ prefix }}-location-id"' in html
    # One macro call per tab (device/bucket/lot/parts) means the dropdown is
    # rendered once per tab automatically — confirm the macro is invoked 4x.
    assert html.count("{{ transfer_fields(") == 4


def test_move_bucket_tab_is_hidden_not_removed():
    html = (pathlib.Path(ROOT) / "templates" / "transfers" / "form.html").read_text(encoding="utf-8")
    assert 'id="move-bucket-tab"' in html
    assert 'id="moveBucketTab"' in html
    # The nav-item wrapping the Move Bucket button carries d-none.
    bucket_li_start = html.index('id="move-bucket-tab"')
    li_open = html.rfind("<li", 0, bucket_li_start)
    assert "d-none" in html[li_open:bucket_li_start]


def test_move_item_transfer_persists_location_id(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    barcode = f"ITTRLOC{suffix}"
    unit_id = f"ITLOC{suffix}"
    loc_id = _seed_location(unit_id)
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
                     current_stage=DeviceStage.stock_in))
        await db.commit()

asyncio.run(main())
""")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or ""
        user_row = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == "{username}"))).scalar_one()
        print(u.id)

asyncio.run(main())
""")
        r = app_client.post(
            "/transfers/new",
            data={
                "csrf_token": csrf, "barcode": [barcode], "transfer_type": "internal",
                "assigned_user_id": user_row, "to_location_id": loc_id,
            },
            follow_redirects=False,
        )
        assert r.status_code == 302, r.text[:400]

        check = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.stock_transfer import StockTransfer

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        t = (await db.execute(select(StockTransfer).where(
                StockTransfer.device_id == dev.id))).scalars().first()
        print(str(t.to_location_id))

asyncio.run(main())
""")
        assert check == loc_id, check
    finally:
        _cleanup(barcode, unit_id)


def test_list_page_shows_location_id_column_and_hides_others():
    html = (pathlib.Path(ROOT) / "templates" / "transfers" / "list.html").read_text(encoding="utf-8")
    assert "<th>Location ID</th>" in html
    # Location ID must render before Type in document order.
    assert html.index("Location ID") < html.index("<th>Type</th>")
    for hidden in ("From", "To", "Dept.", "Quantity"):
        assert f'class="d-none">{hidden}' in html


def test_list_page_uses_global_table():
    html = (pathlib.Path(ROOT) / "templates" / "transfers" / "list.html").read_text(encoding="utf-8")
    assert "initGlobalTable('#transfersTable'" in html
    assert ".DataTable({" not in html


def test_list_page_lot_column_uses_live_join_not_stale_snapshot(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    barcode = f"ITTRLOT{suffix}"
    unit_id = f"ITLOTLOC{suffix}"
    live_lot = f"LOT{suffix}"
    loc_id = _seed_location(unit_id)
    _seed_transfer_with_stale_lot_snapshot(barcode, unit_id, loc_id, live_lot)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get(f"/transfers?q={barcode}", follow_redirects=True).text
        assert barcode in html
        # The stored snapshot was None ("—" in the old code); the live join
        # must resolve the device's actual current lot number instead.
        assert live_lot in html
    finally:
        _cleanup(barcode, unit_id)


def test_list_page_location_id_filter_narrows_results(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    barcode = f"ITTRLF{suffix}"
    unit_id = f"ITLOCF{suffix}"
    other_unit_id = f"ITLOCF2{suffix}"
    loc_id = _seed_location(unit_id)
    other_loc_id = _seed_location(other_unit_id)
    _seed_transfer_with_stale_lot_snapshot(barcode, unit_id, loc_id, f"LOTF{suffix}")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)

        # Anchor on the device-detail link, not a bare barcode search — the
        # filter bar's own "q" input echoes the search term back into its
        # value= attribute regardless of whether any row matched.
        row_marker = f'href="/devices/{barcode}"'

        html_match = app_client.get(f"/transfers?q={barcode}&location_id={loc_id}",
                                    follow_redirects=True).text
        assert row_marker in html_match

        html_no_match = app_client.get(f"/transfers?q={barcode}&location_id={other_loc_id}",
                                       follow_redirects=True).text
        assert row_marker not in html_no_match
    finally:
        _cleanup(barcode, unit_id)
        _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.location import StorageLocation

async def main():
    async with AsyncSessionLocal() as db:
        loc = (await db.execute(select(StorageLocation).where(
                StorageLocation.unit_id == "{other_unit_id}"))).scalar_one_or_none()
        if loc:
            await db.delete(loc)
        await db.commit()

asyncio.run(main())
""")


def test_export_endpoint_returns_csv_with_location_id_column(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    r = app_client.get("/transfers/export", follow_redirects=True)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    header = r.text.lstrip("﻿").splitlines()[0]
    assert "Location ID" in header
