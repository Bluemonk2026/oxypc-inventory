"""/gate-pass — "Customer Return" label under Tag Number (2026-09-02):

Return Stock's Complete action (routers/stock.py return_stock_complete)
creates a new Sale for the tag, which already surfaces on /gate-pass
automatically (that page lists every Sale, not just first-time ones). The
one thing it didn't have: a way to tell those re-sales apart from ordinary
sales. A device carries a "Customer Return" badge under its Tag Number in
/gate-pass/data whenever it has ANY Return row — checked by device_id, not
Device.return_status (which Complete resets to False), so the label survives
past that reset.
"""
import pathlib
import subprocess
import sys
import uuid

from tests.test_iqc_new_user import _login, make_user  # noqa: F411  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def _seed_sale_no_return(barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
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
        db.add(Sale(sale_number="SALEGP{barcode[-6:]}", device_id=dev.id, sale_price=10000,
                    customer_name="Plain Customer"))
        await db.commit()

asyncio.run(main())
""")


def _seed_sale_with_return(barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.sales import Sale, Return

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.sold, return_status=False)
        db.add(dev)
        await db.flush()
        orig_sale = Sale(sale_number="SALEGP{barcode[-6:]}A", device_id=dev.id, sale_price=10000,
                         customer_name="Returning Customer")
        db.add(orig_sale)
        await db.flush()
        db.add(Return(sale_id=orig_sale.id, device_id=dev.id, reason="Not working",
                      condition_on_return="Minor Damage", approval_status="approved"))
        # The re-sale Complete would create — return_status is already back to
        # False, same as after a real Complete run.
        db.add(Sale(sale_number="SALEGP{barcode[-6:]}B", device_id=dev.id, sale_price=9000,
                    customer_name="Returning Customer"))
        await db.commit()

asyncio.run(main())
""")


def _cleanup_device(barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.sales import Sale, Return

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for r in (await db.execute(select(Return).where(Return.device_id == dev.id))).scalars().all():
                await db.delete(r)
            for s in (await db.execute(select(Sale).where(Sale.device_id == dev.id))).scalars().all():
                await db.delete(s)
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
""")


def test_ordinary_sale_has_no_customer_return_badge(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITGPPLAIN{suffix}"
    _seed_sale_no_return(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        r = app_client.get(f"/gate-pass/data?length=500", follow_redirects=True)
        assert r.status_code == 200
        body = r.json()
        row = next(row for row in body["data"] if barcode in row[1])
        assert "Customer Return" not in row[1]
    finally:
        _cleanup_device(barcode)


def test_re_sold_returned_tag_shows_customer_return_badge(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITGPRET{suffix}"
    _seed_sale_with_return(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        r = app_client.get(f"/gate-pass/data?length=500", follow_redirects=True)
        assert r.status_code == 200
        body = r.json()
        matching = [row for row in body["data"] if barcode in row[1]]
        # Both the original sale and the re-sale surface — both carry the tag,
        # so both carry the badge (the label is device-level, not sale-level).
        assert len(matching) == 2
        for row in matching:
            assert "Customer Return" in row[1]
    finally:
        _cleanup_device(barcode)
