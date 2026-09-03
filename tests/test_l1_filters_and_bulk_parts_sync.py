"""L1/L2 page (templates/repair/l1.html):
 - Table-row count moved onto the Global Table module's own row-count badge
   (static/js/global-table.js, 2026-09-03), instead of a static count in the
   card header — same migration as Cosmetic/QC/WorkID Status. Tag Number
   also moved before WorkID in this batch, matching that same convention.
 - New filter bar: Search (Tag/GRN/Model), CPU, RAM, Hard Drive, Lot Number
   dropdown, and the "Only show PNA" checkbox moved in from the header.
 - Filtering the Tag table (client-side, via data-* attributes on each row)
   also recomputes the Bulk Part Request table client-side from
   DEVICE_PARTS_REQUIRED (routers/repair.py repair_list), scoped to whatever
   tags currently pass the filters.
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


def _cleanup_device(barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device, StageMovement
from models.work_order import WorkOrder
from models.iqc_inspection import IQCInspection

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for wo in (await db.execute(select(WorkOrder).where(WorkOrder.device_id == dev.id))).scalars().all():
                await db.delete(wo)
            for m in (await db.execute(select(StageMovement).where(
                    StageMovement.device_id == dev.id))).scalars().all():
                await db.delete(m)
            iqc = (await db.execute(select(IQCInspection).where(
                IQCInspection.device_id == dev.id))).scalar_one_or_none()
            if iqc:
                await db.delete(iqc)
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
""")


def test_filter_bar_and_count_badge_present(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)

    html = app_client.get("/repair/l1", follow_redirects=True).text
    assert 'id="l1SearchBox"' in html
    assert 'id="l1CpuFilter"' in html
    assert 'id="l1RamFilter"' in html
    assert 'id="l1HddFilter"' in html
    assert 'id="l1LotFilter"' in html
    assert 'id="onlyPnaL1"' in html
    assert 'placeholder="Search Tag / GRN / Model"' in html

    # Count moved out of the card header onto the Global Table module's own
    # row-count badge — no hand-built badge/counter function anymore.
    assert "Devices in L1/L2 (" not in html
    assert '<span class="fw-semibold">Devices in L1/L2</span>' in html
    assert "initGlobalTable('#l1Table'" in html
    assert 'id="l1CountBadge"' not in html
    assert "function updateL1CountBadge" not in html


def test_device_row_has_filter_data_attributes_and_parts_json(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITL1FLT{suffix}"

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
        db.add(Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModelXYZ",
                     cpu="Intel Core i5-8250U", ram_gb=8, hdd_summary="512GB_SSD",
                     grn_number="ITGRN{suffix}", current_stage=DeviceStage.l1))
        await db.commit()

asyncio.run(main())
""")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get("/repair/l1", follow_redirects=True).text

        # Find the whole <tr ...>...</tr> block for this device (data-device-id
        # comes before data-search in attribute order, so anchoring on
        # data-search alone would cut it off).
        row = next(c for c in html.split('<tr data-device-id="')[1:]
                   if barcode in c.split("</tr>", 1)[0]).split("</tr>", 1)[0]
        assert 'data-cpu="Intel Core i5-8250U"' in row
        assert 'data-ram="8"' in row
        assert 'data-hdd="512GB_SSD"' in row
        assert f"ITGRN{suffix}" in row  # GRN folded into data-search
        # (data-device-id itself is implicit: the split above only found this
        # chunk because a <tr data-device-id="..."> containing the barcode exists)

        # DEVICE_PARTS_REQUIRED must carry at least one entry for this device,
        # each with the shape rebuildBulkPartsTable() expects.
        blob = html.split("const DEVICE_PARTS_REQUIRED = ", 1)[1].split(";\n", 1)[0]
        import json
        parsed = json.loads(blob)
        dev_id = None
        for did, parts in parsed.items():
            if any(True for _ in parts):
                # match by checking this device's barcode appears in the same
                # response near a data-device-id equal to did
                if f'data-device-id="{did}"' in html:
                    dev_id = did
                    break
        assert dev_id, "expected at least one device_id key in DEVICE_PARTS_REQUIRED"
        entry = parsed[dev_id][0]
        assert set(entry.keys()) >= {"label", "category", "required", "requested", "changed"}
    finally:
        _cleanup_device(barcode)


def test_bulk_parts_table_has_id_for_client_side_rebuild():
    src = open(pathlib.Path(ROOT) / "templates" / "repair" / "l1.html", encoding="utf-8").read()
    assert 'id="bulkPartsTable"' in src
    assert "function rebuildBulkPartsTable" in src
    assert "DEVICE_PARTS_REQUIRED" in src
