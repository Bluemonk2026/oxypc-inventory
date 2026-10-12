"""Inventory Manager (/stock), 2026-10-12:

 A. "Flag Items" bulk action: modal data + Add/Edit (POST /stock/flag) and Delete
    (POST /stock/flag/delete) on the selected tags; flagged tags show a flag icon
    with a tooltip; the flag is removed every time a tag moves into Stock In.
 B. "Returned" column (replaced Assigned User): Yes/No, with an info icon whose
    tooltip shows the latest return's Reason / Condition / Complaint.
"""
import json
import pathlib
import subprocess
import sys
import uuid
from datetime import date

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=90)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    lines = r.stdout.strip().splitlines()
    return lines[-1] if lines else ""


def _seed(barcode, stage="stock_in", flag=False, with_return=False):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from datetime import date
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage
from models.sales import Sale, Return

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.{stage})
        if {flag!r}:
            dev.flag_active = True
            dev.flag_authorized_by = "Seed Authorizer"
            dev.flag_request_date = date(2026, 10, 1)
            dev.flag_target_date = date(2026, 10, 5)
            dev.flag_reason = "Seeded flag reason"
        db.add(dev)
        await db.flush()
        if {with_return!r}:
            sale = Sale(sale_number="SALEIT{barcode[-6:]}", device_id=dev.id, sale_price=20000,
                        customer_name="Original Customer", customer_state="Delhi", payment_mode="Cash")
            db.add(sale)
            await db.flush()
            db.add(Return(sale_id=sale.id, device_id=dev.id, reason="Not working <b>x</b>",
                          condition_on_return="Minor Damage", complaint_text="Screen flicker",
                          approval_status="pending"))
        await db.commit()

asyncio.run(main())
""")


def _read_flag(barcode):
    out = _run(f"""
import asyncio, sys, json
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        d = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        print(json.dumps({{
            "active": bool(d.flag_active), "by": d.flag_authorized_by,
            "req": d.flag_request_date.isoformat() if d.flag_request_date else None,
            "tgt": d.flag_target_date.isoformat() if d.flag_target_date else None,
            "reason": d.flag_reason, "stage": d.current_stage.value}}))

asyncio.run(main())
""")
    return json.loads(out)


def _cleanup(*barcodes):
    bc = ", ".join(f'"{b}"' for b in barcodes)
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device, StageMovement
from models.location import DeviceLocationLog
from models.sales import Sale, Return

async def main():
    async with AsyncSessionLocal() as db:
        for b in [{bc}]:
            dev = (await db.execute(select(Device).where(Device.barcode == b))).scalar_one_or_none()
            if not dev:
                continue
            for model, col in ((Return, Return.device_id), (Sale, Sale.device_id),
                               (StageMovement, StageMovement.device_id),
                               (DeviceLocationLog, DeviceLocationLog.device_id)):
                for row in (await db.execute(select(model).where(col == dev.id))).scalars().all():
                    await db.delete(row)
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
""")


def _post(client, url, **data):
    return client.post(url, data={"csrf_token": client.cookies.get("csrf_token", ""), **data})


def _login_admin(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)


# ── A. Flag Items ────────────────────────────────────────────────────────────
def test_flag_button_and_modal_are_on_the_page(app_client, make_user):  # noqa: F811
    _login_admin(app_client, make_user)
    html = app_client.get("/stock", follow_redirects=True).text
    assert 'id="flagItemsBtn"' in html and "Flag Items (" in html
    for needle in ("Flag Authorized By", "Flag Request Date", "Flag Target Date", "Flag Reason",
                   'id="flagDeleteBtn"', "/stock/flag/delete", "/stock/flag-details"):
        assert needle in html, needle


def test_flag_add_edit_delete_roundtrip(app_client, make_user):  # noqa: F811
    s = uuid.uuid4().hex[:6]
    a, b = f"ITFLAGA{s}", f"ITFLAGB{s}"
    _seed(a)
    _seed(b)
    try:
        _login_admin(app_client, make_user)
        bcs = f"{a},{b}"

        # nothing flagged yet -> modal opens blank (Add), user list present
        d = app_client.get("/stock/flag-details", params={"barcodes": bcs}).json()
        assert d["ok"] and d["flag"] is None and d["flagged"] == 0 and d["total"] == 2
        assert "IQC Test User" in d["users"]

        # Add (applies to both selected tags)
        r = _post(app_client, "/stock/flag", barcodes=bcs, authorized_by="IQC Test User",
                  request_date="2026-10-12", target_date="2026-10-15", reason="Customer escalation")
        assert r.status_code == 200 and r.json() == {"ok": True, "flagged": 2}
        for bc in (a, b):
            f = _read_flag(bc)
            assert f["active"] and f["by"] == "IQC Test User" and f["req"] == "2026-10-12"
            assert f["tgt"] == "2026-10-15" and f["reason"] == "Customer escalation"

        # modal now pre-fills the existing flag (Edit / Delete)
        d = app_client.get("/stock/flag-details", params={"barcodes": bcs}).json()
        assert d["flagged"] == 2 and not d["mixed"]
        assert d["flag"] == {"authorized_by": "IQC Test User", "request_date": "2026-10-12",
                             "target_date": "2026-10-15", "reason": "Customer escalation"}

        # Edit (update one tag only)
        r = _post(app_client, "/stock/flag", barcodes=a, authorized_by="IQC Test User",
                  request_date="2026-10-12", target_date="2026-10-20", reason="Extended")
        assert r.status_code == 200
        assert _read_flag(a)["tgt"] == "2026-10-20" and _read_flag(a)["reason"] == "Extended"
        assert _read_flag(b)["tgt"] == "2026-10-15"
        # selected tags now differ -> flagged as mixed
        assert app_client.get("/stock/flag-details", params={"barcodes": bcs}).json()["mixed"] is True

        # flagged tag shows the flag icon + tooltip details in the table feed
        feed = app_client.get("/stock/data", params={"draw": 1, "start": 0, "length": 5000}).json()["data"]
        row = next(r_ for r_ in feed if f'value="{a}"' in r_[0])
        assert "stock-flag-icon" in row[1] and "Extended" in row[1] and "IQC Test User" in row[1]

        # Delete (both)
        r = _post(app_client, "/stock/flag/delete", barcodes=bcs)
        assert r.status_code == 200 and r.json() == {"ok": True, "cleared": 2}
        for bc in (a, b):
            f = _read_flag(bc)
            assert not f["active"] and f["by"] is None and f["req"] is None
            assert f["tgt"] is None and f["reason"] is None
    finally:
        _cleanup(a, b)


def test_flag_validation(app_client, make_user):  # noqa: F811
    s = uuid.uuid4().hex[:6]
    a = f"ITFLAGV{s}"
    _seed(a)
    try:
        _login_admin(app_client, make_user)
        ok = dict(barcodes=a, authorized_by="IQC Test User", request_date="2026-10-12",
                  target_date="2026-10-15", reason="x")
        assert _post(app_client, "/stock/flag", **{**ok, "target_date": "2026-10-11"}).status_code == 400
        assert _post(app_client, "/stock/flag", **{**ok, "reason": "   "}).status_code == 400
        assert _post(app_client, "/stock/flag", **{**ok, "authorized_by": "Nobody At All"}).status_code == 400
        assert _post(app_client, "/stock/flag", **{**ok, "request_date": "not-a-date"}).status_code == 400
        assert _post(app_client, "/stock/flag", **{**ok, "barcodes": ""}).status_code in (400, 422)
        assert not _read_flag(a)["active"]
        # same-day target is allowed
        assert _post(app_client, "/stock/flag", **{**ok, "target_date": "2026-10-12"}).status_code == 200
    finally:
        _cleanup(a)


def test_flag_requires_csrf(app_client, make_user):  # noqa: F811
    s = uuid.uuid4().hex[:6]
    a = f"ITFLAGC{s}"
    _seed(a)
    try:
        _login_admin(app_client, make_user)
        r = app_client.post("/stock/flag", data={
            "csrf_token": "wrong", "barcodes": a, "authorized_by": "IQC Test User",
            "request_date": "2026-10-12", "target_date": "2026-10-15", "reason": "x"},
            follow_redirects=False)
        assert r.status_code in (302, 303) and "/auth/login" in r.headers["location"]
        assert not _read_flag(a)["active"]
    finally:
        _cleanup(a)


def test_flag_cleared_when_tag_moves_into_stock_in_via_route(app_client, make_user):  # noqa: F811
    s = uuid.uuid4().hex[:6]
    a = f"ITFLAGM{s}"
    _seed(a, stage="l1", flag=True)
    try:
        _login_admin(app_client, make_user)
        assert _read_flag(a)["active"]
        r = _post(app_client, "/stock/move-to-stock", barcode=a)
        assert r.status_code in (200, 302, 303)
        f = _read_flag(a)
        assert f["stage"] == "stock_in"
        assert not f["active"] and f["by"] is None and f["reason"] is None
    finally:
        _cleanup(a)


def test_flag_survives_while_staying_in_stock_in_but_not_other_stage_moves(app_client, make_user):  # noqa: F811
    s = uuid.uuid4().hex[:6]
    a = f"ITFLAGS{s}"
    _seed(a, stage="stock_in", flag=True)
    try:
        # re-assigning the same stage is not a move into Stock In
        out = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device, DeviceStage

async def main():
    async with AsyncSessionLocal() as db:
        d = (await db.execute(select(Device).where(Device.barcode == "{a}"))).scalar_one()
        d.current_stage = DeviceStage.stock_in
        await db.commit()
        d.current_stage = DeviceStage.l1          # leaving Stock In keeps the flag
        await db.commit()
        print(d.flag_active)
        d.current_stage = DeviceStage.stock_in    # coming back clears it
        await db.commit()
        print(d.flag_active)

asyncio.run(main())
""")
        assert out == "False"
        assert not _read_flag(a)["active"]
    finally:
        _cleanup(a)


def test_flag_helper_unit():
    from types import SimpleNamespace
    from models.device import Device, DeviceStage
    from services.device_flag import set_flag, clear_flag, flag_dict
    d = SimpleNamespace(flag_active=False, flag_authorized_by=None, flag_request_date=None,
                        flag_target_date=None, flag_reason=None)
    assert flag_dict(d) is None
    set_flag(d, "Boss", date(2026, 10, 1), date(2026, 10, 3), "urgent")
    assert flag_dict(d) == {"authorized_by": "Boss", "request_date": "2026-10-01",
                            "target_date": "2026-10-03", "reason": "urgent"}
    clear_flag(d)
    assert flag_dict(d) is None and d.flag_reason is None
    # the ORM hook: any stage -> stock_in clears; constructor-time stock_in does not
    dev = Device(barcode="x", current_stage=DeviceStage.stock_in, flag_active=True, flag_reason="r")
    assert dev.flag_active is True
    dev.current_stage = DeviceStage.iqc
    dev.current_stage = DeviceStage.stock_in
    assert dev.flag_active is False and dev.flag_reason is None


# ── B. Returned column ───────────────────────────────────────────────────────
def test_returned_column_header_replaces_assigned_user(app_client, make_user):  # noqa: F811
    _login_admin(app_client, make_user)
    html = app_client.get("/stock", follow_redirects=True).text
    table = html.split('id="stockTable"', 1)[1].split("</thead>", 1)[0]
    assert "<th>Returned</th>" in table
    assert "Assigned User" not in table


def test_returned_cell_yes_with_tooltip_and_no(app_client, make_user):  # noqa: F811
    s = uuid.uuid4().hex[:6]
    yes_bc, no_bc = f"ITRETY{s}", f"ITRETN{s}"
    _seed(yes_bc, with_return=True)
    _seed(no_bc)
    try:
        _login_admin(app_client, make_user)
        feed = app_client.get("/stock/data", params={"draw": 1, "start": 0, "length": 5000}).json()["data"]
        yes_row = next(r for r in feed if f'value="{yes_bc}"' in r[0])
        no_row = next(r for r in feed if f'value="{no_bc}"' in r[0])
        cell = yes_row[9]
        assert ">Yes<" in cell and "returned-info" in cell and "bi-info-circle" in cell
        # tooltip text (HTML-escaped inside title=""): Reason / Condition / Complaint, user text escaped
        assert "Reason:" in cell and "Condition:" in cell and "Complaint:" in cell
        assert "Minor Damage" in cell and "Screen flicker" in cell
        assert "Not working &amp;lt;b&amp;gt;x&amp;lt;/b&amp;gt;" in cell
        assert "<b>x</b>" not in cell
        assert "No" in no_row[9] and "Yes" not in no_row[9] and "returned-info" not in no_row[9]
    finally:
        _cleanup(yes_bc, no_bc)


def test_returned_cell_helper_unit():
    from types import SimpleNamespace
    from routers.stock import _returned_cell_html
    assert "No" in _returned_cell_html(None) and "info" not in _returned_cell_html(None)
    ret = SimpleNamespace(reason="Dead", condition_on_return=None, complaint_text="No boot")
    html = _returned_cell_html(ret)
    assert ">Yes<" in html and "Reason:" in html and "Dead" in html and "No boot" in html
    assert "Condition:" in html and "—" in html  # missing value shows an em-dash
