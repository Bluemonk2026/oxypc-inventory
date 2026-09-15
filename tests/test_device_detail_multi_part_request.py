"""Device Detail — Parts Consumption "Multi Request" (2026-09-15):

Checkboxes on every row that doesn't already carry a request, a "Multi
Request" button in the section header, and one submit raises a "new"
PartRequest for every checked part in a single server round-trip
(routers/part_requests.py create_part_requests_batch) — instead of opening
the Name -> Make -> Model modal once per part. Requests land on Parts
Manager's Part Requests tab exactly the same way a single request does,
since they're the same PartRequest rows.
"""
import json
import pathlib
import re
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


def _seed_device(barcode):
    """A bare L1 device, no IQC — compute_required() flags several parts
    (Keyboard, Screen, Hinge, ...) required=True with no existing request."""
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
                     current_stage=DeviceStage.l1))
        await db.commit()

asyncio.run(main())
""")


def _cleanup(barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.part_request import PartRequest

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for pr in (await db.execute(select(PartRequest).where(
                    PartRequest.device_id == dev.id))).scalars().all():
                await db.delete(pr)
            dev.is_active = False
        await db.commit()

asyncio.run(main())
""")


def test_detail_page_has_checkboxes_and_multi_request_button(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    barcode = f"ITMPR{suffix}"
    _seed_device(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get(f"/devices/{barcode}", follow_redirects=True).text

        assert 'id="pcMultiRequestBtn"' in html
        assert 'id="pcSelectAll"' in html
        assert 'class="pc-select-cb"' in html
        assert 'id="multiPartRequestForm"' in html
        assert f'value="{barcode}"' in html
    finally:
        _cleanup(barcode)


def test_multi_create_raises_a_request_per_selected_part_and_reaches_parts_manager(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    barcode = f"ITMPR2{suffix}"
    _seed_device(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or ""

        parts = [
            {"label": "Keyboard", "category": "Keyboard", "part_id": ""},
            {"label": "Screen", "category": "Screen", "part_id": ""},
        ]
        r = app_client.post(
            "/part-requests/multi-create",
            data={
                "csrf_token": csrf, "barcode": barcode,
                "parts_json": json.dumps(parts), "request_type": "new",
            },
            follow_redirects=False,
        )
        assert r.status_code == 302, r.text[:400]
        location = r.headers.get("location", "")
        assert "2" in location and "raised" in location, location

        # Both PartRequest rows exist for this device, status='requested'.
        check = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.part_request import PartRequest

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        rows = (await db.execute(select(PartRequest).where(PartRequest.device_id == dev.id))).scalars().all()
        print(len(rows))
        for r in sorted(rows, key=lambda x: x.part_name):
            print(r.part_name, r.status, r.request_type, r.qty_requested)

asyncio.run(main())
""")
        lines = check.splitlines()
        assert lines[0] == "2", check
        assert "Keyboard requested new 1" in lines
        assert "Screen requested new 1" in lines

        # Shows up on Parts Manager's Part Requests tab too — same table.
        pm_html = app_client.get("/spare-parts", follow_redirects=True).text
        assert barcode in pm_html
    finally:
        _cleanup(barcode)


def test_multi_create_rejects_empty_selection(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    barcode = f"ITMPR3{suffix}"
    _seed_device(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or ""

        r = app_client.post(
            "/part-requests/multi-create",
            data={"csrf_token": csrf, "barcode": barcode, "parts_json": "[]", "request_type": "new"},
        )
        assert r.status_code == 400
    finally:
        _cleanup(barcode)


def test_rows_with_an_existing_request_have_no_checkbox(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    barcode = f"ITMPR4{suffix}"
    _seed_device(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or ""

        # Raise a request for Keyboard first, through the same batch endpoint.
        app_client.post(
            "/part-requests/multi-create",
            data={
                "csrf_token": csrf, "barcode": barcode,
                "parts_json": json.dumps([{"label": "Keyboard", "category": "Keyboard", "part_id": ""}]),
                "request_type": "new",
            },
        )

        html = app_client.get(f"/devices/{barcode}", follow_redirects=True).text
        # The PNA checkbox also carries data-part-name="Keyboard" (it's
        # rendered for every row regardless of request status) — check for
        # the Multi Request checkbox specifically (class="pc-select-cb"),
        # gated on the row having no request, which Keyboard now does.
        assert not re.search(r'pc-select-cb"[^>]*data-part-name="Keyboard"', html)
        # Parts Consumption's Action column shows the "Requested" status badge
        # for it now instead.
        assert '<span class="badge bg-warning text-dark">Requested' in html
    finally:
        _cleanup(barcode)
