"""2026-09-22: test-data intake for External Partner (Trade Partner) testing.

/trade-partner/manage-lots was rebuilt from a generic "restrict any live Lot,
grant visibility to any real dealer" tool into a hub guiding staff through the
EXISTING Add GRN -> Add/Map Lots -> Upload Asset IQC flow, scoped by the
EXTERNAL_PARTNER_TEST_LOT_PREFIX ("EPT-") lot-number convention and the
EXTERNAL_PARTNER_TEST_ENTITY ("External Partner Test") entity value
(models/master.py). Two safety nets this exercises end-to-end:

1. An EPT- lot auto-restricts itself the moment routers/grn.py's REAL
   grn_add_lot endpoint creates it -- never open to the live dealer catalog
   by default (Lot.is_restricted otherwise defaults to False = visible to
   every dealer).
2. Devices on the test entity are excluded from routers/devices.py's default
   (unfiltered) All Inventory view, but still show up when explicitly
   entity-filtered -- proving the exclusion is a default, not a hard block.
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


def _seed_bare_device(barcode):
    """A device with NO entity set (the common 'Unassigned' case) -- guards
    the NULL-safety bug the exclusion clauses had before it was fixed:
    `Device.entity != X` alone evaluates to SQL NULL (not TRUE) for a NULL
    entity, silently excluding every entity-less device from default views,
    not just the External Partner test entity."""
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
                     current_stage=DeviceStage.iqc))
        await db.commit()

asyncio.run(main())
""")


def _cleanup_bare_device(barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device, StageMovement

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for m in (await db.execute(select(StageMovement).where(StageMovement.device_id == dev.id))).scalars().all():
                await db.delete(m)
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
""")


def test_entity_less_device_still_shows_in_default_views(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    barcode = f"ITNOENT{suffix}"
    username, password = make_user("admin")
    _login(app_client, username, password)
    _seed_bare_device(barcode)
    try:
        assert barcode in app_client.get("/devices", follow_redirects=True).text
    finally:
        _cleanup_bare_device(barcode)


def _seed_test_device(barcode, lot_id):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from database import AsyncSessionLocal
from models.device import Device, DeviceStage
from models.master import EXTERNAL_PARTNER_TEST_ENTITY

async def main():
    async with AsyncSessionLocal() as db:
        db.add(Device(barcode="{barcode}", lot_id="{lot_id}", brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.iqc, entity=EXTERNAL_PARTNER_TEST_ENTITY))
        await db.commit()

asyncio.run(main())
""")


def _lot_is_restricted(lot_id):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).where(Lot.id == "{lot_id}"))).scalar_one()
        print(lot.is_restricted)

asyncio.run(main())
""") == "True"


def _cleanup(barcode, lot_number, grn_id):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device, StageMovement
from models.lot import Lot
from models.grn_import import GRNImport

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for m in (await db.execute(select(StageMovement).where(StageMovement.device_id == dev.id))).scalars().all():
                await db.delete(m)
            await db.delete(dev)
        lot = (await db.execute(select(Lot).where(Lot.lot_number == "{lot_number}"))).scalar_one_or_none()
        if lot:
            await db.delete(lot)
        if "{grn_id}":
            g = (await db.execute(select(GRNImport).where(GRNImport.id == "{grn_id}"))).scalar_one_or_none()
            if g:
                await db.delete(g)
        await db.commit()

asyncio.run(main())
""")


def test_ept_lot_auto_restricts_on_creation_via_real_add_lot_endpoint(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    lot_number = f"EPT-{suffix}"
    barcode = f"ITEPT{suffix}"
    username, password = make_user("admin")
    _login(app_client, username, password)
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    grn_id = ""
    try:
        r = app_client.post("/grn/create-manual", data={
            "csrf_token": csrf, "sender_name": "ITest External Partner Supplier",
            "invoice_number": f"ITEPTINV{suffix}", "quantity": "1", "amount": "0",
            "source": "post_iqc",
        }, follow_redirects=False)
        assert r.status_code == 302, r.text[:300]
        location = r.headers.get("location", "")
        # grn_create_manual redirects to /grn/post-iqc with no id in the URL —
        # look the GRN up by the invoice number we just posted.
        lookup = app_client.get("/grn/post-iqc").text
        assert f"ITEPTINV{suffix}" in lookup, "GRN not found on post-iqc page after create"

        grn_id = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.grn_import import GRNImport

async def main():
    async with AsyncSessionLocal() as db:
        g = (await db.execute(select(GRNImport).where(GRNImport.invoice_number == "ITEPTINV{suffix}"))).scalar_one()
        print(g.id)

asyncio.run(main())
""")

        r2 = app_client.post(f"/grn/{grn_id}/add-lot", data={
            "csrf_token": csrf, "lot_number": [lot_number],
        }, follow_redirects=False)
        assert r2.status_code == 200, r2.text[:300]
        assert r2.json().get("ok") is True, r2.text[:300]

        lot_id = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).where(Lot.lot_number == "{lot_number}"))).scalar_one()
        print(lot.id)

asyncio.run(main())
""")

        # 1. Auto-restrict: never open to the live dealer catalog by default.
        assert _lot_is_restricted(lot_id) is True

        # 2. Manage Lots page picks it up (scoped to EPT- lots only) and shows
        # "No devices yet" before any IQC upload.
        ml_html = app_client.get("/trade-partner/manage-lots").text
        assert lot_number in ml_html
        assert "No devices yet" in ml_html

        # 3. Seed a device on the test entity against this lot (stands in for
        # the real Bulk Upload IQC step, which is unrelated pre-existing
        # logic) and confirm both the exclusion and the entity-confirmed
        # badge.
        _seed_test_device(barcode, lot_id)

        ml_html2 = app_client.get("/trade-partner/manage-lots").text
        assert "Confirmed" in ml_html2

        # 4. All Inventory default (unfiltered) view excludes it...
        default_html = app_client.get("/devices", follow_redirects=True).text
        assert barcode not in default_html

        # ...but an explicit Entity filter for the test entity still shows it.
        filtered_html = app_client.get(
            "/devices?entity=External+Partner+Test", follow_redirects=True).text
        assert barcode in filtered_html
    finally:
        _cleanup(barcode, lot_number, grn_id)
