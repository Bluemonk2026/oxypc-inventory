"""2026-09-21: /transfers table's "Stage" column showed StockTransfer.product_stage
— a snapshot taken once at transfer-creation time — so a device that moved
stage AFTER being transferred kept showing its old, stale stage forever.
Fixed the same way lot_number already was in this file (_transfers_list_rows'
own docstring): live-join Device.current_stage instead, falling back to the
snapshot only when the device row is gone.
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


def _seed_transfer_with_stale_snapshot(barcode, snapshot_stage, live_stage):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.stock_transfer import StockTransfer
from utils.timezone import app_now

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="X", model="Y",
                     current_stage=DeviceStage.{live_stage})
        db.add(dev)
        await db.flush()
        st = StockTransfer(device_id=dev.id, move_kind="device", transfer_type="internal",
                           source="transfers_new",
                           from_warehouse="A", to_warehouse="B", barcode="{barcode}",
                           product_stage="{snapshot_stage}", transfer_date=app_now())
        db.add(st)
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
from models.stock_transfer import StockTransfer

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for st in (await db.execute(select(StockTransfer).where(
                    StockTransfer.device_id == dev.id))).scalars().all():
                await db.delete(st)
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
""")


def test_transfers_table_shows_live_stage_not_stale_snapshot(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITTRXSTAGE{suffix}"
    # Snapshot says "iqc" (from transfer-creation time), but the device has
    # since moved on to Ready to Sale — the table must show the live one.
    _seed_transfer_with_stale_snapshot(barcode, "iqc", "ready_to_sale")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get(f"/transfers?q={barcode}", follow_redirects=True).text
        assert barcode in html
        # The filter bar's own search box (value="{{ q }}") also contains the
        # barcode, earlier in the page than the actual table row — search
        # for the barcode's occurrence inside <tbody> specifically.
        tbody_start = html.index("<tbody>")
        row_start = html.index(barcode, tbody_start)
        row = html[max(0, row_start - 500):row_start + 1500]
        assert "Ready to Sale" in row
        assert "Iqc" not in row
    finally:
        _cleanup(barcode)


def test_transfers_export_csv_uses_live_stage_too(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITTRXSTAGE2{suffix}"
    _seed_transfer_with_stale_snapshot(barcode, "iqc", "sold")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        r = app_client.get(f"/transfers/export?q={barcode}")
        assert r.status_code == 200
        text = r.content.decode("utf-8-sig")
        assert barcode in text
        assert "Sold" in text
    finally:
        _cleanup(barcode)
