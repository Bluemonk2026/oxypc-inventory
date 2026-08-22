"""Ready to Sale Parts only lists parts whose real stock (In Stock − Sold −
Consumed) is greater than 0 — a part with nothing left to sell drops off the
table instead of sitting there disabled. Consumed here also had to catch up
to the same fix Part Master got: pooled by part NAME, every handover status
counted, not just "handed_over"."""
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
        # Fully consumed: 5 in stock, all 5 handed over (status already moved
        # on to "received") — must NOT appear on the page at all.
        depleted = SparePart(part_code="{code_depleted}", name="{name_depleted}",
                             category="RAM", source="new", unit_price=100,
                             qty_in_stock=5, min_stock_alert=1)
        # Still has stock left after the same handover accounting.
        available = SparePart(part_code="{code_available}", name="{name_available}",
                              category="RAM", source="new", unit_price=100,
                              qty_in_stock=5, min_stock_alert=1)
        db.add(depleted)
        db.add(available)
        await db.flush()
        db.add(PartRequest(part_id=depleted.id, part_name="{name_depleted}",
                           request_type="new", status="received", qty_handed_over=5,
                           device_id=dev.id))
        db.add(PartRequest(part_id=available.id, part_name="{name_available}",
                           request_type="new", status="received", qty_handed_over=2,
                           device_id=dev.id))
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
        for code in ["{code_depleted}", "{code_available}"]:
            p = (await db.execute(select(SparePart).where(SparePart.part_code == code))).scalar_one_or_none()
            if p:
                p.is_trashed = True
        for name in ["{name_depleted}", "{name_available}"]:
            reqs = (await db.execute(select(PartRequest).where(PartRequest.part_name == name))).scalars().all()
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


def test_depleted_part_disappears_available_part_stays(app_client, make_user):  # noqa: F811
    code_depleted = f"ITCD{uuid.uuid4().hex[:6]}"
    code_available = f"ITCA{uuid.uuid4().hex[:6]}"
    name_depleted = f"ITESTDEPL{uuid.uuid4().hex[:6]}"
    name_available = f"ITESTAVAIL{uuid.uuid4().hex[:6]}"

    _run(_SEED_SRC.format(root=ROOT, code_depleted=code_depleted, code_available=code_available,
                          name_depleted=name_depleted, name_available=name_available))
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get("/ready-to-sale-parts", follow_redirects=True).text
        assert name_depleted not in html
        assert name_available not in html  # server-side DataTables feed, not inline

        r = app_client.get("/ready-to-sale-parts/data", params={"draw": 1, "start": 0, "length": 100})
        assert r.status_code == 200
        body = r.text
        assert code_depleted not in body, "fully-consumed part must not appear at all"
        assert code_available in body, "part with real stock left must still appear"
    finally:
        _run(_CLEANUP_SRC.format(root=ROOT, code_depleted=code_depleted, code_available=code_available,
                                 name_depleted=name_depleted, name_available=name_available))
