"""Stock Type columns (Sales, All Inventory), Entity filter on Ready to Sale, and the
"Ready for Sale" -> "Finish Good" rename in New Transfer / Change Floor (2026-10-07)."""
import json
import pathlib
import subprocess
import sys
import types
import uuid

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=90)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    lines = r.stdout.strip().splitlines()
    return lines[-1] if lines else ""


# ── Transfers: Finish Good == Ready for Sale ─────────────────────────────────
def test_every_ready_for_sale_spelling_is_one_canonical_type_with_one_label():
    from routers.transfers import canonical_transfer_type, transfer_type_label
    for v in ("ready_for_sale", "Ready for Sale", "Ready to Sale", "Finish Good", "finish_good", " FINISH GOOD "):
        assert canonical_transfer_type(v) == "ready_for_sale", v
        assert transfer_type_label(v) == "Finish Good", v
    # nothing else is touched
    assert canonical_transfer_type("as_is_lot") == "as_is_lot"
    assert canonical_transfer_type("scrap_for_sale") == "scrap_for_sale"
    assert transfer_type_label("as_is_lot") == "As Is Lot"
    assert transfer_type_label("For Repairing") == "For Repairing"
    assert transfer_type_label("transfer_to_trc") == "Transfer To Trc"


def test_every_transfer_entry_point_normalises_the_type_before_using_it():
    import inspect
    from routers import transfers
    for fn in (transfers.create_transfer, transfers.create_parts_transfer, transfers._bulk_assign_devices
               if hasattr(transfers, "_bulk_assign_devices") else None):
        if fn is None:
            continue
        assert "canonical_transfer_type(transfer_type)" in inspect.getsource(fn), fn.__name__
    src = inspect.getsource(transfers)
    assert src.count("canonical_transfer_type(transfer_type)") >= 3
    assert src.count("if transfer_type in (\"ready_for_sale\", \"as_is_lot\")") == 2   # action unchanged


def _render(template, ctx, monkeypatch):
    from templates_config import templates
    from models.user import UserRole
    monkeypatch.setitem(templates.env.globals, "master_options",
                        lambda cat: ["as_is_lot", "ready_for_sale", "scrap_for_sale", "For Repairing"]
                        if cat == "transfer_type" else [])
    user = types.SimpleNamespace(username="admin", role=UserRole.admin, full_name="Admin", is_active=True, id=1)
    base = {"request": types.SimpleNamespace(url=types.SimpleNamespace(path="/x"), query_params={},
                                             session={}, cookies={}),
            "current_user": user}
    return templates.env.get_template(template).render({**base, **ctx})


def test_new_transfer_and_change_floor_show_finish_good_not_ready_for_sale(monkeypatch):
    form = _render("transfers/form.html", {"prefix": "device", "storage_locations": [], "users": [],
                                           "error": None, "success": None}, monkeypatch)
    assert ">Finish Good</option>" in form and ">Ready for Sale</option>" not in form
    assert '<option value="ready_for_sale">Finish Good</option>' in form          # value unchanged

    row = types.SimpleNamespace(transfer_type="ready_for_sale", _display_type="Finish Good",
                                _display_stage="Ready to Sale", _display_lot_number="L1", id=uuid.uuid4(),
                                barcode="T1", make="HP", model="840", quantity=1, from_warehouse="", to_warehouse="",
                                department="", _display_transferred_by="x", _display_received_by="y",
                                transfer_date=__import__('datetime').datetime(2026, 10, 7, 10, 0), to_location_id=None, notes="", move_kind="device",
                                serial_no="", cpu="", generation="", ram="", hdd="")
    lst = _render("transfers/list.html", {
        "transfers": [row], "q": "", "transfer_type": "", "transferred_by": "", "transferred_by_options": [],
        "location_id": "", "storage_locations": [], "location_by_id": {}, "zone_labels": {},
        "date_from": "", "date_to": ""}, monkeypatch)
    assert ">Finish Good</option>" in lst and ">Ready for Sale</option>" not in lst   # filter dropdown
    assert '<span class="badge bg-secondary">Finish Good</span>' in lst               # the Type column


# ── templates: columns ───────────────────────────────────────────────────────
def test_all_inventory_has_stock_type_and_no_price_columns(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/devices", follow_redirects=True).text
    head = html.split('<table id="devicesTable"', 1)[1].split("</thead>", 1)[0]
    assert "<th>Stock Type</th>" in head
    assert "Stock Price" not in head and "Sale Price" not in head
    assert head.index("<th>Grade</th>") < head.index("<th>Stock Type</th>") < head.index("<th>Stage</th>")


def test_sales_list_has_stock_type_after_grade(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/sales", follow_redirects=True).text
    assert "<th>Grade</th><th>Stock Type</th>" in html


def test_ready_to_sale_has_entity_filter(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/sales/ready", follow_redirects=True).text
    assert 'id="ms_val_entity"' in html and 'data-ms="entity"' in html
    assert "d.entity = " in html and "/sales/ready/barcodes?entity=" in html          # table + Select All follow it


# ── data endpoints, on real rows ─────────────────────────────────────────────
SEED = r'''
import asyncio, sys, uuid
from datetime import datetime
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.sales import Sale

TAG = "{tag}"
async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        plain = Device(barcode=TAG + "P", lot_id=lot.id, brand="B", model="M", entity="{ent}",
                       current_stage=DeviceStage.ready_to_sale)
        sub = Device(barcode=TAG + "S", lot_id=lot.id, brand="B", model="M", entity="{ent}",
                     current_stage=DeviceStage.ready_to_sale, sub_lot_number="SL-1")
        other = Device(barcode=TAG + "O", lot_id=lot.id, brand="B", model="M", entity="{other_ent}",
                       current_stage=DeviceStage.ready_to_sale)
        sold_sub = Device(barcode=TAG + "X", lot_id=lot.id, brand="B", model="M", entity="{ent}",
                          current_stage=DeviceStage.sold, sub_lot_number="SL-2")
        sold_plain = Device(barcode=TAG + "Y", lot_id=lot.id, brand="B", model="M", entity="{ent}",
                            current_stage=DeviceStage.sold)
        db.add_all([plain, sub, other, sold_sub, sold_plain]); await db.flush()
        db.add(Sale(sale_number="SALE-{n}1", device_id=sold_sub.id, sale_price=1, sold_by="itest", sold_at=datetime.now()))
        db.add(Sale(sale_number="SALE-{n}2", device_id=sold_plain.id, sale_price=1, sold_by="itest", sold_at=datetime.now()))
        await db.commit()
asyncio.run(main())
'''

CLEAN = r'''
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import text
from database import AsyncSessionLocal
async def main():
    async with AsyncSessionLocal() as db:
        ids = "select id from devices where barcode like '{tag}%'"
        await db.execute(text("delete from sales where device_id in (" + ids + ")"))
        await db.execute(text("delete from stage_movements where device_id in (" + ids + ")"))
        await db.execute(text("delete from devices where barcode like '{tag}%'"))
        await db.commit()
asyncio.run(main())
'''


def test_data_feeds_show_stock_type_and_entity_filter(app_client, make_user):  # noqa: F811
    tag = "ITST" + uuid.uuid4().hex[:6].upper()
    ent, other_ent = "ITENT-" + tag, "ITOTH-" + tag
    n = str(uuid.uuid4().int)[:8]
    _run(SEED.format(root=ROOT, tag=tag, ent=ent, other_ent=other_ent, n=n))
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)

        # All Inventory: 15 columns, Stock Type at index 11, no price columns
        d = app_client.get("/devices/data", params={"q": tag, "length": 50, "exclude_sold": "", "fs": "1"}).json()
        by_code = {}
        for cells in d["data"]:
            assert len(cells) == 15
            by_code[cells[1].split(">")[1].split("<")[0]] = cells
        assert "As-Is" in by_code[tag + "S"][11] and "Finish Good" in by_code[tag + "P"][11]
        assert all("₹" not in c for cells in by_code.values() for c in cells)

        # Sales: Stock Type at index 7
        s = app_client.get("/sales/data", params={"q": tag, "length": 50}).json()
        sales = {c[3].split("<code>")[1].split("</code>")[0]: c for c in s["data"]}
        assert "As-Is Lot" in sales[tag + "X"][7] and "Finish Good" in sales[tag + "Y"][7]

        # Ready to Sale tags table: Entity filter narrows rows, totals and Select All
        allr = app_client.get("/sales/ready/data", params={"search[value]": tag, "length": 50}).json()
        one = app_client.get("/sales/ready/data", params={"search[value]": tag, "length": 50, "entity": ent}).json()
        assert allr["recordsFiltered"] == 2 and one["recordsFiltered"] == 1         # plain (ent) + other (other_ent); sub-lot is As-Is
        codes_all = app_client.get("/sales/ready/barcodes").json()["barcodes"]
        codes_ent = app_client.get("/sales/ready/barcodes", params={"entity": ent}).json()["barcodes"]
        assert tag + "O" in codes_all and tag + "O" not in codes_ent and tag + "P" in codes_ent
    finally:
        _run(CLEAN.format(root=ROOT, tag=tag))
