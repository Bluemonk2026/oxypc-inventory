"""Part Manager page batch: Consumed tile, the new Parts Consumption tab,
Upload New/Harvest sample-file modals, and the trimmed Add Harvest modal.
"""
import pathlib
import re
import subprocess
import sys
import uuid

import pytest

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def _get_spare_parts(app_client, make_user):
    username, password = make_user("spare_parts_manager")
    _login(app_client, username, password)
    return app_client.get("/spare-parts", follow_redirects=True).text


def test_consumed_tile_is_not_scoped_to_this_month(app_client, make_user):  # noqa: F811
    html = _get_spare_parts(app_client, make_user)
    assert "Consumed This Month" not in html
    assert ">Consumed<" in html


def test_parts_consumption_tab_present_with_search_and_export(app_client, make_user):  # noqa: F811
    """2026-09-18: one row per (tag, part name) instead of one aggregate row
    per tag — "Total Parts Changed"/"Total Parts Amount" (the old device-wide
    aggregate columns, the latter mislabeled — it showed a quantity, not an
    amount) are gone; "Part Name Used"/"Total Part Changed"/"Unit Price"/
    "Total Price" are the new per-part columns."""
    html = _get_spare_parts(app_client, make_user)
    assert 'id="partsConsumptionTab"' in html
    assert 'id="parts-consumption-tab"' in html
    assert "Date Added" in html
    assert "Part Name Used" in html
    assert "Total Part Changed" in html
    assert "Unit Price" in html
    assert "Total Price" in html
    assert "Total Parts Changed" not in html
    assert "Total Parts Amount" not in html
    assert 'id="pcSearch"' in html
    assert "pcFilter()" in html
    # Global Table conversion (2026-09-18).
    assert "initGlobalTable('#partsConsumptionTable'" in html


def test_parts_consumption_splits_into_one_row_per_part_name(app_client, make_user):  # noqa: F811
    """A tag with Keyboard changed once and RAM changed twice must show as
    TWO rows (one per part name), each with its own quantity, unit price,
    and total price — not one aggregate row for the whole tag."""
    suffix = uuid.uuid4().hex[:6].upper()
    barcode = f"ITPC{suffix}"
    keyboard_code = f"ITPCKB{suffix}"
    ram_code = f"ITPCRAM{suffix}"

    seeded = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.spare_parts import SparePart
from models.part_request import PartRequest

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.l1)
        db.add(dev)
        kb = SparePart(part_code="{keyboard_code}", name="ITest Keyboard", category="Keyboard",
                       unit_price=500, qty_in_stock=10)
        ram = SparePart(part_code="{ram_code}", name="ITest RAM", category="RAM",
                        unit_price=1000, qty_in_stock=10)
        db.add(kb)
        db.add(ram)
        await db.flush()
        db.add(PartRequest(device_id=dev.id, barcode="{barcode}", part_id=kb.id, part_name=kb.name,
                           request_type="replace", status="received", qty_handed_over=1))
        db.add(PartRequest(device_id=dev.id, barcode="{barcode}", part_id=ram.id, part_name=ram.name,
                           request_type="replace", status="received", qty_handed_over=1))
        db.add(PartRequest(device_id=dev.id, barcode="{barcode}", part_id=ram.id, part_name=ram.name,
                           request_type="replace", status="received", qty_handed_over=1))
        await db.commit()
        print(str(dev.id))

asyncio.run(main())
""")
    try:
        html = _get_spare_parts(app_client, make_user)
        section = html.split('id="partsConsumptionTab"', 1)[1].split("</table>", 1)[0]
        rows = re.findall(r'<tr data-tag="' + barcode + r'"[^>]*>(.*?)</tr>', section, re.S)
        assert len(rows) == 2, f"expected 2 rows (Keyboard, RAM), got {len(rows)}: {rows}"

        by_part = {}
        for row in rows:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
            # cells[2] is Date Added (2026-09-18) — Part Name Used shifted to 3.
            part_name = re.sub(r"<[^>]+>", "", cells[3]).strip()
            qty = re.sub(r"<[^>]+>", "", cells[4]).strip()
            unit_price = re.sub(r"<[^>]+>", "", cells[5]).strip()
            total_price = re.sub(r"<[^>]+>", "", cells[6]).strip()
            by_part[part_name] = (qty, unit_price, total_price)

        assert by_part["ITest Keyboard"] == ("1", "&#8377;500.00", "&#8377;500.00")
        assert by_part["ITest RAM"] == ("2", "&#8377;1,000.00", "&#8377;2,000.00")
    finally:
        _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device
from models.spare_parts import SparePart
from models.part_request import PartRequest

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for pr in (await db.execute(select(PartRequest).where(
                    PartRequest.device_id == dev.id))).scalars().all():
                await db.delete(pr)
            await db.delete(dev)
        for code in ["{keyboard_code}", "{ram_code}"]:
            sp = (await db.execute(select(SparePart).where(SparePart.part_code == code))).scalar_one_or_none()
            if sp:
                await db.delete(sp)
        await db.commit()

asyncio.run(main())
""")


def test_download_sample_moved_into_upload_modals(app_client, make_user):  # noqa: F811
    html = _get_spare_parts(app_client, make_user)
    master_tab = html.split('id="masterTab"', 1)[1].split('<!-- ── TAB 3', 1)[0]
    assert "Download Sample" not in master_tab
    new_modal = html.split('id="uploadNewModal"', 1)[1].split("</form>", 1)[0]
    harvest_modal = html.split('id="uploadHarvestModal"', 1)[1].split("</form>", 1)[0]
    for modal in (new_modal, harvest_modal):
        assert "/spare-parts/bulk-template" in modal
        assert 'enctype="multipart/form-data"' in modal


def test_add_harvest_modal_trimmed_and_reordered(app_client, make_user):  # noqa: F811
    html = _get_spare_parts(app_client, make_user)
    modal = html.split('id="harvestModal"', 1)[1].split("</form>", 1)[0]
    assert 'name="main_category"' not in modal
    assert 'name="invoice_ref"' not in modal
    assert 'id="hv_inv_qty"' not in modal
    assert modal.index('name="category"') < modal.index('name="part_brand"')


def test_export_delete_selected_start_hidden(app_client, make_user):  # noqa: F811
    html = _get_spare_parts(app_client, make_user)
    assert 'id="expSel_partsTable" class="btn btn-outline-info btn-sm d-none"' in html
    assert 'id="delSel_partsTable" class="btn btn-outline-danger btn-sm d-none"' in html
