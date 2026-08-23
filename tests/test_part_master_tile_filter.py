"""Part Master's global filter bar is now a real server-side filter (Filter
button, page reload) so the tiles actually recompute from the filtered
scope, instead of staying fixed global totals while only the table rows
narrowed client-side."""
import pathlib
import subprocess
import sys
import uuid

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)

_SEED_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from database import AsyncSessionLocal
from models.spare_parts import SparePart

async def main():
    async with AsyncSessionLocal() as db:
        p = SparePart(part_code="{code}", name="{name}", category="{category}",
                      source="new", unit_price=500, qty_in_stock=7, min_stock_alert=1)
        db.add(p)
        await db.commit()

asyncio.run(main())
"""

_CLEANUP_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.spare_parts import SparePart

async def main():
    async with AsyncSessionLocal() as db:
        p = (await db.execute(select(SparePart).where(SparePart.part_code == "{code}"))).scalar_one_or_none()
        if p:
            p.is_trashed = True
        await db.commit()

asyncio.run(main())
"""


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def test_filtering_by_part_name_narrows_the_tiles(app_client, make_user):  # noqa: F811
    name = f"ITESTTILE{uuid.uuid4().hex[:6]}"
    code = f"ITTILE{uuid.uuid4().hex[:6]}"
    category = "RAM"

    _run(_SEED_SRC.format(root=ROOT, code=code, name=name, category=category))
    try:
        username, password = make_user("spare_parts_manager")
        _login(app_client, username, password)

        html = app_client.get("/spare-parts", params={"part_name": name}, follow_redirects=True).text
        # 1 part type, 7 in stock (Consumed/Sold both 0 for this fresh part),
        # ₹3,500 stock value (500 unit price * 7 qty) — none of that is true
        # of the whole shop, only of this one filtered-in part.
        assert ">1<" in html.split("Part Types", 1)[0][-200:]
        assert "3,500" in html
    finally:
        _run(_CLEANUP_SRC.format(root=ROOT, code=code))


def test_qty_available_unaffected_by_the_filter(app_client, make_user):  # noqa: F811
    """A Part Request's Qty Available must still resolve correctly even when
    the global filter bar's Category/Part Name would otherwise exclude that
    part's own Part Master row from view."""
    import inspect
    from routers import spare_parts as sp

    src = inspect.getsource(sp.parts_list)
    # group_stock / part_stock / stock_by_name / part_meta must be built from
    # all_parts (the unfiltered universe), not the filtered `parts`.
    block = src.split("Qty Available on the Part Requests", 1)[1].split("# ── Pending part-sourcing", 1)[0]
    assert "for p in all_parts" in block
    assert "for p in parts]" not in block and "for p in parts}" not in block
