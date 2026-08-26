"""Stress Test page: new "L1/L2 Engineer" column (after Lot) shows the most
recent L1/L2 engineer who worked on that tag, derived from WorkOrder
(stage="l1", latest assigned_at) — the same resolution routers/repair.py
already uses for its own "assigned to me" queries."""
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
from models.device import Device, DeviceStage
from models.lot import Lot
from models.work_order import WorkOrder

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.qc_check)
        db.add(dev)
        await db.flush()
        # Two WorkOrders, most recent should win.
        db.add(WorkOrder(work_id="ITWO1{suffix}", device_id=dev.id, barcode=dev.barcode,
                         stage="l1", assigned_name="Older Engineer", status="completed"))
        await db.flush()
        db.add(WorkOrder(work_id="ITWO2{suffix}", device_id=dev.id, barcode=dev.barcode,
                         stage="l1", assigned_name="Newer Engineer", status="pending"))
        await db.commit()

asyncio.run(main())
"""

_CLEANUP_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.work_order import WorkOrder

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            wos = (await db.execute(select(WorkOrder).where(WorkOrder.device_id == dev.id))).scalars().all()
            for wo in wos:
                await db.delete(wo)
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
"""


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def test_l1l2_engineer_column_shows_most_recent_assignment(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITESTQC{suffix}"

    _run(_SEED_SRC.format(root=ROOT, barcode=barcode, suffix=suffix))
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get("/qc", follow_redirects=True).text

        assert "<th>L1/L2 Engineer</th>" in html
        assert html.index("<th>Lot</th>") < html.index("<th>L1/L2 Engineer</th>") < html.index("<th>Brand</th>")

        row = html.split(barcode, 1)[1].split("</tr>", 1)[0]
        assert "Newer Engineer" in row
        assert "Older Engineer" not in row
    finally:
        _run(_CLEANUP_SRC.format(root=ROOT, barcode=barcode))
