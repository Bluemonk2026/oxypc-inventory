"""A bucket_number is reused across unrelated intakes over time. Two bugs
this exposed, both reported as "assigning a bucket at Final QC / Production
resets an old tag's mapping":

1. _move_bucket_devices_to_trc (routers/buckets.py, shared by "Assign to
   Production" and "Move to Production") had no stage filter — it moved
   EVERY active device sharing that bucket_id to trc_production, including
   ones long since sold/scrapped/mid-repair from a previous intake that
   happened to share the same reused bucket. Now scoped to current_stage ==
   stock_in, the only stage this action is meant to advance from.
2. A device arriving at Final QC now releases any bucket_id it still carries
   from an earlier stage, so a stale leftover assignment can never be the
   thing that gets swept up later.
"""
import pathlib
import subprocess
import sys
import uuid

import pytest

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)

_SEED_SRC = """
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
        bucket = Bucket(bucket_number="{bucket_no}", name="Reused Bucket")
        db.add(bucket)
        await db.flush()
        old = Device(barcode="{barcode_old}", lot_id=lot.id, brand="X", model="Y",
                     current_stage=DeviceStage.{old_stage}, bucket_id=bucket.id)
        fresh = Device(barcode="{barcode_fresh}", lot_id=lot.id, brand="X", model="Y",
                       current_stage=DeviceStage.stock_in, bucket_id=bucket.id)
        db.add(old)
        db.add(fresh)
        await db.commit()
        print(bucket.id)

asyncio.run(main())
"""

_CHECK_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        old = (await db.execute(select(Device).where(Device.barcode == "{barcode_old}"))).scalar_one()
        fresh = (await db.execute(select(Device).where(Device.barcode == "{barcode_fresh}"))).scalar_one()
        print("OLD stage=" + old.current_stage.value)
        print("FRESH stage=" + fresh.current_stage.value)
        old.is_active = False
        fresh.is_active = False
        await db.commit()

asyncio.run(main())
"""

_ADVANCE_STAGE_CHECK_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        d = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        print("stage=" + d.current_stage.value)
        print("bucket_id=" + str(d.bucket_id))
        d.is_active = False
        await db.commit()

asyncio.run(main())
"""


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def test_assign_to_production_does_not_sweep_an_unrelated_old_device(app_client, make_user):  # noqa: F811
    barcode_old = f"ITESTBKTO{uuid.uuid4().hex[:6]}"
    barcode_fresh = f"ITESTBKTF{uuid.uuid4().hex[:6]}"
    bucket_no = f"BKTREUSE{uuid.uuid4().hex[:6]}"

    out = _run(_SEED_SRC.format(root=ROOT, bucket_no=bucket_no, barcode_old=barcode_old,
                                barcode_fresh=barcode_fresh, old_stage="sold"))
    bucket_id = out.splitlines()[-1].strip()

    username, password = make_user("admin")
    _login(app_client, username, password)
    csrf = app_client.cookies.get("csrf_token") or "dummy"

    r = app_client.post(f"/buckets/{bucket_id}/assign-to-production", data={"csrf_token": csrf})
    assert r.status_code == 200, r.text[:500]

    out2 = _run(_CHECK_SRC.format(root=ROOT, barcode_old=barcode_old, barcode_fresh=barcode_fresh))
    lines = dict(l.split("=", 1) for l in out2.splitlines() if "=" in l)
    assert lines["OLD stage"] == "sold", "an unrelated old device must not be swept into trc_production"
    assert lines["FRESH stage"] == "trc_production", "the actual stock_in device in this bucket should still move"


def test_move_to_trc_does_not_sweep_an_unrelated_old_device(app_client, make_user):  # noqa: F811
    """Same fix, the other caller: Inventory Manager's own "Move to
    Production" button (/buckets/{id}/move-to-trc) — most likely the actual
    path in the reported bug, since assign-to-production had a separate,
    always-500 NameError bug (fixed alongside this) that would have made it
    impossible to reach the sweep through that route at all."""
    barcode_old = f"ITESTBKTO{uuid.uuid4().hex[:6]}"
    barcode_fresh = f"ITESTBKTF{uuid.uuid4().hex[:6]}"
    bucket_no = f"BKTREUSE{uuid.uuid4().hex[:6]}"

    out = _run(_SEED_SRC.format(root=ROOT, bucket_no=bucket_no, barcode_old=barcode_old,
                                barcode_fresh=barcode_fresh, old_stage="ready_to_sale"))
    bucket_id = out.splitlines()[-1].strip()

    username, password = make_user("admin")
    _login(app_client, username, password)
    csrf = app_client.cookies.get("csrf_token") or "dummy"

    r = app_client.post(f"/buckets/{bucket_id}/move-to-trc", data={"csrf_token": csrf})
    assert r.status_code == 200, r.text[:500]

    out2 = _run(_CHECK_SRC.format(root=ROOT, barcode_old=barcode_old, barcode_fresh=barcode_fresh))
    lines = dict(l.split("=", 1) for l in out2.splitlines() if "=" in l)
    assert lines["OLD stage"] == "ready_to_sale", "an unrelated old device must not be swept into trc_production"
    assert lines["FRESH stage"] == "trc_production", "the actual stock_in device in this bucket should still move"


def test_device_arriving_at_final_qc_releases_its_stale_bucket(app_client, make_user):  # noqa: F811
    barcode = f"ITESTFQCREL{uuid.uuid4().hex[:6]}"
    bucket_no = f"BKTSTALE{uuid.uuid4().hex[:6]}"

    seed = """
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
        bucket = Bucket(bucket_number="{bucket_no}", name="Stale Bucket")
        db.add(bucket)
        await db.flush()
        d = Device(barcode="{barcode}", lot_id=lot.id, brand="X", model="Y",
                   current_stage=DeviceStage.water_sanding, bucket_id=bucket.id)
        db.add(d)
        await db.commit()

asyncio.run(main())
""".format(root=ROOT, bucket_no=bucket_no, barcode=barcode)
    _run(seed)

    username, password = make_user("admin")
    _login(app_client, username, password)
    csrf = app_client.cookies.get("csrf_token") or "dummy"

    r = app_client.post("/cosmetic/advance", data={"csrf_token": csrf, "barcode": barcode}, follow_redirects=False)
    assert r.status_code == 302, r.text[:500]

    out = _run(_ADVANCE_STAGE_CHECK_SRC.format(root=ROOT, barcode=barcode))
    lines = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    assert lines["stage"] == "final_qc"
    assert lines["bucket_id"] == "None", "arriving at Final QC must clear a stale bucket carried over from an earlier stage"
