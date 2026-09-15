"""GRN post IQC — Add/Edit Lot modal now maps several Lots to one GRN
(2026-09-15): "allow to add multiple Lots within modal and on submitting
modal will create all listed lot and map the GRN details with all lots just
like currently creation/Mapping Detail doing for one lot at a time."

POST /grn/{grn_id}/add-lot now takes repeated lot_number / confirm_merge
form fields (one pair per row in the modal) instead of a single pair, and
runs the same per-lot create-or-merge logic in a loop — exactly as it always
did for one lot, just once per row. Every mapped Lot still gets tied back to
the GRN via Lot.grn_system_number (unchanged mechanism), which is how
routers/grn.py's GET /post-iqc now groups multiple Lots under one GRN row
for the "N Lots" popup, and how the Edit GRN modal's mirror-to-lot logic
(grn_edit) now updates every mapped Lot instead of only the first.
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


def _seed_grn(grn_number, sender_name="ITestVendor"):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from database import AsyncSessionLocal
from models.grn_import import GRNImport

async def main():
    async with AsyncSessionLocal() as db:
        db.add(GRNImport(grn_number="{grn_number}", source="post_iqc", created_by="itest",
                          sender_name="{sender_name}"))
        await db.commit()

asyncio.run(main())
""")


def _seed_existing_lot(lot_number, vendor_name="ExistingVendor"):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from datetime import datetime
from database import AsyncSessionLocal
from models.lot import Lot

async def main():
    async with AsyncSessionLocal() as db:
        db.add(Lot(lot_number="{lot_number}", supplier_name="{vendor_name}", vendor_name="{vendor_name}",
                    buying_price=0, qty=1, purchase_date=datetime.utcnow()))
        await db.commit()

asyncio.run(main())
""")


def _get_grn_id(grn_number):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.grn_import import GRNImport

async def main():
    async with AsyncSessionLocal() as db:
        g = (await db.execute(select(GRNImport).where(GRNImport.grn_number == "{grn_number}"))).scalar_one()
        print(g.id)

asyncio.run(main())
""")


def _lots_for_grn(grn_number):
    """Newline-separated 'lot_number' rows for every Lot whose
    grn_system_number points at this GRN, ordered for stable assertions."""
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot

async def main():
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Lot).where(
            Lot.grn_system_number == "{grn_number}").order_by(Lot.lot_number))).scalars().all()
        for l in rows:
            print(l.lot_number)

asyncio.run(main())
""")


def _cleanup(grn_number, lot_numbers):
    numbers_repr = repr(list(lot_numbers))
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.grn_import import GRNImport
from models.lot import Lot

async def main():
    async with AsyncSessionLocal() as db:
        for ln in {numbers_repr}:
            lot = (await db.execute(select(Lot).where(Lot.lot_number == ln))).scalar_one_or_none()
            if lot:
                await db.delete(lot)
        g = (await db.execute(select(GRNImport).where(GRNImport.grn_number == "{grn_number}"))).scalar_one_or_none()
        if g:
            await db.delete(g)
        await db.commit()

asyncio.run(main())
""")


def test_add_lot_creates_several_new_lots_from_one_submit(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    grn_number = str(uuid.uuid4().int)[:12]
    lot_a, lot_b = f"ITMULTIA{suffix}", f"ITMULTIB{suffix}"
    _seed_grn(grn_number)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"
        grn_id = _get_grn_id(grn_number)

        r = app_client.post(f"/grn/{grn_id}/add-lot", data={
            "csrf_token": csrf,
            "lot_number": [lot_a, lot_b],
            "confirm_merge": ["", ""],
        })
        assert r.status_code == 200, r.text[:300]
        assert r.json()["ok"] is True

        mapped = _lots_for_grn(grn_number).splitlines()
        assert mapped == sorted([lot_a, lot_b])
    finally:
        _cleanup(grn_number, [lot_a, lot_b])


def test_add_lot_blocks_on_unconfirmed_existing_lot_without_writing_anything(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    grn_number = str(uuid.uuid4().int)[:12]
    new_lot = f"ITMULTINEW{suffix}"
    existing_lot = f"ITMULTIEXIST{suffix}"
    _seed_grn(grn_number)
    _seed_existing_lot(existing_lot)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"
        grn_id = _get_grn_id(grn_number)

        r = app_client.post(f"/grn/{grn_id}/add-lot", data={
            "csrf_token": csrf,
            "lot_number": [new_lot, existing_lot],
            "confirm_merge": ["", ""],  # neither row confirmed
        })
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["ok"] is False
        assert body["conflicts"] == [existing_lot]

        # Nothing written — not even the unrelated new-lot row in the same batch.
        assert _lots_for_grn(grn_number).splitlines() == []
    finally:
        _cleanup(grn_number, [new_lot, existing_lot])


def test_add_lot_merges_existing_lot_when_confirmed_alongside_a_new_one(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    grn_number = str(uuid.uuid4().int)[:12]
    new_lot = f"ITMULTINEW2{suffix}"
    existing_lot = f"ITMULTIEXIST2{suffix}"
    _seed_grn(grn_number)
    _seed_existing_lot(existing_lot, vendor_name="LegacyVendor")
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"
        grn_id = _get_grn_id(grn_number)

        r = app_client.post(f"/grn/{grn_id}/add-lot", data={
            "csrf_token": csrf,
            "lot_number": [new_lot, existing_lot],
            "confirm_merge": ["", "1"],
        })
        assert r.status_code == 200, r.text[:300]
        assert r.json()["ok"] is True

        mapped = _lots_for_grn(grn_number).splitlines()
        assert mapped == sorted([new_lot, existing_lot])
    finally:
        _cleanup(grn_number, [new_lot, existing_lot])


def test_post_iqc_page_shows_lot_count_and_addedit_lot_modal(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    grn_number = str(uuid.uuid4().int)[:12]
    lot_a, lot_b = f"ITMULTIVIEW1{suffix}", f"ITMULTIVIEW2{suffix}"
    _seed_grn(grn_number)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"
        grn_id = _get_grn_id(grn_number)
        app_client.post(f"/grn/{grn_id}/add-lot", data={
            "csrf_token": csrf, "lot_number": [lot_a, lot_b], "confirm_merge": ["", ""],
        })

        html = app_client.get("/grn/post-iqc", follow_redirects=True).text
        # Modal renamed from "Add Lot" to "Add/Edit Lot".
        assert "Add/Edit Lot" in html
        assert 'id="addLotModal"' in html
        # Multi-row support in the modal.
        assert 'id="al_rows"' in html
        assert 'id="al_add_row"' in html
        # LOT column now shows a clickable count instead of listing names inline.
        assert "2 Lots" in html
        assert 'id="lotListModal"' in html
        assert 'class="btn btn-sm btn-link p-0 fw-semibold text-decoration-none lot-count-btn"' in html
        # A GRN with mapped Lots now shows "Edit Lot" (same modal, prefilled),
        # not a plain link to /lots/{id}/edit.
        assert "Edit Lot" in html
        assert f'data-grn-id="{grn_id}"' in html
        assert f"data-lot-numbers=\"{lot_a},{lot_b}\"" in html
    finally:
        _cleanup(grn_number, [lot_a, lot_b])
