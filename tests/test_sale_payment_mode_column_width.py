"""New Tag Sale / New Part Sale — Payment Mode column width (2026-09-03 fix):

Sale.payment_mode and PartSale.payment_mode were VARCHAR(20), left over from
the old hardcoded cash/upi/card/credit codes. Once the Payment Mode dropdown
was wired to Master Data's Dropdown Configuration (2026-08-31), selecting a
longer seeded value — "Bank Transfer (NEFT/RTGS/IMPS)" is 30 characters —
threw an unhandled Postgres StringDataRightTruncationError on submit (a raw
500, not a friendly form error), because Postgres rejects an over-length
VARCHAR insert outright rather than silently truncating it. Widened both
columns to VARCHAR(50).
"""
import pathlib
import subprocess
import sys
import uuid

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)

LONG_PAYMENT_MODE = "Bank Transfer (NEFT/RTGS/IMPS)"  # 30 chars — the value that broke it


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def _seed_device_ready_to_sale(barcode):
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
                     current_stage=DeviceStage.ready_to_sale, device_price=15000))
        await db.commit()

asyncio.run(main())
""")


def _cleanup_device(barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
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


def test_new_tag_sale_accepts_a_long_master_data_payment_mode(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITPAYWIDE{suffix}"
    _seed_device_ready_to_sale(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post("/sales/new", data={
            "csrf_token": csrf, "barcode": barcode, "sale_price": "15000",
            "payment_mode": LONG_PAYMENT_MODE,
        }, follow_redirects=False)
        assert r.status_code in (302, 200), r.text[:500]
        assert r.status_code != 500

        stored = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.sales import Sale

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        s = (await db.execute(select(Sale).where(Sale.device_id == dev.id))).scalar_one()
        print(s.payment_mode)

asyncio.run(main())
""")
        assert stored == LONG_PAYMENT_MODE
    finally:
        _cleanup_device(barcode)
