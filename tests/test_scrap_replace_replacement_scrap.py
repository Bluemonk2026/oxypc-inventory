"""Scrap Products ("Tags Scrapped") — Replace button for Replacement Scrap
tags (2026-09-02):

A device that reached Scrap Products with l34_status='Replacement Scrap'
shows ONLY a "Replace" button in the Action column (no Verify/Sell/View).
That button opens a modal to search (GET /devices/api/search-tags) and
select a replacement tag, showing its Stage/Tag Number/Lot Number/Make/
Model/CPU/RAM/Hard Drive/Grade/Device Price. Submitting
(POST /scrap-products/{barcode}/set-replacement) stores the pick on
Device.replace_with_barcode, rendered as "(Replace with <link>)" beneath
the scrapped tag number.
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


def _seed_scrap_device(barcode, l34_status="Replacement Scrap"):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage, DeviceGrade

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ScrapBrand", model="ScrapModel",
                     current_stage=DeviceStage.scrap_for_sale, grade=DeviceGrade.scrap,
                     l34_status="{l34_status}")
        db.add(dev)
        await db.commit()
        print(dev.id)

asyncio.run(main())
""")


def _seed_plain_device(barcode):
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
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ReplBrand", model="ReplModel",
                     cpu="i5", ram_gb=8, storage_gb=256, storage_type="SSD",
                     current_stage=DeviceStage.stock_in)
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
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
""")


def test_replacement_scrap_shows_only_replace_button(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITSCRRS{suffix}"
    _seed_scrap_device(barcode, "Replacement Scrap")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get("/scrap-products", follow_redirects=True).text
        assert barcode in html
        idx = html.index(barcode)
        row = html[idx:idx + 3000]
        assert "openReplaceModal" in row
        assert "Verify" not in row.split("</tr>")[0]
        assert "btn-success py-0 px-2\"><i class=\"bi bi-cart-plus" not in row.split("</tr>")[0]
    finally:
        _cleanup(barcode)


def test_normal_scrap_keeps_existing_action_buttons(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITSCRNS{suffix}"
    _seed_scrap_device(barcode, "Normal Scrap")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get("/scrap-products", follow_redirects=True).text
        idx = html.index(barcode)
        row = html[idx:idx + 3000]
        assert "openReplaceModal" not in row.split("</tr>")[0]
        assert "openVerifyModal" in row.split("</tr>")[0]
    finally:
        _cleanup(barcode)


def test_search_tags_endpoint_returns_matching_device_details(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITSCRSRCH{suffix}"
    _seed_plain_device(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        r = app_client.get(f"/devices/api/search-tags?q={barcode[-8:]}")
        assert r.status_code == 200
        data = r.json()
        matches = [x for x in data["results"] if x["barcode"] == barcode]
        assert len(matches) == 1
        m = matches[0]
        assert m["make"] == "ReplBrand"
        assert m["model"] == "ReplModel"
        assert m["cpu"] == "i5"
        assert m["ram"] == "8 GB"
        assert m["storage"] == "256 GB SSD"
    finally:
        _cleanup(barcode)


def test_set_replacement_stores_and_renders_link(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    scrap_barcode = f"ITSCRSET{suffix}"
    repl_barcode = f"ITSCRREPL{suffix}"
    _seed_scrap_device(scrap_barcode, "Replacement Scrap")
    _seed_plain_device(repl_barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post(f"/scrap-products/{scrap_barcode}/set-replacement",
                            data={"csrf_token": csrf, "replacement_barcode": repl_barcode})
        assert r.status_code == 200, r.text[:400]
        assert r.json()["ok"] is True

        html = app_client.get("/scrap-products", follow_redirects=True).text
        idx = html.index(scrap_barcode)
        row = html[idx:idx + 800]
        assert "Replace with" in row
        assert repl_barcode in row
    finally:
        _cleanup(scrap_barcode)
        _cleanup(repl_barcode)


def test_set_replacement_rejects_unknown_tag(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    scrap_barcode = f"ITSCRBAD{suffix}"
    _seed_scrap_device(scrap_barcode, "Replacement Scrap")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post(f"/scrap-products/{scrap_barcode}/set-replacement",
                            data={"csrf_token": csrf, "replacement_barcode": "NOSUCHTAG"})
        assert r.status_code == 404
        assert r.json()["ok"] is False
    finally:
        _cleanup(scrap_barcode)
