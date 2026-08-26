"""All Tags tab (templates/cosmetic/all_tags.html): a "Cosmetic Stages"
filter dropdown, injected ahead of DataTables' own search box, filters the
table by each row's data-stage attribute — same custom-search-hook pattern
as the L1/L2 filter bar (templates/repair/l1.html).
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


def _seed_device(stage, barcode):
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
        db.add(Device(barcode="{barcode}", lot_id=lot.id, brand="X", model="Y",
                     current_stage=DeviceStage.{stage}))
        await db.commit()

asyncio.run(main())
""")


def _cleanup(barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
""")


def test_all_tags_page_has_stage_filter_dropdown_before_searchbox(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    barcode = f"ITALLFILT{suffix}"
    _seed_device("cleaning", barcode)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        html = app_client.get("/cosmetic/all_tags", follow_redirects=True).text
        assert 'id="cosmeticStageFilter"' in html
        assert 'data-stage="cleaning"' in html
        assert "All Stages" in html
        assert "prepend(select)" in html  # ahead of DataTables' search box
    finally:
        _cleanup(barcode)


def test_all_tags_stage_filter_options_are_templated_from_the_pipeline():
    # Options come from the `pipeline` context var (COSMETIC_NAV_STAGES),
    # not a hardcoded per-stage list — stays correct if the pipeline changes.
    src = open(pathlib.Path(ROOT) / "templates" / "cosmetic" / "all_tags.html", encoding="utf-8").read()
    assert '{% for s in pipeline %}' in src.split("cosmeticStageFilter", 1)[1][:400]
    assert 'value="{{ s.value }}"' in src
    assert "tr.getAttribute('data-stage') !== stage" in src
