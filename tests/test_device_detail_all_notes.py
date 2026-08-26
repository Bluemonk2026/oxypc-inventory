"""Device Detail gets a consolidated "All Notes" section below Parts
Consumption, surfacing L1/L2 (RepairJob), L3/L4 (Device.repair_notes),
Stress (Device.stress_notes + QCCheck history) and Final QC
(fqc_failure_reason/fqc_pass_notes) — none of the last two were rendered
anywhere on this page before."""
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
from models.repair import RepairJob
from models.qc import QCCheck
from utils.timezone import app_now

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.qc_check,
                     repair_notes="L3/L4 replaced the hinge assembly",
                     stress_notes="Failed: Battery — swells under load",
                     fqc_failure_reason="Screen has a dead pixel cluster")
        db.add(dev)
        await db.flush()
        db.add(RepairJob(device_id=dev.id, stage="L1", engineer_name="ITest Engineer",
                         issue_description="Keyboard sticky keys", resolution="Replaced keyboard",
                         started_at=app_now()))
        db.add(QCCheck(device_id=dev.id, result="fail", attempt_number=1,
                       notes="Failed on first attempt", issues_found="Battery drains fast",
                       checked_at=app_now()))
        await db.commit()

asyncio.run(main())
"""

_CLEANUP_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.repair import RepairJob
from models.qc import QCCheck

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for rep in (await db.execute(select(RepairJob).where(RepairJob.device_id == dev.id))).scalars().all():
                await db.delete(rep)
            for qc in (await db.execute(select(QCCheck).where(QCCheck.device_id == dev.id))).scalars().all():
                await db.delete(qc)
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
"""


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def test_all_notes_section_shows_all_four_note_types(app_client, make_user):  # noqa: F811
    barcode = f"ITESTDD{uuid.uuid4().hex[:6]}"

    _run(_SEED_SRC.format(root=ROOT, barcode=barcode))
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get(f"/devices/{barcode}", follow_redirects=True).text

        assert 'id="all-notes"' in html
        notes_section = html.split('id="all-notes"', 1)[1].split("</div>\n    </div>", 1)[0]

        # L1/L2 — from RepairJob
        assert "Keyboard sticky keys" in notes_section
        assert "Replaced keyboard" in notes_section
        # L3/L4 — from the shared Device.repair_notes field
        assert "L3/L4 replaced the hinge assembly" in notes_section
        # Stress — Device.stress_notes + QCCheck history, previously never rendered
        assert "Failed: Battery" in notes_section
        assert "Failed on first attempt" in notes_section
        assert "Battery drains fast" in notes_section
        # Final QC — previously never rendered anywhere on this page
        assert "Screen has a dead pixel cluster" in notes_section
    finally:
        _run(_CLEANUP_SRC.format(root=ROOT, barcode=barcode))
