"""Inventory Manager (/stock) — Buckets/Cartons table scoped to Stock In
(2026-09-02):

The table previously showed every bucket at status=stock_in regardless of
where its tags actually were — a bucket already moved on (e.g. its tags sent
to Production) still lingered here. loadBucketTable() now passes
with_stage=stock_in, so /api/buckets drops any bucket with zero active
devices actually at that stage — same pattern already used by Production
Manager's Bucket Allocation tab (with_stage=trc_production).

Exception: an is_customer_return bucket (Return Stock's Assign Bucket) never
has its tags AT stock_in — they're mid-repair at whatever stage their return
re-entered them at — so it's kept via exempt_customer_return=1, with its Qty
shown as its real (unscoped) device count rather than a misleading 0.
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


def _seed_bucket(barcode, bucket_number, device_stage, is_customer_return=False, bucket_status="stock_in"):
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
        bucket = Bucket(bucket_number="{bucket_number}", name="Test Carton",
                        status="{bucket_status}", is_customer_return={is_customer_return})
        db.add(bucket)
        await db.flush()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="X", model="Y",
                     current_stage=DeviceStage.{device_stage}, bucket_id=bucket.id)
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
from models.device import Device
from models.bucket import Bucket

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            await db.delete(dev)
        bkt = (await db.execute(select(Bucket).where(Bucket.bucket_number == "{bucket_number}"))).scalar_one_or_none()
        if bkt:
            await db.delete(bkt)
        await db.commit()

asyncio.run(main())
""")


def test_bucket_with_tags_still_at_stock_in_shows(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITBKTSI{suffix}"
    bucket_number = f"BKTSI{suffix}"
    _seed_bucket(barcode, bucket_number, "stock_in")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        r = app_client.get("/api/buckets?status=stock_in&with_stage=stock_in&exempt_customer_return=1")
        assert r.status_code == 200
        match = next((b for b in r.json() if b["bucket_number"] == bucket_number), None)
        assert match, "bucket with a tag still at stock_in must show"
        assert match["device_count"] == 1
    finally:
        _cleanup(barcode, bucket_number)


def test_bucket_whose_tag_moved_on_no_longer_shows(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITBKTMOVED{suffix}"
    bucket_number = f"BKTMOVED{suffix}"
    # Bucket status stays stock_in (not yet moved to production as a bucket),
    # but its one device has already advanced past stock_in — e.g. sent
    # straight to iqc some other way.
    _seed_bucket(barcode, bucket_number, "iqc")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        r = app_client.get("/api/buckets?status=stock_in&with_stage=stock_in&exempt_customer_return=1")
        assert r.status_code == 200
        match = next((b for b in r.json() if b["bucket_number"] == bucket_number), None)
        assert match is None, "bucket whose tags moved off stock_in must not show"
    finally:
        _cleanup(barcode, bucket_number)


def test_customer_return_bucket_shows_even_though_its_tag_is_not_at_stock_in(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITBKTCR{suffix}"
    bucket_number = f"BKTCR{suffix}"
    _seed_bucket(barcode, bucket_number, "l1", is_customer_return=True)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        r = app_client.get("/api/buckets?status=stock_in&with_stage=stock_in&exempt_customer_return=1")
        assert r.status_code == 200
        match = next((b for b in r.json() if b["bucket_number"] == bucket_number), None)
        assert match, "is_customer_return bucket must show regardless of its tags' stage"
        # Qty reflects its real (unscoped) device count, not a misleading 0.
        assert match["device_count"] == 1
    finally:
        _cleanup(barcode, bucket_number)


def test_customer_return_bucket_hidden_without_the_exemption_flag(app_client, make_user):  # noqa: F811
    """Confirms the exemption is opt-in — Production Manager's own
    with_stage=trc_production caller (which never passes
    exempt_customer_return) must keep hiding empty buckets exactly as the
    prior batch fixed, not have that undone by this one."""
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITBKTCRNOEX{suffix}"
    bucket_number = f"BKTCRNOEX{suffix}"
    _seed_bucket(barcode, bucket_number, "l1", is_customer_return=True)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        r = app_client.get("/api/buckets?status=stock_in&with_stage=stock_in")
        assert r.status_code == 200
        match = next((b for b in r.json() if b["bucket_number"] == bucket_number), None)
        assert match is None, "without exempt_customer_return, the plain with_stage filter must apply"
    finally:
        _cleanup(barcode, bucket_number)
