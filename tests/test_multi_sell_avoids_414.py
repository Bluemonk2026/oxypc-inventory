"""Ready to Sale Tags — Multi-Sell (2026-09-01 fix):

The Multi-Sell button navigated via `window.location = '/sales/new?barcodes=' +
...` — a GET request with every selected Tag Number crammed into the query
string. A large enough selection (hundreds of tags, e.g. via the Bulk
Upload Tags modal + Select All) could exceed the web server/proxy's max URI
length and throw "414 Request-URI Too Large". Fixed by POSTing the
selection instead (POST /sales/new/prefill, mirroring the pattern the
Multi-Request button on the same page already uses for /dispatch/request)
— a POST body has no such limit.
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


def _seed_device_ready_to_sale(barcode, price="15000"):
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
                     current_stage=DeviceStage.ready_to_sale, device_price={price}))
        await db.commit()

asyncio.run(main())
""")


def _seed_devices_ready_to_sale_bulk(barcodes, price="15000"):
    """One subprocess, one commit for the whole batch — a per-item subprocess
    spawn (one Python interpreter + DB connection each) is far too slow for
    a few hundred rows."""
    codes_literal = repr(list(barcodes))
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
        for bc in {codes_literal}:
            db.add(Device(barcode=bc, lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                         current_stage=DeviceStage.ready_to_sale, device_price={price}))
        await db.commit()

asyncio.run(main())
""")


def _cleanup_device(barcode):
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


def _cleanup_devices_bulk(barcodes):
    codes_literal = repr(list(barcodes))
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select, delete
from database import AsyncSessionLocal
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Device).where(Device.barcode.in_({codes_literal})))
        await db.commit()

asyncio.run(main())
""")


def test_ready_list_multi_sell_posts_a_form_not_a_query_string(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/sales/ready", follow_redirects=True).text
    assert 'id="multiSellForm"' in html
    assert 'action="/sales/new/prefill"' in html
    assert "document.getElementById('multiSellForm').submit();" in html
    # The old GET-navigation-with-query-string approach is gone.
    assert "window.location = '/sales/new?barcodes='" not in html


def test_prefill_post_handles_a_large_selection_without_414(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    # Enough tags that the equivalent GET query string would run well past
    # a typical web server/proxy's default max URI length (~8KB).
    barcodes = [f"ITMS{suffix}{i:04d}" for i in range(300)]
    _seed_devices_ready_to_sale_bulk(barcodes)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post("/sales/new/prefill", data={
            "csrf_token": csrf, "barcodes": ",".join(barcodes), "qty": str(len(barcodes)),
        }, follow_redirects=True)
        assert r.status_code == 200, r.text[:400]
        assert barcodes[0] in r.text
        assert f"{len(barcodes)}" in r.text  # multi_count shown somewhere on the page
    finally:
        _cleanup_devices_bulk(barcodes)


def test_prefill_post_renders_same_as_get_for_the_same_selection(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode_a = f"ITMSPRICEA{suffix}"
    barcode_b = f"ITMSPRICEB{suffix}"
    _seed_device_ready_to_sale(barcode_a, price="10000")
    _seed_device_ready_to_sale(barcode_b, price="20000")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"
        codes = f"{barcode_a},{barcode_b}"

        r_get = app_client.get(f"/sales/new?barcodes={codes}&qty=2", follow_redirects=True)
        r_post = app_client.post("/sales/new/prefill", data={
            "csrf_token": csrf, "barcodes": codes, "qty": "2",
        }, follow_redirects=True)
        assert r_get.status_code == 200
        assert r_post.status_code == 200
        # Both routes share the same rendering logic — the "N tags selected"
        # badge and the prefilled tag list appear identically in both pages.
        assert "2 tags selected" in r_get.text
        assert "2 tags selected" in r_post.text
        assert codes in r_get.text
        assert codes in r_post.text
    finally:
        _cleanup_device(barcode_a)
        _cleanup_device(barcode_b)
