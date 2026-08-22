"""Final QC's Bucket field is a free-text Bucket Name, not a dropdown of
existing buckets:
  - a name that doesn't exist yet auto-creates a Bucket
  - submitting it clears bucket_id from every OTHER device linked to that
    bucket EXCEPT ones already at Final QC Pass/Fail Hold, so several tags
    decided into the same name keep accumulating instead of kicking each
    other out, while anything stale (sold/scrapped/mid-repair from an
    unrelated earlier use of the same name) gets swept clean
"""
import pathlib
import subprocess
import sys
import uuid

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
        bucket = Bucket(bucket_number="{bucket_no}", name="{bucket_name}")
        db.add(bucket)
        await db.flush()
        stale = Device(barcode="{barcode_stale}", lot_id=lot.id, brand="X", model="Y",
                       current_stage=DeviceStage.sold, bucket_id=bucket.id)
        held = Device(barcode="{barcode_held}", lot_id=lot.id, brand="X", model="Y",
                      current_stage=DeviceStage.final_qc_pass_hold, bucket_id=bucket.id)
        new_dev = Device(barcode="{barcode_new}", lot_id=lot.id, brand="X", model="Y",
                         current_stage=DeviceStage.final_qc)
        db.add(stale)
        db.add(held)
        db.add(new_dev)
        await db.commit()

asyncio.run(main())
"""

_CHECK_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.bucket import Bucket

async def main():
    async with AsyncSessionLocal() as db:
        bucket = (await db.execute(select(Bucket).where(Bucket.name == "{bucket_name}"))).scalar_one()
        stale = (await db.execute(select(Device).where(Device.barcode == "{barcode_stale}"))).scalar_one()
        held = (await db.execute(select(Device).where(Device.barcode == "{barcode_held}"))).scalar_one()
        new_dev = (await db.execute(select(Device).where(Device.barcode == "{barcode_new}"))).scalar_one()
        print("stale.bucket_id=" + str(stale.bucket_id))
        print("held.bucket_id=" + str(held.bucket_id))
        print("new_dev.bucket_id=" + str(new_dev.bucket_id))
        print("bucket.id=" + str(bucket.id))
        for d in (stale, held, new_dev):
            d.is_active = False
        await db.commit()

asyncio.run(main())
"""

_NEW_NAME_CHECK_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.bucket import Bucket
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        bucket = (await db.execute(select(Bucket).where(Bucket.name == "{bucket_name}"))).scalar_one_or_none()
        print("bucket_exists=" + str(bucket is not None))
        if bucket:
            d = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
            print("device.bucket_id_matches=" + str(d.bucket_id == bucket.id))
            d.is_active = False
            bucket_number = bucket.bucket_number
            from sqlalchemy import delete as _delete
            await db.commit()

asyncio.run(main())
"""


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def _lines(out):
    return dict(l.split("=", 1) for l in out.splitlines() if "=" in l)


def test_submitting_a_bucket_name_sweeps_stale_but_keeps_held_devices(app_client, make_user):  # noqa: F811
    bucket_name = f"ITESTBKT{uuid.uuid4().hex[:6]}"
    bucket_no = f"BKTFQC{uuid.uuid4().hex[:6]}"
    barcode_stale = f"ITESTSTALE{uuid.uuid4().hex[:6]}"
    barcode_held = f"ITESTHELD{uuid.uuid4().hex[:6]}"
    barcode_new = f"ITESTNEW{uuid.uuid4().hex[:6]}"

    _run(_SEED_SRC.format(root=ROOT, bucket_no=bucket_no, bucket_name=bucket_name,
                          barcode_stale=barcode_stale, barcode_held=barcode_held,
                          barcode_new=barcode_new))

    username, password = make_user("admin")
    _login(app_client, username, password)
    csrf = app_client.cookies.get("csrf_token") or "dummy"

    r = app_client.post("/cosmetic/advance", data={
        "csrf_token": csrf, "barcode": barcode_new, "bucket_name": bucket_name,
        "final_qc_status": "pass", "grade": "A",
    }, follow_redirects=False)
    assert r.status_code == 302, r.text[:500]

    out = _lines(_run(_CHECK_SRC.format(root=ROOT, bucket_name=bucket_name,
                                        barcode_stale=barcode_stale, barcode_held=barcode_held,
                                        barcode_new=barcode_new)))
    assert out["stale.bucket_id"] == "None", "a device not at Pass/Fail Hold must be swept clean"
    assert out["held.bucket_id"] == out["bucket.id"], "a device already at Pass/Fail Hold must not be touched"
    assert out["new_dev.bucket_id"] == out["bucket.id"], "the device just decided must join the bucket"


def test_typing_a_new_bucket_name_creates_the_bucket(app_client, make_user):  # noqa: F811
    bucket_name = f"ITESTNEWBKT{uuid.uuid4().hex[:6]}"
    barcode = f"ITESTNB{uuid.uuid4().hex[:6]}"

    seed = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        d = Device(barcode="{barcode}", lot_id=lot.id, brand="X", model="Y",
                   current_stage=DeviceStage.final_qc)
        db.add(d)
        await db.commit()

asyncio.run(main())
""".format(root=ROOT, barcode=barcode)
    _run(seed)

    username, password = make_user("admin")
    _login(app_client, username, password)
    csrf = app_client.cookies.get("csrf_token") or "dummy"

    r = app_client.post("/cosmetic/advance", data={
        "csrf_token": csrf, "barcode": barcode, "bucket_name": bucket_name,
        "final_qc_status": "pass", "grade": "A",
    }, follow_redirects=False)
    assert r.status_code == 302, r.text[:500]

    out = _lines(_run(_NEW_NAME_CHECK_SRC.format(root=ROOT, bucket_name=bucket_name, barcode=barcode)))
    assert out["bucket_exists"] == "True"
    assert out["device.bucket_id_matches"] == "True"
