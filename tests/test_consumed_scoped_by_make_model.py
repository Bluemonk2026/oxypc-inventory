"""Consumed pools by name+make+model (or, when a name is undifferentiated,
by that shared blank make/model) — never by part NAME alone across two
otherwise-unrelated Make/Model parts.

Repro of the bug this fixes: two Part Master rows both named "RAM", one for
Dell Latitude and one for HP EliteBook, each with its own handover history.
Before this fix, Part Master's Consumed column summed BOTH rows' handovers
into every "RAM" row regardless of laptop model — the Dell row's Consumed
count included the HP row's handovers and vice versa."""
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
from models.device import Device
from models.spare_parts import SparePart
from models.part_request import PartRequest

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).limit(1))).scalars().first()
        dell = SparePart(part_code="{code1}", name="{name}", category="RAM",
                         source="new", unit_price=100, qty_in_stock=10, min_stock_alert=1,
                         make="Dell", model="Latitude 5490")
        hp = SparePart(part_code="{code2}", name="{name}", category="RAM",
                       source="new", unit_price=100, qty_in_stock=10, min_stock_alert=1,
                       make="HP", model="EliteBook 840")
        db.add(dell)
        db.add(hp)
        await db.flush()
        # Dell row: 2 units handed over.
        db.add(PartRequest(part_id=dell.id, part_name="{name}", request_type="new",
                           status="received", qty_handed_over=2, device_id=dev.id))
        # HP row: 5 units handed over — must never bleed into Dell's count.
        db.add(PartRequest(part_id=hp.id, part_name="{name}", request_type="new",
                           status="handed_over", qty_handed_over=5, device_id=dev.id))
        await db.commit()

asyncio.run(main())
"""

_CLEANUP_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.spare_parts import SparePart
from models.part_request import PartRequest

async def main():
    async with AsyncSessionLocal() as db:
        for code in ["{code1}", "{code2}"]:
            p = (await db.execute(select(SparePart).where(SparePart.part_code == code))).scalar_one_or_none()
            if p:
                p.is_trashed = True
        reqs = (await db.execute(select(PartRequest).where(PartRequest.part_name == "{name}"))).scalars().all()
        for r in reqs:
            await db.delete(r)
        await db.commit()

asyncio.run(main())
"""


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def test_consumed_does_not_cross_make_model_boundary(app_client, make_user):  # noqa: F811
    name = f"ITESTMM{uuid.uuid4().hex[:6]}"
    code1 = f"ITMM1{uuid.uuid4().hex[:6]}"
    code2 = f"ITMM2{uuid.uuid4().hex[:6]}"

    _run(_SEED_SRC.format(root=ROOT, code1=code1, code2=code2, name=name))
    try:
        username, password = make_user("spare_parts_manager")
        _login(app_client, username, password)

        html = app_client.get("/spare-parts", follow_redirects=True).text
        dell_row = html.split(code1, 1)[1].split("</tr>", 1)[0]
        hp_row = html.split(code2, 1)[1].split("</tr>", 1)[0]
        assert ">2<" in dell_row, f"Dell row should show its own Consumed=2, not HP's: {dell_row[:400]}"
        assert ">5<" in hp_row, f"HP row should show its own Consumed=5, not Dell's: {hp_row[:400]}"

        # Ready to Sale Parts' Consumed pooling (routers/part_sales.py) must
        # agree — it mirrors Part Master's resolution for exactly this reason.
        # qty_in_stock=10 for both; Dell has 2 consumed (stock=8), HP has 5
        # consumed (stock=5) — before this fix both would've pooled to 7
        # consumed and shown stock=3 for both.
        dell_data = app_client.get("/ready-to-sale-parts/data", params={"code": code1}).json()
        hp_data = app_client.get("/ready-to-sale-parts/data", params={"code": code2}).json()
        assert 'data-stock="8"' in dell_data["data"][0][-1], dell_data
        assert 'data-stock="5"' in hp_data["data"][0][-1], hp_data
    finally:
        _run(_CLEANUP_SRC.format(root=ROOT, code1=code1, code2=code2, name=name))
