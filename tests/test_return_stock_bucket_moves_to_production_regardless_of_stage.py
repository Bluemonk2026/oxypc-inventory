"""Return Stock's "Assign Bucket" -> "Move to Production" (2026-09-02 fix):

Reported: a bucket created from the Inventory Manager page's Return Stock
table (routers/stock.py return_stock_assign_bucket, is_customer_return=True)
did not appear in Production Manager's Bucket Allocation tab after "Move to
Production" — even though the bucket's own status/assigned_to_production
flags were set correctly.

Root cause: _move_bucket_devices_to_trc (routers/buckets.py) only moves
devices whose current_stage == stock_in, to protect against a reused
bucket_number sweeping up unrelated old devices. Return Stock devices are
never at stock_in — they're mid-repair tags re-entering the pipeline at
whatever stage their return re-entered them at (iqc, l1, cleaning, ...). So
zero devices ever moved to trc_production for these buckets, and
/api/buckets?with_stage=trc_production (which drops buckets holding zero
active devices in that stage) silently omitted the bucket from the tab.

Fix: is_customer_return buckets skip the stock_in restriction entirely —
every device on one got there specifically via the Return Stock Assign
Bucket action, so the stale-reused-bucket-number risk doesn't apply.
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


def _seed_customer_return_bucket_with_device_at(barcode, bucket_number, stage):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.bucket import Bucket

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        bucket = Bucket(bucket_number="{bucket_number}", name="Return Carton",
                        is_customer_return=True)
        db.add(bucket)
        await db.flush()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="X", model="Y",
                     current_stage=DeviceStage.{stage}, bucket_id=bucket.id,
                     return_status=True)
        db.add(dev)
        await db.commit()
        print(bucket.id)

asyncio.run(main())
""")


def _cleanup(barcode, bucket_number):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device, StageMovement
from models.bucket import Bucket

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for m in (await db.execute(select(StageMovement).where(
                    StageMovement.device_id == dev.id))).scalars().all():
                await db.delete(m)
            await db.delete(dev)
        bkt = (await db.execute(select(Bucket).where(Bucket.bucket_number == "{bucket_number}"))).scalar_one_or_none()
        if bkt:
            await db.delete(bkt)
        await db.commit()

asyncio.run(main())
""")


def test_customer_return_bucket_at_iqc_still_moves_to_production(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITRSMOV{suffix}"
    bucket_number = f"BKTRSMOV{suffix}"
    out = _seed_customer_return_bucket_with_device_at(barcode, bucket_number, "iqc")
    bucket_id = out.strip().splitlines()[-1]
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post(f"/buckets/{bucket_id}/move-to-trc", data={"csrf_token": csrf})
        assert r.status_code == 200, r.text[:500]
        assert r.json()["moved"] == 1

        state = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.bucket import Bucket

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        bkt = (await db.execute(select(Bucket).where(Bucket.bucket_number == "{bucket_number}"))).scalar_one()
        print(dev.current_stage.value)
        print(bkt.status)
        print(bkt.assigned_to_production)

asyncio.run(main())
""").splitlines()
        assert state[0] == "trc_production"
        assert state[1] == "trc_pending"
        assert state[2] == "True"

        # And it now actually surfaces via the same API call the Bucket
        # Allocation tab uses.
        buckets = app_client.get(
            "/api/buckets?status=trc_pending,validated&with_stage=trc_production"
        ).json()
        match = next((b for b in buckets if b["bucket_number"] == bucket_number), None)
        assert match, "bucket did not surface in the Bucket Allocation feed"
        assert match["device_count"] == 1
    finally:
        _cleanup(barcode, bucket_number)


def test_ordinary_bucket_at_iqc_still_does_not_move(app_client, make_user):  # noqa: F811
    """Regression guard: a NON-customer-return bucket must keep the original
    stock_in-only behavior — this fix must not loosen the stale-bucket-reuse
    protection for the general case."""
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITRSNOMOV{suffix}"
    bucket_number = f"BKTNOMOV{suffix}"
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.bucket import Bucket

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        bucket = Bucket(bucket_number="{bucket_number}", name="Ordinary Bucket")
        db.add(bucket)
        await db.flush()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="X", model="Y",
                     current_stage=DeviceStage.iqc, bucket_id=bucket.id)
        db.add(dev)
        await db.commit()
        print(bucket.id)

asyncio.run(main())
""")
    bucket_id = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.bucket import Bucket

async def main():
    async with AsyncSessionLocal() as db:
        bkt = (await db.execute(select(Bucket).where(Bucket.bucket_number == "{bucket_number}"))).scalar_one()
        print(bkt.id)

asyncio.run(main())
""")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post(f"/buckets/{bucket_id}/move-to-trc", data={"csrf_token": csrf})
        assert r.status_code == 200, r.text[:500]
        assert r.json()["moved"] == 0

        state = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        print(dev.current_stage.value)

asyncio.run(main())
""").strip()
        assert state == "iqc"
    finally:
        _cleanup(barcode, bucket_number)
