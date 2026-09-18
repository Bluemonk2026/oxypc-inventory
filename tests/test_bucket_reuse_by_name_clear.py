"""Inventory Manager's "Add to Bucket / Carton" modal, 2026-09-18:

A physical carton gets reused, but /buckets/create previously always minted
a brand-new Bucket row with a fresh bucket_number regardless of what name
was typed — retyping an old carton's name created a second, confusingly
duplicate bucket, never touching the old one's still-mapped tags.

Now: GET /api/buckets/lookup-by-name lets the modal show, as the operator
types, whether that name already belongs to an existing bucket and how many
tags are still mapped to it. An optional "Clear Bucket" button unmaps them
(reuses the existing generic POST /buckets/{id}/release action — devices
untouched, only their bucket_id link removed). Whether or not Clear was
used, POST /buckets/create now reuses that SAME bucket by name (case-
insensitive) instead of creating a duplicate, so newly selected tags join
whatever (if anything) is still there.
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


def _seed_device_and_bucket(barcode, bucket_number, bucket_name):
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
        bucket = Bucket(bucket_number="{bucket_number}", name="{bucket_name}", status="stock_in")
        db.add(bucket)
        await db.flush()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.stock_in, bucket_id=bucket.id)
        db.add(dev)
        await db.commit()
        print(bucket.id)

asyncio.run(main())
""")


def _seed_loose_device(barcode):
    return _run(f"""
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
                     current_stage=DeviceStage.stock_in)
        db.add(dev)
        await db.commit()
        print(dev.id)

asyncio.run(main())
""")


def _device_bucket_id(barcode):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        print(dev.bucket_id or "None")

asyncio.run(main())
""")


def _cleanup(barcodes, bucket_number):
    barcode_list = ", ".join(f'"{b}"' for b in barcodes)
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.bucket import Bucket

async def main():
    async with AsyncSessionLocal() as db:
        for bc in [{barcode_list}]:
            dev = (await db.execute(select(Device).where(Device.barcode == bc))).scalar_one_or_none()
            if dev:
                await db.delete(dev)
        bkt = (await db.execute(select(Bucket).where(Bucket.bucket_number == "{bucket_number}"))).scalar_one_or_none()
        if bkt:
            await db.delete(bkt)
        await db.commit()

asyncio.run(main())
""")


def test_lookup_by_name_not_found_for_unknown_name(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    r = app_client.get("/api/buckets/lookup-by-name?name=NoSuchBucketNameXYZ")
    assert r.status_code == 200
    assert r.json()["found"] is False


def test_lookup_by_name_finds_existing_bucket_with_tag_count(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITBKTLOOKUP{suffix}"
    bucket_number = f"ITBLK{suffix}"
    bucket_name = f"ITest Carton {suffix}"
    _seed_device_and_bucket(barcode, bucket_number, bucket_name)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        r = app_client.get(f"/api/buckets/lookup-by-name?name={bucket_name}")
        body = r.json()
        assert body["found"] is True
        assert body["tag_count"] == 1
        assert body["bucket_number"] == bucket_number
        # Case-insensitive match.
        r2 = app_client.get(f"/api/buckets/lookup-by-name?name={bucket_name.upper()}")
        assert r2.json()["found"] is True
    finally:
        _cleanup([barcode], bucket_number)


def test_create_bucket_reuses_existing_bucket_by_name(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    old_barcode = f"ITREUSEOLD{suffix}"
    new_barcode = f"ITREUSENEW{suffix}"
    bucket_number = f"ITRU{suffix}"
    bucket_name = f"ITest Reuse Carton {suffix}"
    _seed_device_and_bucket(old_barcode, bucket_number, bucket_name)
    _seed_loose_device(new_barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"
        r = app_client.post("/buckets/create", data={
            "csrf_token": csrf, "barcodes": new_barcode, "name": bucket_name,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["reused"] is True
        assert body["bucket_number"] == bucket_number  # same bucket, not a new one

        # Old tag is still in the bucket (nothing silently cleared it) and
        # the newly selected tag joined it — both share the same bucket_id.
        assert _device_bucket_id(old_barcode) == _device_bucket_id(new_barcode)
    finally:
        _cleanup([old_barcode, new_barcode], bucket_number)


def test_clear_bucket_unmaps_old_tags_without_deleting_them(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITCLEAR{suffix}"
    bucket_number = f"ITCLR{suffix}"
    bucket_name = f"ITest Clear Carton {suffix}"
    bucket_id = _seed_device_and_bucket(barcode, bucket_number, bucket_name)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        assert _device_bucket_id(barcode) == bucket_id

        r = app_client.post(f"/buckets/{bucket_id}/release", data={"csrf_token": csrf})
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        assert r.json()["released"] == 1

        # Device itself untouched, just unmapped.
        assert _device_bucket_id(barcode) == "None"

        # Lookup now reports 0 tags for this bucket name.
        lookup = app_client.get(f"/api/buckets/lookup-by-name?name={bucket_name}").json()
        assert lookup["found"] is True
        assert lookup["tag_count"] == 0
    finally:
        _cleanup([barcode], bucket_number)


def test_add_to_bucket_modal_has_reuse_ui(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/stock", follow_redirects=True).text
    assert 'id="bktExistingWarning"' in html
    assert 'id="bktExistingCount"' in html
    assert 'id="bktClearBtn"' in html
    assert '/api/buckets/lookup-by-name' in html
    assert "/buckets/' + bktExistingBucketId + '/release" in html
