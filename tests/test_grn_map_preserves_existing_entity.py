"""POST /grn/map (routers/grn.py grn_map, 2026-08-31 fix):

A tag re-entering IQC after Entity Movement's "SOLD TO" change (which sets
Device.entity to a non-default entity and clears grn_number so the tag must
be re-mapped to a GRN) was having that entity silently reverted the moment
it got mapped to a GRN again — the mapping step unconditionally hardcoded
`d.entity = "OxyPC Computers"` for every device it touched, regardless of
what entity was already set. Now it only defaults a BLANK entity (new/
legacy tags that never had one) and leaves an already-set entity alone.
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


def _seed_device_and_grn(barcode, grn_number, entity):
    entity_line = f'dev.entity = "{entity}"' if entity else "pass"
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.grn_import import GRNImport

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.iqc, grn_number=None)
        {entity_line}
        db.add(dev)
        db.add(GRNImport(grn_number="{grn_number}", source="post_iqc", created_by="itest"))
        await db.commit()
        print(str(dev.id))

asyncio.run(main())
""")


def _get_grn_id(grn_number):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.grn_import import GRNImport

async def main():
    async with AsyncSessionLocal() as db:
        g = (await db.execute(select(GRNImport).where(GRNImport.grn_number == "{grn_number}"))).scalar_one()
        print(g.id)

asyncio.run(main())
""")


def _get_device_id(barcode):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        d = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        print(d.id)

asyncio.run(main())
""")


def _device_entity(barcode):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        d = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        print(d.entity or "")

asyncio.run(main())
""")


def _cleanup(barcode, grn_number):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device, StageMovement
from models.grn_import import GRNImport

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for m in (await db.execute(select(StageMovement).where(
                    StageMovement.device_id == dev.id))).scalars().all():
                await db.delete(m)
            await db.delete(dev)
        g = (await db.execute(select(GRNImport).where(GRNImport.grn_number == "{grn_number}"))).scalar_one_or_none()
        if g:
            await db.delete(g)
        await db.commit()

asyncio.run(main())
""")


def test_grn_map_preserves_an_already_set_entity(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITGRNENT{suffix}"
    grn_number = str(uuid.uuid4().int)[:12]
    _seed_device_and_grn(barcode, grn_number, entity="Renew Circuits")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"
        grn_id = _get_grn_id(grn_number)
        device_id = _get_device_id(barcode)

        r = app_client.post("/grn/map", data={
            "csrf_token": csrf, "grn_id": grn_id, "device_ids": device_id,
        }, headers={"x-requested-with": "fetch"})
        assert r.status_code == 200, r.text[:400]
        assert r.json()["ok"] is True

        assert _device_entity(barcode) == "Renew Circuits"
    finally:
        _cleanup(barcode, grn_number)


def test_grn_map_still_defaults_a_blank_entity_to_oxypc(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITGRNBLANK{suffix}"
    grn_number = str(uuid.uuid4().int)[:12]
    _seed_device_and_grn(barcode, grn_number, entity=None)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"
        grn_id = _get_grn_id(grn_number)
        device_id = _get_device_id(barcode)

        r = app_client.post("/grn/map", data={
            "csrf_token": csrf, "grn_id": grn_id, "device_ids": device_id,
        }, headers={"x-requested-with": "fetch"})
        assert r.status_code == 200, r.text[:400]
        assert r.json()["ok"] is True

        assert _device_entity(barcode) == "OxyPC Computers"
    finally:
        _cleanup(barcode, grn_number)
