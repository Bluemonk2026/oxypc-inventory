"""Inventory Manager (/stock) — Return Stock table (2026-09-01):

 - New table at the bottom of /stock listing devices with Device.return_status
   True whose most recent Return has approval_status='approved'. Columns:
   Tag Number, Model, CPU, RAM, Storage, Current Stage, Reason, Condition,
   Complaint, Repair Cost, Labour Cost, Part Cost.
 - POST /stock/return-stock/assign-bucket — bulk-assigns selected tags to a
   Bucket (create-or-reuse by name, case-insensitive), flags it
   is_customer_return so the Buckets/Cartons table shows a "Customer Return"
   label under the bucket name.
 - POST /stock/return-stock/{barcode}/verify — saves Repair Cost + Labour
   Cost onto the device's most recent approved Return row.
 - POST /stock/return-stock/{barcode}/complete — creates a new Sale reusing
   the original sale's customer/payment details, moves the device to `sold`,
   and clears Device.return_status so it drops out of this table.
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


def _seed_returned_device(barcode):
    """A device with an approved Return sitting back at `iqc`, plus the
    original Sale it was returned from (so 'Complete' has customer details to
    copy)."""
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.sales import Sale, Return

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     cpu="Intel Core i5-8250U", ram_gb=8, hdd_summary="512GB_SSD",
                     current_stage=DeviceStage.iqc, return_status=True, device_price=15000)
        db.add(dev)
        await db.flush()
        sale = Sale(sale_number="SALEIT{barcode[-6:]}", device_id=dev.id, sale_price=20000,
                    customer_name="Original Customer", customer_phone="9998887777",
                    customer_state="Delhi", payment_mode="Cash")
        db.add(sale)
        await db.flush()
        ret = Return(sale_id=sale.id, device_id=dev.id, reason="Not working",
                     condition_on_return="Minor Damage", complaint_text="Screen flicker",
                     approval_status="approved", warranty_status="out_of_warranty")
        db.add(ret)
        await db.commit()
        print(dev.id)

asyncio.run(main())
""")


def _cleanup_device(barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device, StageMovement
from models.sales import Sale, Return
from models.bucket import Bucket

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for r in (await db.execute(select(Return).where(Return.device_id == dev.id))).scalars().all():
                await db.delete(r)
            for s in (await db.execute(select(Sale).where(Sale.device_id == dev.id))).scalars().all():
                await db.delete(s)
            for m in (await db.execute(select(StageMovement).where(
                    StageMovement.device_id == dev.id))).scalars().all():
                await db.delete(m)
            if dev.bucket_id:
                bkt = (await db.execute(select(Bucket).where(Bucket.id == dev.bucket_id))).scalar_one_or_none()
                if bkt:
                    await db.delete(bkt)
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
""")


def test_return_stock_table_renders_row(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITRSTOCK{suffix}"
    _seed_returned_device(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get("/stock", follow_redirects=True).text
        assert 'id="returnStockTable"' in html
        assert barcode in html
        assert "Not working" in html
        assert "Minor Damage" in html
        assert "Screen flicker" in html
        # out_of_warranty with zero spare-part consumption -> Part Cost shows 0.00, not em-dash
        row = html.split(f'value="{barcode}"', 1)[1].split("</tr>", 1)[0]
        assert "rs-verify-btn" in row
        assert "rs-complete-btn" in row
        assert ">0.00<" in row  # Part Cost cell: out_of_warranty + zero consumption
    finally:
        _cleanup_device(barcode)


def test_assign_bucket_creates_bucket_and_flags_customer_return(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITRSBKT{suffix}"
    _seed_returned_device(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"
        bucket_name = f"ReturnCarton{suffix}"

        r = app_client.post("/stock/return-stock/assign-bucket", data={
            "csrf_token": csrf, "barcodes": barcode, "bucket_name": bucket_name,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True

        buckets = app_client.get("/api/buckets?status=stock_in").json()
        match = next((b for b in buckets if b["bucket_number"] == body["bucket_number"]), None)
        assert match, "created bucket not found via /api/buckets"
        assert match["is_customer_return"] is True
        assert match["name"] == bucket_name
    finally:
        _cleanup_device(barcode)


def test_verify_saves_repair_and_labour_cost(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITRSVFY{suffix}"
    _seed_returned_device(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post(f"/stock/return-stock/{barcode}/verify", data={
            "csrf_token": csrf, "repair_cost": "1500.50", "labour_cost": "500",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["repair_cost"] == "1500.50"
        assert body["labour_cost"] == "500.00" or body["labour_cost"] == "500"

        html = app_client.get("/stock", follow_redirects=True).text
        assert "1500.50" in html
    finally:
        _cleanup_device(barcode)


def test_complete_creates_sale_with_copied_customer_details_and_clears_return_status(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITRSCPL{suffix}"
    _seed_returned_device(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post(f"/stock/return-stock/{barcode}/complete", data={"csrf_token": csrf})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["sale_number"]

        state = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.sales import Sale

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        sales = (await db.execute(select(Sale).where(Sale.device_id == dev.id)
                 .order_by(Sale.sold_at.desc()))).scalars().all()
        newest = sales[0]
        print(dev.current_stage.value)
        print(dev.return_status)
        print(newest.customer_name)
        print(newest.customer_phone)
        print(newest.payment_mode)
        print(len(sales))

asyncio.run(main())
""").splitlines()
        assert state[0] == "sold"
        assert state[1] == "False"
        assert state[2] == "Original Customer"
        assert state[3] == "9998887777"
        assert state[4] == "Cash"
        assert state[5] == "2"  # original sale + new re-sale

        # And it drops out of the Return Stock table now that return_status is False.
        html = app_client.get("/stock", follow_redirects=True).text
        row_marker = f'value="{barcode}"'
        assert row_marker not in html
    finally:
        _cleanup_device(barcode)
