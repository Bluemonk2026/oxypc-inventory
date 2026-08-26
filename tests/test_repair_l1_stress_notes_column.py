"""L1/L2 Repair table gets a "Stress Notes" column right after "Repair
Notes", showing device.stress_notes — the failure note the Stress Test
page's Fail action now writes there."""
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

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.l1,
                     stress_notes="Failed: Keyboard, Touchpad — sticky keys")
        db.add(dev)
        await db.commit()

asyncio.run(main())
"""

_CLEANUP_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
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
"""


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def test_stress_notes_column_after_repair_notes(app_client, make_user):  # noqa: F811
    barcode = f"ITESTL1{uuid.uuid4().hex[:6]}"

    _run(_SEED_SRC.format(root=ROOT, barcode=barcode))
    try:
        username, password = make_user("l1_engineer")
        _login(app_client, username, password)
        html = app_client.get("/repair/l1", follow_redirects=True).text

        assert "<th>Stress Notes</th>" in html
        assert html.index("<th>Repair Notes</th>") < html.index("<th>Stress Notes</th>")

        row = html.split(barcode, 1)[1].split("</tr>", 1)[0]
        assert "Failed: Keyboard, Touchpad" in row
    finally:
        _run(_CLEANUP_SRC.format(root=ROOT, barcode=barcode))
