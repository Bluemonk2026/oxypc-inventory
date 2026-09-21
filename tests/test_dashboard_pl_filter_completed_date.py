"""2026-09-21: Dashboard "P&L From"/"P&L To" filter, rebuilt from scratch.

Prior state: the filter fed a `lot_pl` list that `dashboard.html` never
rendered anywhere (dead computation), and even that dead computation was
itself broken — it filtered on a `purchase_date` dict key that was never
set, so setting either bound silently emptied the (invisible) list. Setting
the filter had ZERO visible effect on the page.

Now: P&L From/To scopes by each device's own "stage completed" date —
Sale.sold_at for a device that ended up Sold, or the StageMovement.moved_at
into Scrapped/Scrap for Sale for one that ended up there. A device still
mid-pipeline has no completed date and never counts once the filter is
active. This drives two things:
 - A newly-rendered "Lot P&L" table on the dashboard (previously nonexistent
   in the UI) — with no filter, full all-time figures per lot (unchanged
   from what the dead computation always calculated); with a filter, each
   lot's buying_price/parts_cost/labour_cost/cosmetic_cost/revenue are
   scoped to just the devices in that lot that completed in-range (buying
   price attributed per-unit — lot.buying_price / lot.qty — to only those
   devices), and lots with nothing completed in-range are left out entirely.
 - Financial Summary's Total Investment/Total Revenue/Net Profit, which stay
   the exact same all-time figures with no filter, but switch to the same
   completed-date scoping the moment either bound is set. Parts Spent/Labour
   Spent are untouched — those stay tied to the Year dropdown, unrelated to
   this filter, per the pre-existing cross-page-consistency comment.
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


def _seed_lot_two_devices_one_sold(lot_number, supplier, buying_price, sold_barcode, other_barcode,
                                    sold_at_iso, sale_price):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from datetime import datetime
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.sales import Sale

async def main():
    async with AsyncSessionLocal() as db:
        lot = Lot(lot_number="{lot_number}", supplier_name="{supplier}",
                  buying_price={buying_price}, qty=2, purchase_date=datetime(2019, 1, 1))
        db.add(lot)
        await db.flush()
        sold_dev = Device(barcode="{sold_barcode}", lot_id=lot.id, brand="X", model="Y",
                          current_stage=DeviceStage.sold)
        other_dev = Device(barcode="{other_barcode}", lot_id=lot.id, brand="X", model="Y",
                           current_stage=DeviceStage.l1)
        db.add(sold_dev)
        db.add(other_dev)
        await db.flush()
        sale = Sale(sale_number="ITPLSALE{uuid.uuid4().hex[:8]}", device_id=sold_dev.id,
                    sale_price={sale_price}, sold_by="itest",
                    sold_at=datetime.fromisoformat("{sold_at_iso}"))
        db.add(sale)
        await db.commit()
        print(lot.id)

asyncio.run(main())
""")


def _cleanup(lot_number, sold_barcode, other_barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, StageMovement
from models.sales import Sale

async def main():
    async with AsyncSessionLocal() as db:
        for bc in ("{sold_barcode}", "{other_barcode}"):
            dev = (await db.execute(select(Device).where(Device.barcode == bc))).scalar_one_or_none()
            if dev:
                for sale in (await db.execute(select(Sale).where(Sale.device_id == dev.id))).scalars().all():
                    await db.delete(sale)
                for m in (await db.execute(select(StageMovement).where(
                        StageMovement.device_id == dev.id))).scalars().all():
                    await db.delete(m)
                await db.delete(dev)
        lot = (await db.execute(select(Lot).where(Lot.lot_number == "{lot_number}"))).scalar_one_or_none()
        if lot:
            await db.delete(lot)
        await db.commit()

asyncio.run(main())
""")


def _lot_pl_row_for(html, lot_number):
    idx = html.find(f">{lot_number}<")
    if idx < 0:
        return None
    row_start = html.rfind("<tr>", 0, idx)
    row_end = html.find("</tr>", idx)
    return html[row_start:row_end]


def test_no_filter_lot_pl_shows_full_buying_price(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    lot_number = f"ITPLLOT{suffix}"
    sold_barcode = f"ITPLSOLD{suffix}"
    other_barcode = f"ITPLOTHER{suffix}"
    _seed_lot_two_devices_one_sold(lot_number, "ITest Supplier", 10000, sold_barcode, other_barcode,
                                    "2020-05-15T10:00:00", 5000)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get("/dashboard", follow_redirects=True).text
        assert "Lot P&amp;L" in html or "Lot P&L" in html
        row = _lot_pl_row_for(html, lot_number)
        assert row is not None, "seeded lot did not appear in the unfiltered Lot P&L table"
        # Unfiltered: full lot buying_price (10,000), not halved.
        assert "10,000" in row
        assert "5,000" in row  # revenue from the one sale
    finally:
        _cleanup(lot_number, sold_barcode, other_barcode)


def test_filter_covering_sale_date_scopes_buying_price_and_shows_lot(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    lot_number = f"ITPLLOT2{suffix}"
    sold_barcode = f"ITPLSOLD2{suffix}"
    other_barcode = f"ITPLOTHER2{suffix}"
    _seed_lot_two_devices_one_sold(lot_number, "ITest Supplier", 10000, sold_barcode, other_barcode,
                                    "2020-05-15T10:00:00", 5000)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get(
            "/dashboard?pl_from=2020-05-01&pl_to=2020-05-31", follow_redirects=True
        ).text
        row = _lot_pl_row_for(html, lot_number)
        assert row is not None, "lot with a sale inside the range should still appear"
        # Only 1 of the lot's 2 devices completed in-range: buying_price
        # attributed as (10000 / 2) * 1 = 5,000, not the full 10,000.
        assert "5,000" in row
        assert "10,000" not in row
        assert "Completed-date filtered" in html
    finally:
        _cleanup(lot_number, sold_barcode, other_barcode)


def test_filter_excluding_sale_date_hides_lot_entirely(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    lot_number = f"ITPLLOT3{suffix}"
    sold_barcode = f"ITPLSOLD3{suffix}"
    other_barcode = f"ITPLOTHER3{suffix}"
    _seed_lot_two_devices_one_sold(lot_number, "ITest Supplier", 10000, sold_barcode, other_barcode,
                                    "2020-05-15T10:00:00", 5000)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get(
            "/dashboard?pl_from=2021-01-01&pl_to=2021-12-31", follow_redirects=True
        ).text
        row = _lot_pl_row_for(html, lot_number)
        assert row is None, "lot with nothing completed in-range must not appear"
    finally:
        _cleanup(lot_number, sold_barcode, other_barcode)


def test_scrapped_device_counts_as_completed_via_stage_movement(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    lot_number = f"ITPLSCRAP{suffix}"
    barcode = f"ITPLSCRAPDEV{suffix}"
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from datetime import datetime
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage, StageMovement

async def main():
    async with AsyncSessionLocal() as db:
        lot = Lot(lot_number="{lot_number}", supplier_name="ITest Supplier",
                  buying_price=3000, qty=1, purchase_date=datetime(2019, 1, 1))
        db.add(lot)
        await db.flush()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="X", model="Y",
                     current_stage=DeviceStage.scrapped)
        db.add(dev)
        await db.flush()
        db.add(StageMovement(device_id=dev.id, from_stage=DeviceStage.l3, to_stage=DeviceStage.scrapped,
                             moved_by="itest", moved_at=datetime(2020, 6, 10)))
        await db.commit()

asyncio.run(main())
""")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get(
            "/dashboard?pl_from=2020-06-01&pl_to=2020-06-30", follow_redirects=True
        ).text
        row = _lot_pl_row_for(html, lot_number)
        assert row is not None, "lot whose only device was scrapped in-range should appear"
        assert "3,000" in row  # full buying_price attributed (1 of 1 device completed)
    finally:
        _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, StageMovement

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for m in (await db.execute(select(StageMovement).where(
                    StageMovement.device_id == dev.id))).scalars().all():
                await db.delete(m)
            await db.delete(dev)
        lot = (await db.execute(select(Lot).where(Lot.lot_number == "{lot_number}"))).scalar_one_or_none()
        if lot:
            await db.delete(lot)
        await db.commit()

asyncio.run(main())
""")


def test_no_filter_financial_summary_matches_prior_alltime_total(app_client, make_user):  # noqa: F811
    """Regression guard: with no P&L From/To set, Total Investment must be
    the exact unscoped SUM(Lot.buying_price) across every lot — unchanged
    from before this feature existed."""
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/dashboard", follow_redirects=True).text

    expected = _run("""
import asyncio, sys
sys.path.insert(0, r"%s")
from sqlalchemy import select, func
from database import AsyncSessionLocal
from models.lot import Lot

async def main():
    async with AsyncSessionLocal() as db:
        total = (await db.execute(select(func.coalesce(func.sum(Lot.buying_price), 0)))).scalar()
        print(int(total))

asyncio.run(main())
""" % ROOT)
    formatted = f"{int(expected):,}"
    assert f"₹{formatted}" in html


def test_dashboard_pl_filter_no_longer_500s(app_client, make_user):  # noqa: F811
    """The filter previously had no code path that could error visibly since
    it silently no-op'd; now it runs real queries — confirm it doesn't 500
    on a normal date range."""
    username, password = make_user("admin")
    _login(app_client, username, password)
    r = app_client.get("/dashboard?pl_from=2026-01-01&pl_to=2026-12-31", follow_redirects=True)
    assert r.status_code == 200
