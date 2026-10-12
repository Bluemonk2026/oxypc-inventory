"""Sales Report + Exit Gate Pass: Invoice column / Invoice search (2026-10-12).

Both tables now lead with Sale ID, Date, Invoice, Tag Number (right after the
checkbox) and the DataTables search box also matches Sale.invoice_no.
"""
import pathlib
import re
import subprocess
import sys
import uuid

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=90)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def _headers(html, table_id):
    head = html.split(f'<table id="{table_id}"', 1)[1].split("</thead>", 1)[0]
    return [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r"<th[^>]*>.*?</th>", head, re.S)]


# ── templates: header order ──────────────────────────────────────────────────
def test_sales_list_header_order(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    h = _headers(app_client.get("/sales", follow_redirects=True).text, "salesTable")
    assert h[:5] == ["", "Sale#", "Date", "Invoice", "Tag Number"]
    assert h[5:8] == ["Brand/Model", "Lot", "Grade"]


def test_gate_pass_header_order(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/gate-pass", follow_redirects=True).text
    h = _headers(html, "gpTable")
    assert h[:5] == ["", "Sale No", "Sold At", "Invoice", "Tag Number"]
    assert h[5:] == ["Lot", "Device", "Customer", "Status", "Delivery Challan", "Action"]
    assert "order: [[2, 'desc']]" in html and "targets: [0, 4, 5, 6, 9, 10]" in html


# ── data feeds, on real rows ─────────────────────────────────────────────────
SEED = r'''
import asyncio, sys
from datetime import datetime
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.sales import Sale

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{tag}", lot_id=lot.id, brand="B", model="M",
                     current_stage=DeviceStage.sold)
        db.add(dev); await db.flush()
        db.add(Sale(sale_number="SALE-{tag}", device_id=dev.id, sale_price=1, sold_by="itest",
                    sold_at=datetime.now(), invoice_no="{inv}", customer_name="ITCust"))
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
        ids = "select id from devices where barcode = '{tag}'"
        await db.execute(text("delete from sales where device_id in (" + ids + ")"))
        await db.execute(text("delete from stage_movements where device_id in (" + ids + ")"))
        await db.execute(text("delete from devices where barcode = '{tag}'"))
        await db.commit()
asyncio.run(main())
'''


def test_data_feeds_invoice_cell_position_and_search(app_client, make_user):  # noqa: F811
    tag = "ITINV" + uuid.uuid4().hex[:6].upper()
    inv = "INV/" + uuid.uuid4().hex[:8].upper()
    _run(SEED.format(root=ROOT, tag=tag, inv=inv))
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)

        # Sales Report: 0 chk, 1 Sale#, 2 Date, 3 Invoice, 4 Tag
        s = app_client.get("/sales/data", params={"search[value]": inv, "length": 50}).json()
        assert s["recordsFiltered"] == 1
        c = s["data"][0]
        assert f"SALE-{tag}" in c[1] and c[3] == inv and f"<code>{tag}</code>" in c[4]
        # sorting by the Invoice column must not error
        r = app_client.get("/sales/data", params={"order[0][column]": 3, "order[0][dir]": "asc", "length": 5})
        assert r.status_code == 200
        # the "Sales ID" sale-number search still works
        s2 = app_client.get("/sales/data", params={"search[value]": f"SALE-{tag}", "length": 50}).json()
        assert s2["recordsFiltered"] == 1

        # Gate pass: 0 chk, 1 Sale No, 2 Sold At, 3 Invoice, 4 Tag
        g = app_client.get("/gate-pass/data", params={"search[value]": inv, "length": 50}).json()
        assert g["recordsFiltered"] == 1
        c = g["data"][0]
        assert f"SALE-{tag}" in c[1] and c[3] == inv and f"<code>{tag}</code>" in c[4]
        assert "ITCust" in c[7]
        r = app_client.get("/gate-pass/data", params={"order[0][column]": 3, "order[0][dir]": "desc", "length": 5})
        assert r.status_code == 200
    finally:
        _run(CLEAN.format(root=ROOT, tag=tag))
