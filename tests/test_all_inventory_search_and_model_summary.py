"""All Inventory (/devices): token-wise search over Make / Model / RAM / CPU /
Storage, the Touch Type badge next to the Tag Number, and the rebuilt Model Based
Summary (CPU / RAM / Storage / Touch / Grade / Stock Type / entity badges + Total
row, fed from the same filtered tag set as the Tag table) — 2026-10-12.
"""
import json
import pathlib
import random
import re
import subprocess
import sys
import uuid

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


# ── pure helpers ─────────────────────────────────────────────────────────────
def test_search_tokens_split_on_whitespace_and_glue_units():
    from utils.inventory_summary import search_tokens
    assert search_tokens("HP 840 16GB i5 512") == ["HP", "840", "16GB", "i5", "512"]
    assert search_tokens("hp  840 16 GB, i5   1 TB") == ["hp", "840", "16GB", "i5", "1TB"]
    assert search_tokens("") == [] and search_tokens("   ") == [] and search_tokens(None) == []


def _sql(clause):
    from sqlalchemy.dialects import postgresql
    return str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_every_token_must_match_and_ram_storage_are_matched_numerically():
    from utils.inventory_summary import device_search_clause
    sql = _sql(device_search_clause("HP 16GB 512"))
    assert sql.count(" AND ") == 2                    # one OR-group per token, AND-ed
    assert "devices.ram_gb IN (16)" in sql and "devices.storage_gb IN (512)" in sql
    assert "devices.brand ILIKE" in sql and "devices.cpu ILIKE" in sql and "devices.model ILIKE" in sql
    # a unit token ("16GB") is RAM/Storage only; it must not hit Make/Model/CPU text
    unit_group = _sql(device_search_clause("16GB"))
    assert "devices.model" not in unit_group and "devices.cpu" not in unit_group
    # 1TB is 1000 or 1024 GB; out-of-range numbers never reach the integer columns
    assert "IN (1000, 1024)" in _sql(device_search_clause("1TB"))
    assert "ram_gb IN" not in _sql(device_search_clause("99999999999"))
    assert device_search_clause("  ") is None


def test_wildcards_in_a_search_are_literal():
    from utils.inventory_summary import device_search_clause
    assert "\\%" in _sql(device_search_clause("100%"))


def test_entity_abbreviation_is_deterministic():
    from utils.inventory_summary import entity_abbr
    assert entity_abbr("OxyPC Computers") == "OC"
    assert entity_abbr("Renew Circuits") == "RC"
    assert entity_abbr("Deshwal") == "DES"
    assert entity_abbr("Blue Monk Venture Group Ltd") == "BMVG"      # capped at 4
    assert entity_abbr("  renew   circuits ") == "RC"
    assert entity_abbr("Unassigned") == "UNA"
    assert entity_abbr("") == "NA" and entity_abbr(None) == "NA"


def _row(**kw):
    base = dict(make="HP", model="840", device_type="Laptop", cpu="i5", ram="16GB", storage="512GB SSD",
                touch="Non-Touch", grade="A", stock="Finish Good", entity="OxyPC Computers",
                n=1, price=100, repaired=0)
    base.update(kw)
    return base


def _text(html):
    return " ".join(re.findall(r">([^<]+)<", html))


def test_rows_split_when_any_group_attribute_differs():
    from utils.inventory_summary import fold_summary_rows
    base = _row()
    variants = [dict(model="850"), dict(make="Dell"), dict(device_type="Desktop"),
                dict(cpu="i7"), dict(ram="8GB"), dict(storage="256GB SSD")]
    groups, totals = fold_summary_rows([base] + [_row(**v) for v in variants])
    assert len(groups) == 7 and totals["total_count"] == 7
    # touch / grade / stock / entity differences do NOT split a row
    groups, _ = fold_summary_rows([base, _row(grade="B", touch="Touch", stock="As-Is", entity="Renew Circuits")])
    assert len(groups) == 1 and groups[0]["total_count"] == 2


def test_badge_strings_and_total_row():
    from utils.inventory_summary import fold_summary_rows, group_row_cells, total_row_cells
    rows = [
        _row(n=3, grade="A", touch="Non-Touch", stock="Finish Good", entity="OxyPC Computers", price=300),
        _row(n=2, grade="B", touch="Touch", stock="As-Is", entity="Renew Circuits", price=200),
        _row(n=1, grade=None, touch=None, stock="In Progress", entity="OxyPC Computers", price=50),
        _row(model="850", n=4, grade="A", touch="Touch", stock="Finish Good", entity="Renew Circuits", price=400),
    ]
    groups, totals = fold_summary_rows(rows)
    g = next(x for x in groups if x["model"] == "840")
    cells = group_row_cells(g, True, "")
    # Make, Model, Device Type, CPU, RAM, Storage, Touch, Grade, Stock, Total Count, Price, Actions
    assert cells[:6] == ["HP", "840", "Laptop", "i5", "16GB", "512GB SSD"]
    assert _text(cells[6]) == "T-2 NT-4"
    assert _text(cells[7]) == "A-3 B-2 Ungraded-1"
    assert _text(cells[8]) == "Finish Good-3 As-Is-2 In Progress-1"
    assert _text(cells[9]) == "6 OC-4 RC-2"
    assert cells[10] == "₹550"
    assert "flex-nowrap" in cells[7] and "text-nowrap" in cells[7]         # one line
    # Total row: numeric columns summed, badge columns aggregated across every row
    total = total_row_cells(totals, True)
    assert "Total" in total[0] and total[1:6] == [""] * 5
    assert _text(total[6]) == "T-6 NT-4"
    assert _text(total[7]) == "A-7 B-2 Ungraded-1"
    assert _text(total[8]) == "Finish Good-7 As-Is-2 In Progress-1"
    assert _text(total[9]) == "10 RC-6 OC-4"
    assert "₹950" in total[10]
    # no pricing -> no price cell in either row
    assert len(group_row_cells(g, False, "")) == 11 and len(total_row_cells(totals, False)) == 11


def test_repaired_is_computed_but_not_a_column():
    from utils.inventory_summary import fold_summary_rows, group_row_cells
    groups, _ = fold_summary_rows([_row(repaired=1)])
    assert groups[0]["repaired_count"] == 1
    assert len(group_row_cells(groups[0], True, "")) == 12              # 6 keys + 3 badges + count + price + actions


def test_template_has_new_columns_filters_and_no_repaired_column(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/devices", follow_redirects=True).text
    head = html.split('<table id="modelSummaryTable"', 1)[1].split("</thead>", 1)[0]
    cols = re.findall(r"<th>([^<]*)</th>", head)
    assert cols[:10] == ["Make", "Model", "Device Type", "CPU", "RAM", "Storage",
                         "Touch Type", "Grade", "Stock Type", "Total Count"]
    assert "Repaired" not in head
    for name in ("make", "touch", "stock_type", "device_type", "grade", "entity"):
        assert f'id="ms_val_{name}"' in html, name


# ── real rows ────────────────────────────────────────────────────────────────
SEED = r'''
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage, DeviceGrade

TAG = "{tag}"
MK = "{mk}"
E1, E2 = "{e1}", "{e2}"
I5 = "Intel Core i5-8350U"
async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        def dev(sfx, **kw):
            d = dict(barcode=TAG + sfx, lot_id=lot.id, brand=MK, model="Latitude 840", device_type="Laptop",
                     cpu=I5, ram_gb=16, storage_gb=512, storage_type="SSD", grade=DeviceGrade.A,
                     entity=E1, current_stage=DeviceStage.ready_to_sale)
            d.update(kw)
            return Device(**d)
        db.add_all([
            dev("1"),                                                              # Finish Good, NT, A
            dev("2", grade=DeviceGrade.B, touch_type="Touch", entity=E2, sub_lot_number="SL-1"),   # As-Is, T, B
            dev("3", current_stage=DeviceStage.l1),                                # In Progress
            dev("4", ram_gb=8),                                                    # own row (RAM differs)
            dev("5", model="Elitebook 850", cpu="AMD Ryzen 5 PRO", storage_gb=1000, storage_type="HDD", entity=E2),
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


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=90)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")


class _Seeded:
    def __init__(self):
        # letters only (no digits / no D, H, I, S): a numeric or "hdd"/"ssd"/"i5" search
        # term must never match the random barcode or make by accident
        rnd = "".join(random.choice("ABCEFGJK") for _ in range(8))
        self.tag = "ITSUM" + rnd
        self.mk = "ZZMK" + rnd
        self.e1, self.e2 = "Zeta Omega Test", "Yank Peru Quad"       # abbreviations ZOT / YPQ

    def __enter__(self):
        _run(SEED.format(root=ROOT, tag=self.tag, mk=self.mk, e1=self.e1, e2=self.e2))
        return self

    def __exit__(self, *exc):
        _run(CLEAN.format(root=ROOT, tag=self.tag))

    def tags(self, *nums):
        return {self.tag + str(n) for n in nums}


def _tag_search(client, seeded, search):
    """Barcodes of the seeded devices the Tag table's search box returns."""
    d = client.get("/devices/data", params={"make": seeded.mk, "search[value]": search, "length": 50,
                                            "fs": "1", "exclude_sold": ""}).json()
    return {re.search(r"/devices/([^\"]+)\"", c[1]).group(1) for c in d["data"]}


def _summary(client, seeded, **params):
    p = {"make": seeded.mk, "length": 50, "fs": "1", "exclude_sold": ""}
    p.update(params)
    return client.get("/devices/model-summary/data", params=p).json()


def test_tag_table_search_each_column_alone_and_combined(app_client, make_user):  # noqa: F811
    with _Seeded() as s:
        username, password = make_user("admin")
        _login(app_client, username, password)
        check = lambda q: _tag_search(app_client, s, q)                     # noqa: E731
        everything = s.tags(1, 2, 3, 4, 5)
        assert check("") == everything
        assert check(s.mk) == everything                                    # Make
        assert check("Elitebook") == s.tags(5)                              # Model
        assert check("840") == s.tags(1, 2, 3, 4)
        assert check("i5") == s.tags(1, 2, 3, 4)                            # CPU
        assert check("ryzen") == s.tags(5)
        assert check("16") == s.tags(1, 2, 3, 5)                            # RAM, number only
        assert check("16GB") == s.tags(1, 2, 3, 5)
        assert check("16 GB") == s.tags(1, 2, 3, 5)                         # spaced unit
        assert check("8gb") == s.tags(4)
        assert check("512") == s.tags(1, 2, 3, 4)                           # Storage
        assert check("512GB") == s.tags(1, 2, 3, 4)
        assert check("ssd") == s.tags(1, 2, 3, 4)
        assert check("1tb") == s.tags(5)                                    # 1TB == 1000GB
        assert check("hdd") == s.tags(5)
        # every token must match, each in a different column
        assert check("840 16GB i5 512") == s.tags(1, 2, 3)
        assert check(f"{s.mk} 840 8gb") == s.tags(4)
        assert check("840 ryzen") == set()
        assert check("840 32gb") == set()


def test_page_level_q_uses_the_same_token_search(app_client, make_user):  # noqa: F811
    with _Seeded() as s:
        username, password = make_user("admin")
        _login(app_client, username, password)
        d = app_client.get("/devices/data", params={"q": f"{s.mk} 840 16GB i5 512", "length": 50,
                                                    "fs": "1", "exclude_sold": ""}).json()
        assert d["recordsFiltered"] == 3


def test_tag_cell_shows_touch_badge_next_to_tag_number(app_client, make_user):  # noqa: F811
    with _Seeded() as s:
        username, password = make_user("admin")
        _login(app_client, username, password)
        d = app_client.get("/devices/data", params={"make": s.mk, "length": 50, "fs": "1", "exclude_sold": ""}).json()
        cell = {re.search(r"/devices/([^\"]+)\"", c[1]).group(1): c for c in d["data"]}
        assert ">NT</span>" in cell[s.tag + "1"][1] and ">T</span>" not in cell[s.tag + "1"][1]   # NULL => NT
        assert ">T</span>" in cell[s.tag + "2"][1]
        # barcode link and checkbox value are untouched
        assert f'value="{s.tag}1"' in cell[s.tag + "1"][0]
        assert f'<a href="/devices/{s.tag}1"' in cell[s.tag + "1"][1]
        # Stock Type column follows _stock_label (In Progress for a live stage)
        assert "In Progress" in cell[s.tag + "3"][11] and "As-Is" in cell[s.tag + "2"][11]


def test_summary_rows_badges_and_total_row(app_client, make_user):  # noqa: F811
    with _Seeded() as s:
        username, password = make_user("admin")
        _login(app_client, username, password)
        d = _summary(app_client, s)
        assert d["recordsFiltered"] == 3                                    # 840/16GB, 840/8GB, 850
        *rows, total = d["data"]
        assert "Total" in total[0] and len(rows) == 3
        by_ram_model = {(r[1], r[4]): r for r in rows}
        main = by_ram_model[("Latitude 840", "16GB")]
        assert main[:6] == [s.mk, "Latitude 840", "Laptop", "Intel Core i5-8350U", "16GB", "512GB SSD"]
        assert _text(main[6]) == "T-1 NT-2"
        assert _text(main[7]) == "A-2 B-1"
        assert _text(main[8]) == "Finish Good-1 As-Is-1 In Progress-1"
        assert _text(main[9]) == "3 ZOT-2 YPQ-1"
        assert by_ram_model[("Latitude 840", "8GB")][5] == "512GB SSD"
        assert by_ram_model[("Elitebook 850", "16GB")][5] == "1000GB HDD"
        # Total row: sums + aggregated badges across all rows
        assert _text(total[6]) == "T-1 NT-4"
        assert _text(total[7]) == "A-4 B-1"
        assert _text(total[8]) == "Finish Good-3 As-Is-1 In Progress-1"
        assert _text(total[9]) == "5 ZOT-3 YPQ-2"
        assert d["totals"]["total_count"] == 5


def test_summary_total_follows_filters_and_matches_the_tag_table(app_client, make_user):  # noqa: F811
    with _Seeded() as s:
        username, password = make_user("admin")
        _login(app_client, username, password)
        cases = [
            ({}, 5),
            ({"touch": "Touch"}, 1),
            ({"touch": "Non-Touch"}, 4),
            ({"stock_type": "In Progress"}, 1),
            ({"stock_type": "Finish Good,As-Is"}, 4),
            ({"grade": "B"}, 1),
            ({"entity": s.e2}, 2),
            ({"entity": s.e1}, 3),
            ({"device_type": "Laptop"}, 5),
            ({"device_type": "Desktop"}, 0),
            ({"search[value]": "16GB i5"}, 3),            # the summary's own search box
            ({"search[value]": "ryzen"}, 1),
            ({"search[value]": "nothing-matches"}, 0),
            ({"tag_search": s.tag + "2"}, 1),             # the Tag table's search box narrows it too
            ({"q": "850"}, 1),
        ]
        for params, expected in cases:
            d = _summary(app_client, s, **params)
            assert d["totals"]["total_count"] == expected, params
            if expected:
                assert _text(d["data"][-1][9]).split()[0] == str(expected), params
            else:
                assert d["data"] == [], params
            # the Tag table, given the same filters, lists exactly as many tags
            tag_params = {k: v for k, v in params.items() if k != "tag_search"}
            tag_params.update({"make": s.mk, "length": 50, "fs": "1", "exclude_sold": ""})
            if "tag_search" in params:
                tag_params["search[value]"] = params["tag_search"]
            assert app_client.get("/devices/data", params=tag_params).json()["recordsFiltered"] == expected, params
        # Make filter: another make removes them all
        assert _summary(app_client, s, make="NoSuchMake")["totals"]["total_count"] == 0
        # Total row covers the whole filtered set even when only one page is returned
        d = _summary(app_client, s, length=1)
        assert len(d["data"]) == 2 and d["totals"]["total_count"] == 5


def test_summary_modal_lists_exactly_the_tags_of_a_group(app_client, make_user):  # noqa: F811
    with _Seeded() as s:
        username, password = make_user("admin")
        _login(app_client, username, password)
        base = {"make": s.mk, "fs": "1", "exclude_sold": "", "g_make": s.mk, "g_model": "Latitude 840",
                "g_device_type": "Laptop", "g_cpu": "Intel Core i5-8350U", "g_storage": "512GB SSD"}
        got = lambda **kw: {t["barcode"] for t in app_client.get(              # noqa: E731
            "/devices/model-summary/tags", params={**base, **kw}).json()["tags"]}
        assert got(g_ram="16GB") == s.tags(1, 2, 3)
        assert got(g_ram="8GB") == s.tags(4)
        assert got(g_ram="16GB", touch="Touch") == s.tags(2)


def test_stock_sql_twin_agrees_with_stock_label():
    """utils.inventory_summary.stock_type_expr must stay in step with _stock_label."""
    from models.device import Device, DeviceStage
    from routers.devices import _stock_label
    from utils.inventory_summary import stock_type_expr
    sql = _sql(stock_type_expr())
    assert "ready_to_sale" in sql and "sold" in sql and "As-Is" in sql
    d = Device(current_stage=DeviceStage.ready_to_sale, sub_lot_number=" SL ")
    assert _stock_label(d) == "As-Is"
    assert _stock_label(Device(current_stage=DeviceStage.sold, sub_lot_number="")) == "Finish Good"
    assert _stock_label(Device(current_stage=DeviceStage.l1, sub_lot_number="SL")) == "In Progress"
