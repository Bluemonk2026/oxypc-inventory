"""L1/L2 Bulk Part Request (2026-09-14):

- "Total Requested" (and DEVICE_PARTS_REQUIRED's per-device `requested` flag,
  which the client-side rebuildBulkPartsTable() sums from) used to count only
  PartRequest rows at status='handed_over' — a request JUST raised through
  this same table (status='requested', per routers/repair.py's own
  bulk_part_request()) didn't move the badge at all, which is what led staff
  to re-request the same tags through Device Detail instead, creating real
  duplicate PartRequest rows. Fixed by counting 'requested' OR 'handed_over'
  as "Total Requested" (any OPEN request, not yet confirmed received).
- New/Replace Request buttons were briefly disabled once Total Requested
  reached Total Quantity for that part row (2026-09-14), then reverted the
  same day at the user's request — re-requesting a tag is a valid thing to
  do deliberately, so the buttons stay enabled always.
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


def _seed_device_with_open_keyboard_request(barcode):
    """A bare L1 device with no IQC row (compute_required flags Keyboard
    required=True when iqc is None — services/parts_required.py) plus an
    open (status='requested') PartRequest for Keyboard. Prints the device id."""
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.part_request import PartRequest

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.l1)
        db.add(dev)
        await db.flush()
        db.add(PartRequest(device_id=dev.id, barcode=dev.barcode, stage="l1",
                           part_name="Keyboard", request_type="new",
                           requested_by="itest", status="requested"))
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


def test_open_requested_status_reflected_immediately_in_device_parts_required(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6].upper()
    barcode = f"ITL1OPEN{suffix}"
    dev_id = _seed_device_with_open_keyboard_request(barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get("/repair/l1", follow_redirects=True).text

        blob = html.split("const DEVICE_PARTS_REQUIRED = ", 1)[1].split(";\n", 1)[0]
        import json
        parsed = json.loads(blob)
        assert dev_id in parsed, f"device {dev_id} missing from DEVICE_PARTS_REQUIRED"
        keyboard_entry = next(e for e in parsed[dev_id] if e["label"] == "Keyboard")
        assert keyboard_entry["required"] is True
        assert keyboard_entry["requested"] is True, (
            "a status='requested' PartRequest must mark this device's Keyboard "
            "row as requested immediately, not only once handed_over"
        )
        assert keyboard_entry["changed"] is False
    finally:
        _cleanup(barcode)


def test_repair_router_counts_requested_status_as_open():
    src = (pathlib.Path(ROOT) / "routers" / "repair.py").read_text(encoding="utf-8")
    assert '.status.in_(["requested", "handed_over", "received"])' in src
    assert 'pstatus in ("requested", "handed_over")' in src


def test_bulk_part_request_buttons_are_never_disabled():
    src = (pathlib.Path(ROOT) / "templates" / "repair" / "l1.html").read_text(encoding="utf-8")
    assert "fully_requested" not in src
    assert "fullyRequested" not in src
    assert "disAttr" not in src
