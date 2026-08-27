"""backfill_sale_company.py — one-off backfill for sales recorded before
Sale.company_id/company_* existed. Matches each sale's device's current
entity to a Company row, same rule create_sale() uses going forward.
"""
import pathlib
import subprocess
import sys
import uuid

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def test_backfill_populates_snapshot_from_matching_entity():
    suffix = uuid.uuid4().hex[:6]
    entity = f"ITestBackfillEntity{suffix}"
    barcode = f"ITBKFILL{suffix}"
    company_name = f"ITest Backfill Co {suffix}"

    company_id = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from database import AsyncSessionLocal
from models.company import Company

async def main():
    async with AsyncSessionLocal() as db:
        c = Company(company_name="{company_name}", company_entity="{entity}",
                    company_gstin="29ITESTGST1Z5", company_state="Delhi",
                    company_state_code="07", is_active=True)
        db.add(c)
        await db.flush()
        print(c.id)
        await db.commit()

asyncio.run(main())
""")

    sale_id = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
import models  # noqa
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.sales import Sale

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="X", model="Y",
                     current_stage=DeviceStage.sold, entity="{entity}")
        db.add(dev)
        await db.flush()
        sale = Sale(sale_number="ITBKF{suffix}", device_id=dev.id, sale_price=1000, company_id=None)
        db.add(sale)
        await db.flush()
        print(sale.id)
        await db.commit()

asyncio.run(main())
""")

    try:
        out = _run("import backfill_sale_company, asyncio; asyncio.run(backfill_sale_company.main())")
        assert f"Backfilled" in out

        result = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
import models  # noqa
from sqlalchemy import select
from database import AsyncSessionLocal
from models.sales import Sale

async def main():
    async with AsyncSessionLocal() as db:
        sale = (await db.execute(select(Sale).where(Sale.id == "{sale_id}"))).scalar_one()
        print("company_name=" + str(sale.company_name))
        print("company_gstin=" + str(sale.company_gstin))

asyncio.run(main())
""")
        lines = dict(l.split("=", 1) for l in result.splitlines() if "=" in l)
        assert lines["company_name"] == company_name
        assert lines["company_gstin"] == "29ITESTGST1Z5"
    finally:
        _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
import models  # noqa
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.sales import Sale
from models.company import Company

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for s in (await db.execute(select(Sale).where(Sale.device_id == dev.id))).scalars().all():
                await db.delete(s)
            await db.delete(dev)
        c = (await db.execute(select(Company).where(Company.id == "{company_id}"))).scalar_one_or_none()
        if c:
            await db.delete(c)
        await db.commit()

asyncio.run(main())
""")


def test_backfill_is_a_noop_on_sales_already_resolved():
    """Sales already touched by create_sale's new logic (company_name set)
    must be left alone — re-running the backfill must not overwrite them."""
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITBKFDONE{suffix}"

    sale_id = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
import models  # noqa
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.sales import Sale

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="X", model="Y",
                     current_stage=DeviceStage.sold)
        db.add(dev)
        await db.flush()
        sale = Sale(sale_number="ITBKFD{suffix}", device_id=dev.id, sale_price=1000,
                    company_name="Already Set Co", company_gstin="ALREADY-SET")
        db.add(sale)
        await db.flush()
        print(sale.id)
        await db.commit()

asyncio.run(main())
""")
    try:
        _run("import backfill_sale_company, asyncio; asyncio.run(backfill_sale_company.main())")

        result = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
import models  # noqa
from sqlalchemy import select
from database import AsyncSessionLocal
from models.sales import Sale

async def main():
    async with AsyncSessionLocal() as db:
        sale = (await db.execute(select(Sale).where(Sale.id == "{sale_id}"))).scalar_one()
        print("company_gstin=" + str(sale.company_gstin))

asyncio.run(main())
""")
        assert "company_gstin=ALREADY-SET" in result
    finally:
        _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
import models  # noqa
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.sales import Sale

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for s in (await db.execute(select(Sale).where(Sale.device_id == dev.id))).scalars().all():
                await db.delete(s)
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
""")
