"""Extended Warranty page (2026-09-14): set a Warranty Type on an already-sold
device, then extend it out via the Update modal's date field.

No new table — everything lives on the existing Sale row (Sale.sold_at =
Warranty Starts, Sale.warranty_expires_at = Warranty Stops, Sale.warranty_days
= running day count). These tests seed a Device + a $0-warranty Sale directly,
drive the real HTTP endpoints, and read the result back from the DB.
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


def _seed_sold_device(barcode):
    """Device + a Sale with no warranty on file yet (warranty_type='none').
    Prints the new Sale's id."""
    out = _run(f"""
import asyncio, sys, uuid
sys.path.insert(0, r"{ROOT}")
from datetime import datetime, timedelta
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.sales import Sale

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.sold)
        db.add(dev)
        await db.flush()
        sold_at = datetime.utcnow() - timedelta(days=5)
        sale_number = "ITSEW" + uuid.uuid4().hex[:12].upper()  # fits VARCHAR(20)
        sale = Sale(sale_number=sale_number, device_id=dev.id, sale_price=5000,
                    sold_at=sold_at, warranty_type="none")
        db.add(sale)
        await db.commit()
        print(sale.id)

asyncio.run(main())
""")
    return out


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
            dev.is_active = False
        await db.commit()

asyncio.run(main())
""")


def _read_sale(sale_id):
    """Print warranty_type,warranty_days,warranty_expires_at(iso) for a Sale id."""
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.sales import Sale

async def main():
    async with AsyncSessionLocal() as db:
        sale = (await db.execute(select(Sale).where(Sale.id == "{sale_id}"))).scalar_one()
        print(sale.warranty_type, sale.warranty_days,
              sale.warranty_expires_at.isoformat() if sale.warranty_expires_at else "None")

asyncio.run(main())
""")


def test_table_shows_warranty_left_and_links_tag_number(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    barcode = f"ITEWLFT{suffix}"
    _seed_sold_device(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or ""
        app_client.post(
            "/extended-warranty/set",
            data={"csrf_token": csrf, "barcode": barcode, "warranty_type": "30_days"},
            follow_redirects=False,
        )

        html = app_client.get("/extended-warranty").text
        # Warranty Left column header sits directly before Warranty (in days)
        # in the table (the Set Warranty form above it also has a "Warranty
        # (in days)" label, so this checks the exact table header, not just
        # presence anywhere on the page).
        assert "<th>Warranty Left</th><th>Warranty (in days)</th>" in html
        assert f'<a href="/devices/{barcode}"' in html
        # Fresh 30-day warranty — comfortably not expiring soon.
        assert "bg-success" in html
    finally:
        _cleanup(barcode)


def test_set_warranty_computes_days_and_expiry(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    barcode = f"ITEWSET{suffix}"
    sale_id = _seed_sold_device(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or ""

        r = app_client.post(
            "/extended-warranty/set",
            data={"csrf_token": csrf, "barcode": barcode, "warranty_type": "30_days"},
            follow_redirects=False,
        )
        assert r.status_code == 302, r.text[:400]
        assert "success" in r.headers.get("location", ""), r.headers.get("location")

        wtype, days, expiry = _read_sale(sale_id).split(" ", 2)
        assert wtype == "30_days"
        assert days == "30", f"expected 30 warranty_days, got {days}"
        assert expiry != "None"

        # Page renders the new row.
        page = app_client.get("/extended-warranty").text
        assert barcode in page
    finally:
        _cleanup(barcode)


def test_update_modal_extends_warranty_and_adds_days(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    barcode = f"ITEWEXT{suffix}"
    sale_id = _seed_sold_device(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or ""

        # Give it a 30-day warranty first.
        app_client.post(
            "/extended-warranty/set",
            data={"csrf_token": csrf, "barcode": barcode, "warranty_type": "30_days"},
            follow_redirects=False,
        )
        _wtype, _days, expiry_iso = _read_sale(sale_id).split(" ", 2)
        from datetime import datetime, timedelta
        current_expiry = datetime.fromisoformat(expiry_iso)
        new_expiry = current_expiry + timedelta(days=15)

        r = app_client.post(
            f"/extended-warranty/{sale_id}/update",
            data={
                "csrf_token": csrf,
                "extended_warranty": new_expiry.strftime("%Y-%m-%d"),
                "notes": "test extension",
            },
        )
        assert r.status_code == 200, r.text[:400]
        payload = r.json()
        assert payload["ok"] is True
        assert payload["warranty_days"] == 45, payload  # 30 + 15

        wtype, days, expiry = _read_sale(sale_id).split(" ", 2)
        assert days == "45", f"expected 45 warranty_days after extension, got {days}"
    finally:
        _cleanup(barcode)


def test_update_modal_rejects_a_date_not_after_current_expiry(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    barcode = f"ITEWBAD{suffix}"
    sale_id = _seed_sold_device(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or ""

        app_client.post(
            "/extended-warranty/set",
            data={"csrf_token": csrf, "barcode": barcode, "warranty_type": "30_days"},
            follow_redirects=False,
        )
        _wtype, _days, expiry_iso = _read_sale(sale_id).split(" ", 2)
        from datetime import datetime
        current_expiry = datetime.fromisoformat(expiry_iso)

        r = app_client.post(
            f"/extended-warranty/{sale_id}/update",
            data={
                "csrf_token": csrf,
                "extended_warranty": current_expiry.strftime("%Y-%m-%d"),  # same date, not after
                "notes": "",
            },
        )
        assert r.status_code == 400, r.text[:400]
    finally:
        _cleanup(barcode)
