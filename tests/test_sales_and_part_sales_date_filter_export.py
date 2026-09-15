"""/sales and /part-sales — Date filter + Export button (2026-09-15):

Both pages previously had no way to filter the Date column, and /sales had
only "Export All CSV" (unfiltered, capped 5,000) and "Export Selected"
(checked rows only) — neither exports exactly what the filter bar shows.
/part-sales had no filter bar or export at all.

- /sales, /sales/data (DataTables feed) and the new GET /sales/export all
  share routers/sales.py's _sales_filters(), extended with date_from/date_to
  against Sale.sold_at, so the three can never disagree about what "the
  filtered view" means.
- /part-sales and the new GET /part-sales/export share a new
  _part_sales_filters() against PartSale.sold_at, same pattern.
"""
import csv
import io
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


def _seed_sale(barcode, sale_number, sold_at_iso):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
import models  # noqa
from datetime import datetime
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.sales import Sale

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.sold)
        db.add(dev)
        await db.flush()
        db.add(Sale(sale_number="{sale_number}", device_id=dev.id, sale_price=10000,
                    sold_at=datetime.fromisoformat("{sold_at_iso}"), sold_by="itest"))
        await db.commit()

asyncio.run(main())
""")


def _cleanup_sale(barcode, sale_number):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.sales import Sale

async def main():
    async with AsyncSessionLocal() as db:
        s = (await db.execute(select(Sale).where(Sale.sale_number == "{sale_number}"))).scalar_one_or_none()
        if s:
            await db.delete(s)
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
""")


def _seed_part_sale(sale_number, sold_at_iso):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from datetime import datetime
from sqlalchemy import select
from database import AsyncSessionLocal
from models.spare_parts import SparePart
from models.part_sales import PartSale

async def main():
    async with AsyncSessionLocal() as db:
        part = (await db.execute(select(SparePart).limit(1))).scalars().first()
        db.add(PartSale(sale_number="{sale_number}", part_id=part.id, part_name="ITest Keyboard",
                        qty=1, sale_unit_price=500, total_sale_price=500,
                        sold_at=datetime.fromisoformat("{sold_at_iso}"), sold_by="itest"))
        await db.commit()

asyncio.run(main())
""")


def _cleanup_part_sale(sale_number):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.part_sales import PartSale

async def main():
    async with AsyncSessionLocal() as db:
        s = (await db.execute(select(PartSale).where(PartSale.sale_number == "{sale_number}"))).scalar_one_or_none()
        if s:
            await db.delete(s)
        await db.commit()

asyncio.run(main())
""")


# ── /sales ─────────────────────────────────────────────────────────────────

def test_sales_page_has_date_filter_and_export_button(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/sales", follow_redirects=True).text
    assert 'name="date_from"' in html
    assert 'name="date_to"' in html
    assert 'id="exportFilteredBtn"' in html
    assert "/sales/export?" in html


def test_sales_date_filter_narrows_the_filtered_count(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    barcode_in = f"ITSALEIN{suffix}"
    barcode_out = f"ITSALEOUT{suffix}"
    sale_in = f"ITSN-IN-{suffix}"
    sale_out = f"ITSN-OUT-{suffix}"
    _seed_sale(barcode_in, sale_in, "2026-06-15T10:00:00")
    _seed_sale(barcode_out, sale_out, "2026-01-05T10:00:00")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)

        r = app_client.get("/sales/data", params={
            "date_from": "2026-06-01", "date_to": "2026-06-30",
            "draw": 1, "start": 0, "length": 50,
        })
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        flat = str(body["data"])
        assert sale_in in flat
        assert sale_out not in flat
    finally:
        _cleanup_sale(barcode_in, sale_in)
        _cleanup_sale(barcode_out, sale_out)


def test_sales_export_respects_date_filter(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    barcode_in = f"ITSALEXIN{suffix}"
    barcode_out = f"ITSALEXOUT{suffix}"
    sale_in = f"ITSNX-IN-{suffix}"
    sale_out = f"ITSNX-OUT-{suffix}"
    _seed_sale(barcode_in, sale_in, "2026-06-15T10:00:00")
    _seed_sale(barcode_out, sale_out, "2026-01-05T10:00:00")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)

        r = app_client.get("/sales/export", params={
            "date_from": "2026-06-01", "date_to": "2026-06-30",
        })
        assert r.status_code == 200, r.text[:300]
        assert r.headers["content-type"].startswith("text/csv")
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
        sale_numbers = [row[0] for row in rows[1:]]
        assert sale_in in sale_numbers
        assert sale_out not in sale_numbers
    finally:
        _cleanup_sale(barcode_in, sale_in)
        _cleanup_sale(barcode_out, sale_out)


# ── /part-sales ────────────────────────────────────────────────────────────

def test_part_sales_page_has_date_filter_and_export_button(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/part-sales", follow_redirects=True).text
    assert 'name="date_from"' in html
    assert 'name="date_to"' in html
    assert "/part-sales/export?" in html


def test_part_sales_date_filter_narrows_the_list(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    sale_in = f"ITPSN-IN-{suffix}"
    sale_out = f"ITPSN-OUT-{suffix}"
    _seed_part_sale(sale_in, "2026-06-15T10:00:00")
    _seed_part_sale(sale_out, "2026-01-05T10:00:00")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)

        html = app_client.get("/part-sales", params={
            "date_from": "2026-06-01", "date_to": "2026-06-30",
        }, follow_redirects=True).text
        assert sale_in in html
        assert sale_out not in html
    finally:
        _cleanup_part_sale(sale_in)
        _cleanup_part_sale(sale_out)


def test_part_sales_export_respects_date_filter(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    sale_in = f"ITPSNX-IN-{suffix}"
    sale_out = f"ITPSNX-OUT-{suffix}"
    _seed_part_sale(sale_in, "2026-06-15T10:00:00")
    _seed_part_sale(sale_out, "2026-01-05T10:00:00")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)

        r = app_client.get("/part-sales/export", params={
            "date_from": "2026-06-01", "date_to": "2026-06-30",
        })
        assert r.status_code == 200, r.text[:300]
        assert r.headers["content-type"].startswith("text/csv")
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
        sale_numbers = [row[0] for row in rows[1:]]
        assert sale_in in sale_numbers
        assert sale_out not in sale_numbers
    finally:
        _cleanup_part_sale(sale_in)
        _cleanup_part_sale(sale_out)
