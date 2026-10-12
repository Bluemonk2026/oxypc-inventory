"""Ready for Sale Tag page (/sales/ready): two tab groups (Ready for Sale | As-Is) and the
Touch Type badge (T / NT, default NT) next to the Tag Number (2026-10-12)."""
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
    lines = r.stdout.strip().splitlines()
    return lines[-1] if lines else ""


def test_page_has_two_tab_groups_with_four_tabs(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/sales/ready", follow_redirects=True).text

    # group 1 and group 2, each with its own nav-tabs
    assert 'id="readyGroupTabs"' in html and 'id="asIsGroupTabs"' in html
    g1 = html[html.index('id="readyGroupTabs"'):html.index('id="asIsGroupTabs"')]
    g2 = html[html.index('id="asIsGroupTabs"'):]
    assert "Ready for Sale Tags</button>" in g1 and "Ready for Sale Model Summary</button>" in g1
    assert "As-Is Lot</button>" in g2 and "As-Is Model Summary</button>" in g2
    assert "As-Is Lot</button>" not in g1 and "Ready for Sale Tags</button>" not in g2

    # each tab drives its own pane; one table per pane, in the right group
    for tab, pane in (("rs-tags-tab", "rs-tags-pane"), ("rs-models-tab", "rs-models-pane"),
                      ("ai-lot-tab", "ai-lot-pane"), ("ai-models-tab", "ai-models-pane")):
        assert f'id="{tab}"' in html and f'data-bs-target="#{pane}"' in html and f'id="{pane}"' in html
    for table in ("readyTable", "readyModelSummaryTable"):
        assert f'id="{table}"' in html
    ready_part = html[html.index('id="readyGroup"'):html.index('id="asIsGroup"')]
    as_is_part = html[html.index('id="asIsGroup"'):html.index('id="asIsLotEditModal"')]
    assert 'id="readyTable"' in ready_part and 'id="readyModelSummaryTable"' in ready_part
    assert 'id="asIsLotTable"' in as_is_part and 'id="asIsModelSummaryTable"' in as_is_part

    # bulk / select-all controls live only in the Ready for Sale group; DataTables re-fit on tab show
    for ctl in ("readySelectAll", "multiSellBtn", "newBulkSaleBtn", "bulkSetPriceBtn", "ms_val_entity"):
        assert ctl in ready_part and ctl not in as_is_part, ctl
    assert "shown.bs.tab" in html and "columns.adjust()" in html


SEED = r'''
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage

TAG = "{tag}"
async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        db.add_all([
            Device(barcode=TAG + "T", lot_id=lot.id, brand="B", model="M", touch_type="Touch",
                   current_stage=DeviceStage.ready_to_sale),
            Device(barcode=TAG + "N", lot_id=lot.id, brand="B", model="M",
                   current_stage=DeviceStage.ready_to_sale),
        ])
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
        await db.execute(text("delete from stage_movements where device_id in (" + ids + ")"))
        await db.execute(text("delete from devices where barcode like '{tag}%'"))
        await db.commit()
asyncio.run(main())
'''


def test_data_feed_tag_cell_has_touch_badge_default_nt(app_client, make_user):  # noqa: F811
    tag = "ITTCH" + uuid.uuid4().hex[:6].upper()
    _run(SEED.format(root=ROOT, tag=tag))
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        d = app_client.get("/sales/ready/data", params={"search[value]": tag, "length": 50}).json()
        cells = {re.search(r"<code[^>]*>([^<]+)</code>", c[1]).group(1): c for c in d["data"]}
        touch, plain = cells[tag + "T"], cells[tag + "N"]

        # badge sits in the Tag Number cell itself (right after the barcode link)
        assert ">T</span>" in touch[1] and ">NT</span>" not in touch[1]
        assert ">NT</span>" in plain[1] and ">T</span>" not in plain[1]            # NULL touch_type => NT
        assert touch[1].index("</a>") < touch[1].index(">T</span>")
        # the barcode text the scan JS relies on is untouched: checkbox value + <code>
        assert f'value="{tag}T"' in touch[0] and f"<code class=\"fw-bold\">{tag}T</code>" in touch[1]
    finally:
        _run(CLEAN.format(root=ROOT, tag=tag))
