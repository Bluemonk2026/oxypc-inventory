"""Parts Manager "Part Requests" tab Engineer filter (2026-09-14):

Investigated from a reported discrepancy — an L1/L2 engineer's Bulk Part
Request table showed counts scoped to his current 33-tag queue, but Parts
Manager's Part Requests tab showed 45 records for him: every non-faulty
PartRequest row ever created, any engineer, any status, any device,
forever, with no way to actually scope the tab to one engineer server-side
(the only way to "filter by name" was DataTables' own client-side global
search box matching whatever text happened to render).

This adds a real server-side Engineer filter (GET ?engineer=<name>),
applied only to Part Requests / Faulty Request (Part Master and the tiles
have no engineer to match against).
"""
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
from models.part_request import PartRequest

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).limit(1))).scalars().first()
        db.add(PartRequest(part_name="{part_a}", request_type="new", status="requested",
                           device_id=dev.id, engineer_name="{eng_a}", requested_by="{eng_a}"))
        db.add(PartRequest(part_name="{part_b}", request_type="new", status="requested",
                           device_id=dev.id, engineer_name="{eng_b}", requested_by="{eng_b}"))
        # Faulty-type row for eng_a too, to confirm the filter scopes both tabs.
        db.add(PartRequest(part_name="{part_a}", request_type="faulty", status="requested",
                           device_id=dev.id, engineer_name="{eng_a}", requested_by="{eng_a}"))
        await db.commit()

asyncio.run(main())
"""

_CLEANUP_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.part_request import PartRequest

async def main():
    async with AsyncSessionLocal() as db:
        for name in ("{part_a}", "{part_b}"):
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


def test_engineer_filter_scopes_part_requests_and_faulty_tabs(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    part_a = f"ITENGA{suffix}"
    part_b = f"ITENGB{suffix}"
    eng_a = f"ITEngA{suffix}"
    eng_b = f"ITEngB{suffix}"
    _run(_SEED_SRC.format(root=ROOT, part_a=part_a, part_b=part_b, eng_a=eng_a, eng_b=eng_b))
    try:
        username, password = make_user("spare_parts_manager")
        _login(app_client, username, password)

        # Unfiltered: both engineers' requests are visible, and the Engineer
        # dropdown offers both as options.
        html = app_client.get("/spare-parts", follow_redirects=True).text
        assert part_a in html and part_b in html
        assert f'value="{eng_a}"' in html
        assert f'value="{eng_b}"' in html

        # Filtered to eng_a: eng_b's request disappears from both the Part
        # Requests and the Faulty Request tables; eng_a's own rows (one of
        # each request_type) remain.
        html = app_client.get(f"/spare-parts?engineer={eng_a}", follow_redirects=True).text
        assert part_a in html
        assert part_b not in html
    finally:
        _run(_CLEANUP_SRC.format(root=ROOT, part_a=part_a, part_b=part_b))
