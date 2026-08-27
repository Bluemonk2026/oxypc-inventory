"""Selling company on Invoice/Delivery Challan (routers/sales.py create_sale,
routers/invoices.py print_invoice/print_waybill):

 - Every Sale now resolves and LOCKS IN a company_id at creation time,
   matched from the sold device's entity to the Company Setting row tagged
   with that same entity (models.company.Company.company_entity) —
   previously invoices.py always printed whichever active company was
   oldest, regardless of which entity actually owned the device (reported
   bug: every invoice showed "Renew Circuit").
 - A device whose entity has no matching Company row falls back to the
   oldest active company (same default as before this change) rather than
   blocking the sale.
 - Printing an invoice/waybill never re-resolves the company from current
   Company Setting — it reads sale.company_id, so editing or deactivating a
   company later does not change what an already-recorded sale prints.
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


def _seed_company(name, entity, gstin="29ITESTGST1Z5"):
    out = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from database import AsyncSessionLocal
from models.company import Company

async def main():
    async with AsyncSessionLocal() as db:
        c = Company(company_name="{name}", company_entity="{entity}",
                    company_gstin="{gstin}", company_state="Delhi",
                    company_state_code="07", is_active=True)
        db.add(c)
        await db.flush()
        print(c.id)
        await db.commit()

asyncio.run(main())
""")
    return out


def _deactivate_company(company_id):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.company import Company

async def main():
    async with AsyncSessionLocal() as db:
        c = (await db.execute(select(Company).where(Company.id == "{company_id}"))).scalar_one()
        c.company_name = "MUTATED AFTER SALE"
        c.is_active = False
        await db.commit()

asyncio.run(main())
""")


def _cleanup_company(company_id):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.company import Company

async def main():
    async with AsyncSessionLocal() as db:
        c = (await db.execute(select(Company).where(Company.id == "{company_id}"))).scalar_one_or_none()
        if c:
            await db.delete(c)
        await db.commit()

asyncio.run(main())
""")


def _seed_device(barcode, entity):
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
                     current_stage=DeviceStage.ready_to_sale, entity="{entity}",
                     device_price=1000))
        await db.commit()

asyncio.run(main())
""")


def _cleanup_device_and_sale(barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
import models  # noqa — must load every model so Sale.company_id's FK to
                # "companies" can resolve; a narrow models.sales-only import
                # leaves that table unregistered and SQLAlchemy raises
                # NoReferencedTableError on first flush.
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device, StageMovement
from models.sales import Sale
from models.engines import DeviceCosting

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for s in (await db.execute(select(Sale).where(Sale.device_id == dev.id))).scalars().all():
                await db.delete(s)
            for m in (await db.execute(select(StageMovement).where(
                    StageMovement.device_id == dev.id))).scalars().all():
                await db.delete(m)
            for c in (await db.execute(select(DeviceCosting).where(
                    DeviceCosting.device_id == dev.id))).scalars().all():
                await db.delete(c)
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
""")


def _get_sale_company_id(barcode):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
import models  # noqa — see _cleanup_device_and_sale for why
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.sales import Sale

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        sale = (await db.execute(select(Sale).where(Sale.device_id == dev.id))).scalar_one()
        print(sale.company_id)

asyncio.run(main())
""")


def test_sale_locks_in_company_matching_device_entity(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    entity_a = f"ITestEntityA{suffix}"
    entity_b = f"ITestEntityB{suffix}"
    barcode = f"ITSALECO{suffix}"

    company_a = _seed_company(f"ITest Company A {suffix}", entity_a)
    company_b = _seed_company(f"ITest Company B {suffix}", entity_b)
    _seed_device(barcode, entity_b)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post("/sales/new", data={
            "csrf_token": csrf, "barcode": barcode, "sale_price": "5000",
        }, follow_redirects=False)
        assert r.status_code in (302, 200), r.text[:400]

        assert _get_sale_company_id(barcode) == company_b, (
            "sale must resolve to the company tagged with the device's own entity, not entity_a's")
    finally:
        _cleanup_device_and_sale(barcode)
        _cleanup_company(company_a)
        _cleanup_company(company_b)


def test_sale_falls_back_to_oldest_active_company_when_entity_unmatched(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    known_entity = f"ITestKnownEntity{suffix}"
    unmatched_entity = f"ITestNoCompanyForThis{suffix}"
    barcode = f"ITSALEFB{suffix}"

    company = _seed_company(f"ITest Fallback Co {suffix}", known_entity)
    _seed_device(barcode, unmatched_entity)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"
        r = app_client.post("/sales/new", data={
            "csrf_token": csrf, "barcode": barcode, "sale_price": "5000",
        }, follow_redirects=False)
        assert r.status_code in (302, 200), r.text[:400]

        # No company is tagged with unmatched_entity, so the sale must still
        # go through (never block a sale for missing company setup) and land
        # on SOME active company rather than null.
        resolved = _get_sale_company_id(barcode)
        assert resolved != "None"
    finally:
        _cleanup_device_and_sale(barcode)
        _cleanup_company(company)


def test_invoice_print_shows_locked_in_company_after_it_is_later_changed(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    entity = f"ITestLockEntity{suffix}"
    barcode = f"ITSALELOCK{suffix}"
    original_name = f"ITest Original Co {suffix}"

    company = _seed_company(original_name, entity)
    _seed_device(barcode, entity)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"
        app_client.post("/sales/new", data={
            "csrf_token": csrf, "barcode": barcode, "sale_price": "5000",
        }, follow_redirects=False)

        sale_id = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
import models  # noqa — see _cleanup_device_and_sale for why
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.sales import Sale

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        sale = (await db.execute(select(Sale).where(Sale.device_id == dev.id))).scalar_one()
        print(sale.id)

asyncio.run(main())
""")

        # Mutate the company AFTER the sale — rename it and deactivate it.
        _deactivate_company(company)

        html = app_client.get(f"/invoices/print/{sale_id}", follow_redirects=True).text
        assert original_name in html, "invoice must show the company as it was on the sale date"
        assert "MUTATED AFTER SALE" not in html

        html2 = app_client.get(f"/invoices/waybill/{sale_id}", follow_redirects=True).text
        assert original_name in html2
        assert "MUTATED AFTER SALE" not in html2
    finally:
        _cleanup_device_and_sale(barcode)
        _cleanup_company(company)


def test_old_sale_without_company_id_still_prints_via_fallback(app_client, make_user):  # noqa: F811
    """A sale recorded before this column existed (company_id=None) must not
    break print_invoice/print_waybill — they fall back to get_company_settings'
    pre-existing 'oldest active company' default."""
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITSALEPRE{suffix}"
    _seed_device(barcode, f"ITestPreExistingEntity{suffix}")

    sale_id = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
import models  # noqa — see _cleanup_device_and_sale for why
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device
from models.sales import Sale
import uuid as u

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        sale = Sale(sale_number="ITPRE{suffix}", device_id=dev.id, sale_price=1000, company_id=None)
        db.add(sale)
        await db.flush()
        print(sale.id)
        await db.commit()

asyncio.run(main())
""")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        r = app_client.get(f"/invoices/print/{sale_id}", follow_redirects=True)
        assert r.status_code == 200
        r2 = app_client.get(f"/invoices/waybill/{sale_id}", follow_redirects=True)
        assert r2.status_code == 200
    finally:
        _cleanup_device_and_sale(barcode)
