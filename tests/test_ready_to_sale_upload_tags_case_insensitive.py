"""Ready to Sale — Bulk Upload Tags (POST /sales/ready/upload-tags, 2026-09-11 fix):

The stage lookup was a plain `Device.barcode.in_(tags)` — an exact,
case-sensitive match. Tag numbers get typed into spreadsheets by hand and
come back a different case than the stored barcode (this codebase's
barcodes are inconsistently cased — some lots are upper, some lower), so a
tag sitting in Ready to Sale right now was reported "not found" purely
because of casing. The identical bug was already found and fixed on
/devices' own bulk tag upload (routers/devices.py, func.upper().in_()) —
this pins the same fix here.
"""
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


def _seed_ready_device(barcode):
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
                     current_stage=DeviceStage.ready_to_sale)
        db.add(dev)
        await db.commit()

asyncio.run(main())
""")


def _cleanup(barcode):
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


def test_upload_tags_matches_ready_to_sale_device_regardless_of_case(app_client, make_user):  # noqa: F811
    """A tag typed in different case than the stored barcode must still
    resolve to 'found', echoed back in the casing the database stores (the
    page ticks rows by exact barcode string, so echoing the typed casing
    back would select nothing)."""
    suffix = uuid.uuid4().hex[:6].upper()
    barcode = f"ITRTSCASE{suffix}"  # stored upper
    _seed_ready_device(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or ""

        csv_body = f"tag_number\n{barcode.lower()}\n"
        r = app_client.post(
            "/sales/ready/upload-tags",
            data={"csrf_token": csrf},
            files={"file": ("tags.csv", io.BytesIO(csv_body.encode()), "text/csv")},
        )
        assert r.status_code == 200, r.text[:400]
        payload = r.json()
        assert payload["not_found"] == [], f"case-folded tag reported not found: {payload}"
        assert payload["not_ready"] == [], f"unexpectedly reported not ready: {payload}"
        assert barcode in payload["found"], (
            f"found echoed the typed casing instead of the stored barcode: {payload['found']}")
    finally:
        _cleanup(barcode)


def test_upload_tags_still_reports_not_ready_for_a_different_stage(app_client, make_user):  # noqa: F811
    """A real device that exists but isn't in Ready to Sale must still land
    in not_ready, not found — the case-insensitive fix must not blur the
    stage check itself."""
    suffix = uuid.uuid4().hex[:6].upper()
    barcode = f"ITRTSNR{suffix}"
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
                     current_stage=DeviceStage.iqc)
        db.add(dev)
        await db.commit()

asyncio.run(main())
""")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or ""

        csv_body = f"tag_number\n{barcode.lower()}\n"
        r = app_client.post(
            "/sales/ready/upload-tags",
            data={"csrf_token": csrf},
            files={"file": ("tags.csv", io.BytesIO(csv_body.encode()), "text/csv")},
        )
        assert r.status_code == 200, r.text[:400]
        payload = r.json()
        assert payload["found"] == [], f"wrong-stage tag was reported found: {payload}"
        assert barcode in payload["not_ready"], f"expected in not_ready: {payload}"
    finally:
        _cleanup(barcode)
