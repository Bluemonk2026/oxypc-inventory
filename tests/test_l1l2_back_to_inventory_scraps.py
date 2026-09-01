"""L1/L2 Repair page — "Back to Inventory" (renamed from "Back to Production",
2026-09-02):

When L3/L4 Status is Normal Scrap or Replacement Scrap, this button (only
ever rendered for those two statuses) used to send the device to
current_stage=scrapped only — which landed it on Production Manager's
"Scrap Products from Repair Line" table, an intermediate stop. It now also
sets grade=scrap and moves to current_stage=scrap_for_sale, landing directly
on the "Tags Scrapped" page (/scrap-products), which requires BOTH.
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


def _seed_l34_scrap_device(barcode, l34_status):
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
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="X", model="Y",
                     current_stage=DeviceStage.l1, l34_status="{l34_status}")
        db.add(dev)
        await db.commit()
        print(dev.id)

asyncio.run(main())
""")


def _cleanup(barcode):
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
            for m in (await db.execute(select(StageMovement).where(
                    StageMovement.device_id == dev.id))).scalars().all():
                await db.delete(m)
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
""")


def test_button_renamed_to_back_to_inventory(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITL34BTN{suffix}"
    _seed_l34_scrap_device(barcode, "Normal Scrap")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get("/repair/l1", follow_redirects=True).text
        assert "Back to Inventory" in html
        assert "Back to Production" not in html
    finally:
        _cleanup(barcode)


def test_normal_scrap_lands_on_tags_scrapped_page(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITL34NS{suffix}"
    device_id = _seed_l34_scrap_device(barcode, "Normal Scrap")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post("/repair/back-to-production",
                            data={"csrf_token": csrf, "device_id": device_id}, follow_redirects=False)
        assert r.status_code == 302, r.text[:400]

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
        print(dev.grade.value if dev.grade else "None")

asyncio.run(main())
""").splitlines()
        assert state[0] == "scrap_for_sale"
        assert state[1] == "scrap"

        # And it now actually shows up on the Tags Scrapped page.
        scrap_html = app_client.get("/scrap-products", follow_redirects=True).text
        assert barcode in scrap_html
    finally:
        _cleanup(barcode)


def test_replacement_scrap_also_lands_on_tags_scrapped_page(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITL34RS{suffix}"
    device_id = _seed_l34_scrap_device(barcode, "Replacement Scrap")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post("/repair/back-to-production",
                            data={"csrf_token": csrf, "device_id": device_id}, follow_redirects=False)
        assert r.status_code == 302

        scrap_html = app_client.get("/scrap-products", follow_redirects=True).text
        assert barcode in scrap_html
    finally:
        _cleanup(barcode)
