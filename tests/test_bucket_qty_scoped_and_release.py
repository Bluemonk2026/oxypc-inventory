"""Production Manager page:
 - Bucket Allocation tab's "Bucket Qty" column now counts only devices at
   current_stage=trc_production for that bucket (not every active device
   ever linked to it, which double-counted an earlier, unrelated intake
   that happened to reuse the same bucket) — and buckets with zero such
   devices are excluded from the tab entirely (GET /api/buckets?with_stage=).
 - "Buckets in Repair Line" tab's Action column: "Assign to Engineer" is
   gone, replaced by "Release Bucket" (POST /buckets/{id}/release), which
   unmaps every device on the bucket and clears assigned_to_production/
   dept_assigned so the bucket drops out of both tabs.
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


_SEED_MIXED_STAGE_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.bucket import Bucket

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        bucket = Bucket(bucket_number="{bucket_no}", name="ITest Mixed Bucket",
                        assigned_to_production=True, dept_assigned=False)
        db.add(bucket)
        await db.flush()
        in_stage = Device(barcode="{barcode_in}", lot_id=lot.id, brand="X", model="Y",
                          current_stage=DeviceStage.trc_production, bucket_id=bucket.id)
        elsewhere = Device(barcode="{barcode_out}", lot_id=lot.id, brand="X", model="Y",
                           current_stage=DeviceStage.sold, bucket_id=bucket.id)
        db.add(in_stage)
        db.add(elsewhere)
        await db.commit()
        print(bucket.id)

asyncio.run(main())
"""

_SEED_EMPTY_STAGE_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.bucket import Bucket

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        bucket = Bucket(bucket_number="{bucket_no}", name="ITest Zero-in-Stage Bucket",
                        assigned_to_production=True, dept_assigned=False)
        db.add(bucket)
        await db.flush()
        elsewhere = Device(barcode="{barcode_out}", lot_id=lot.id, brand="X", model="Y",
                           current_stage=DeviceStage.sold, bucket_id=bucket.id)
        db.add(elsewhere)
        await db.commit()
        print(bucket.id)

asyncio.run(main())
"""

_CLEANUP_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.bucket import Bucket

async def main():
    async with AsyncSessionLocal() as db:
        for bc in {barcodes}:
            dev = (await db.execute(select(Device).where(Device.barcode == bc))).scalar_one_or_none()
            if dev:
                await db.delete(dev)
        bkt = (await db.execute(select(Bucket).where(Bucket.bucket_number == "{bucket_no}"))).scalar_one_or_none()
        if bkt:
            await db.delete(bkt)
        await db.commit()

asyncio.run(main())
"""


def test_with_stage_scopes_device_count_and_excludes_zero_buckets(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    bucket_no = f"ITBKT{suffix}"
    barcode_in = f"ITINSTAGE{suffix}"
    barcode_out = f"ITOUTSTAGE{suffix}"
    bucket_no2 = f"ITBKT2{suffix}"
    barcode_out2 = f"ITOUTSTAGE2{suffix}"

    _run(_SEED_MIXED_STAGE_SRC.format(root=ROOT, bucket_no=bucket_no, barcode_in=barcode_in, barcode_out=barcode_out))
    _run(_SEED_EMPTY_STAGE_SRC.format(root=ROOT, bucket_no=bucket_no2, barcode_out=barcode_out2))
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)

        data = app_client.get("/api/buckets", params={
            "status": "stock_in", "with_stage": "trc_production",
        }).json()
        by_number = {b["bucket_number"]: b for b in data}

        assert bucket_no in by_number, "bucket with a trc_production device must be included"
        assert by_number[bucket_no]["device_count"] == 1, (
            "device_count must only count the trc_production device, not the sold one too")

        assert bucket_no2 not in by_number, "bucket with zero trc_production devices must be excluded"
    finally:
        _run(_CLEANUP_SRC.format(root=ROOT, barcodes=[barcode_in, barcode_out], bucket_no=bucket_no))
        _run(_CLEANUP_SRC.format(root=ROOT, barcodes=[barcode_out2], bucket_no=bucket_no2))


def test_release_bucket_unmaps_devices_and_clears_flags(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    bucket_no = f"ITRLS{suffix}"
    barcode_a = f"ITRLSA{suffix}"
    barcode_b = f"ITRLSB{suffix}"

    seed = f"""
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
        bucket = Bucket(bucket_number="{bucket_no}", name="ITest Release Bucket",
                        assigned_to_production=True, dept_assigned=True)
        db.add(bucket)
        await db.flush()
        db.add(Device(barcode="{barcode_a}", lot_id=lot.id, brand="X", model="Y",
                      current_stage=DeviceStage.l1, bucket_id=bucket.id))
        db.add(Device(barcode="{barcode_b}", lot_id=lot.id, brand="X", model="Y",
                      current_stage=DeviceStage.l1, bucket_id=bucket.id))
        await db.commit()
        print(bucket.id)

asyncio.run(main())
"""
    bucket_id = _run(seed)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post(f"/buckets/{bucket_id}/release-repair-line", data={"csrf_token": csrf})
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["ok"] is True
        assert body["released"] == 2

        check = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.bucket import Bucket

async def main():
    async with AsyncSessionLocal() as db:
        a = (await db.execute(select(Device).where(Device.barcode == "{barcode_a}"))).scalar_one()
        b = (await db.execute(select(Device).where(Device.barcode == "{barcode_b}"))).scalar_one()
        bkt = (await db.execute(select(Bucket).where(Bucket.bucket_number == "{bucket_no}"))).scalar_one()
        print(a.bucket_id)
        print(b.bucket_id)
        print(bkt.assigned_to_production)
        print(bkt.dept_assigned)

asyncio.run(main())
""")
        lines = check.splitlines()
        assert lines[0] == "None"
        assert lines[1] == "None"
        assert lines[2] == "False"
        assert lines[3] == "False"
    finally:
        _run(_CLEANUP_SRC.format(root=ROOT, barcodes=[barcode_a, barcode_b], bucket_no=bucket_no))


def test_release_button_replaces_assign_to_engineer_in_template():
    src = open(pathlib.Path(ROOT) / "templates" / "lots" / "trc_production.html", encoding="utf-8").read()
    assert "release-bkt-btn" in src
    assert "Release Bucket" in src
    assert "/buckets/'+id+'/release-repair-line" in src
    assert "assign-eng-btn" not in src
    assert "assign-to-engineer" not in src
    assert "Assign to Engineer" not in src
