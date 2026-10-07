"""Production Manager page — per-tile "Summary" CSV downloads.

Every summary tile (except PNA, which has its own endpoint) links to
GET /trc-production/summary/{tile}; the CSV holds exactly the tags the tile
counts (shared criterion in routers.stock._prod_tile_criteria).
"""
import csv
import io
import uuid

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)
from tests.test_production_manager_summary_tiles import _cleanup, _run, _seed

# tile -> (stage that belongs, stage that does not)
TILES = {
    "at-you": ("trc_production", "l3"),
    "l1-l2": ("l2", "trc_production"),
    "l3-l4": ("l3", "l1"),
    "stress": ("qc_check", "l3"),
    "cosmetic": ("painting", "l1"),
    "final-qc": ("final_qc_fail_hold", "qc_check"),
    "returned": ("l1", "l2"),
}


def _set_return_status(barcode, status):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{__import__('tests.test_production_manager_summary_tiles', fromlist=['ROOT']).ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one()
        dev.tag_return_status = "{status}"
        await db.commit()

asyncio.run(main())
""")


def _rows(resp):
    return list(csv.reader(io.StringIO(resp.text)))


def test_each_tile_summary_csv(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    seeded = {}
    try:
        for tile, (yes_stage, no_stage) in TILES.items():
            key = tile.replace("-", "")[:6].upper()
            yes_bc, no_bc = f"ITSUMY{key}{suffix}", f"ITSUMN{key}{suffix}"
            _seed(yes_bc, yes_stage)
            _seed(no_bc, no_stage)
            seeded[tile] = (yes_bc, no_bc)
        # Returned tile: first device marked for repair, the second is not.
        _set_return_status(seeded["returned"][0], "Return for Repair")

        username, password = make_user("admin")
        _login(app_client, username, password)

        for tile, (yes_bc, no_bc) in seeded.items():
            r = app_client.get(f"/trc-production/summary/{tile}", follow_redirects=True)
            assert r.status_code == 200, tile
            assert r.headers["content-type"].startswith("text/csv"), tile
            assert f"trc_{tile.replace('-', '_')}_summary.csv" in r.headers["content-disposition"]
            rows = _rows(r)
            header = ["Tag Number", "Brand", "Model", "Lot Number", "Stage", "Updated At"]
            if tile == "returned":
                header.append("Return Status")
            assert rows[0] == header, tile
            tags = {row[0] for row in rows[1:]}
            assert yes_bc in tags, tile
            assert no_bc not in tags, tile
            if tile == "returned":
                row = next(x for x in rows[1:] if x[0] == yes_bc)
                assert row[-1] == "Return for Repair"
    finally:
        for yes_bc, no_bc in seeded.values():
            _cleanup(yes_bc)
            _cleanup(no_bc)


def test_unknown_tile_is_404(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    r = app_client.get("/trc-production/summary/bogus", follow_redirects=True)
    assert r.status_code == 404


def test_page_has_summary_link_for_every_tile(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/trc-production", follow_redirects=True).text
    for tile in TILES:
        assert f'href="/trc-production/summary/{tile}"' in html, tile
    assert 'href="/trc-production/pna-summary"' in html
