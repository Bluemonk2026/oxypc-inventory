"""Global Table behavior (2026-09-02) — a reusable server-side DataTables
pattern (static/js/global-table.js + .gtable* classes in app.css): single-line
headers, horizontal scroll with the first column frozen (CSS position:sticky,
no FixedColumns plugin), 2-line cell truncation with a native title= tooltip,
a "Page view" dropdown + warning-badge row count on the left, search +
pagination on the right, and checkbox multi-select with scan-to-select.

Demonstrated first on Inventory Search (#devicesTable / /devices/data) — the
heaviest table in the app (~19-22k devices in production) — since it already
had server-side paging, checkboxes, and scan-to-select; this batch layers the
shared behavior on top without changing any of that.

Also covers the query-optimization piece: Device.device_type gained an index
since it's an exact-match filter/sort column on this same endpoint.
"""
import pathlib
import subprocess
import sys
import time
import uuid

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def _seed_heavy_devices(marker, count):
    """One subprocess, one transaction, `count` devices — fast enough to
    exercise real pagination without spawning a subprocess per row."""
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        for i in range({count}):
            db.add(Device(barcode="{marker}" + str(i).zfill(5), lot_id=lot.id,
                          brand="{marker}", model="HeavyLoadModel", device_type="Laptop",
                          current_stage=DeviceStage.stock_in))
        await db.commit()

asyncio.run(main())
""")


def _cleanup(marker):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        for d in (await db.execute(select(Device).where(Device.brand == "{marker}"))).scalars().all():
            await db.delete(d)
        await db.commit()

asyncio.run(main())
""")


def test_global_table_js_loaded_on_every_page(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/devices", follow_redirects=True).text
    assert '/static/js/global-table.js' in html


def test_global_table_css_classes_present():
    css = pathlib.Path(ROOT, "static", "css", "app.css").read_text(encoding="utf-8")
    assert ".gtable thead th" in css
    assert ".gtable-clamp2" in css
    assert ".gtable-scroll-wrap" in css
    assert ".gtable-count-badge" in css
    # First/last (checkbox/Action) column centering + the 14px default size.
    assert "text-align: center" in css
    assert "font-size: 14px" in css
    # The overflow:hidden-vs-position:sticky conflict with the app-wide
    # ".card-body table" rounded-corner rule, found via live browser testing.
    assert ".card-body .gtable" in css
    # DataTables' div.dataTables_wrapper div.dataTables_info rule (specificity
    # 0,2,2) pads the info slot for its traditional bottom-row position;
    # re-skinned as the top-left count badge, that padding pushed it visibly
    # below the length dropdown's vertical center — also found live.
    assert ".gtable-top .dataTables_info" in css
    assert "padding-top: 0 !important" in css


def test_global_table_button_labels_never_wrap():
    """2026-09-03: button labels (icon or no icon) must stay on one line
    everywhere Global Table owns the markup — the Action column (a flex/
    inline-block button can still wrap its own text once its column gets
    tight) and the table-top toolbar (a flex-wrap row that can shrink a
    button below its label's natural width on a narrow viewport)."""
    css = pathlib.Path(ROOT, "static", "css", "app.css").read_text(encoding="utf-8")
    assert ".gtable-top .btn" in css
    assert ".gtable-top button" in css
    toolbar_rule = css[css.index(".gtable-top .btn"):][:120]
    assert "white-space: nowrap;" in toolbar_rule


def test_global_table_js_clamps_every_column_by_default():
    js = pathlib.Path(ROOT, "static", "js", "global-table.js").read_text(encoding="utf-8")
    assert "clampLength || 32" in js
    assert "'_all'" in js


def test_global_table_js_clamps_a_value_of_exactly_clamp_length():
    """2026-09-02: real CPU strings like "Intel Core i7-10810U @ 1.61 GHz"
    land at exactly 32 characters and were silently skipping the clamp under
    the old `<=` comparison ("over 32" only) — confirmed live on /devices.
    `< clampLength` (not `<=`) means "at or over the threshold" clamps."""
    js = pathlib.Path(ROOT, "static", "js", "global-table.js").read_text(encoding="utf-8")
    assert "text.length < clampLength" in js
    assert "text.length <= clampLength" not in js


def test_devices_table_wired_to_global_table(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/devices", follow_redirects=True).text
    assert "initGlobalTable('#devicesTable'" in html
    assert "scan: { inputId: 'devicesScanInput'" in html


def test_devices_table_has_global_table_card_header():
    """Global Table convention: a card-header with an icon + title (here
    "All Tags Inventory") — same pattern as templates/cosmetic/received.html's
    "Devices in {{ stage_label }}" bar. No plain count badge here — instead
    this table's own action buttons (Delete Selected/Customise/Upload Tags/
    Export CSV), since they act only on this table. The entity breakdown
    badges move (via JS) into the DataTables toolbar, right after the
    row-count badge next to the "Page view" dropdown — not the card-header,
    not the Results Header."""
    src = pathlib.Path(ROOT, "templates", "devices", "list.html").read_text(encoding="utf-8")
    assert "card-header bg-transparent d-flex justify-content-between align-items-center" in src
    assert "All Tags Inventory" in src
    assert 'class="badge bg-warning text-dark">{{ total }} device(s)</span>' not in src
    # DataTables' dom-string mini-language needs dot-prefixed classes after
    # an id (#id.class1.class2) — a space-separated list gets read as one
    # literal (and broken) id value instead. Regression coverage for that.
    assert '<"#entityBadgeArea.d-flex.flex-wrap.gap-2">' in src  # toolbar dom slot
    assert "#entityBadgeArea d-flex flex-wrap gap-2\"" not in src  # the broken form
    assert "$('#entityBadgeArea').append($('#entityBadges')" in src  # JS relocation
    # The 4 buttons now live inside the card-header, not the Results Header.
    header_start = src.index('class="card-header bg-transparent')
    header_end = src.index('<div class="card-body p-0">')
    header_block = src[header_start:header_end]
    for btn_id in ("bulkDeleteBtn", "customiseBtn", "bulkTagModal", "exportCsvLink"):
        assert btn_id in header_block, btn_id


def test_devices_data_uses_badges_not_small_and_btn_sm_not_btn_xs():
    """Tag Number stays plain clickable link text (not a badge chip) — only
    the entity subline and the assigned Location ID render as .badge chips
    (replacing the old bare .small text). The Assign + View/Edit/Trash
    buttons use real Bootstrap .btn-sm (em-relative, scales with the table's
    14px default) instead of this app's old .btn-xs (rem-relative — stayed
    16px regardless of the table's own font-size)."""
    import inspect
    from routers import devices as dv

    src = inspect.getsource(dv.device_search_data)
    assert "btn-xs" not in src
    assert '"small' not in src  # no leftover bare .small usage on these cells
    assert 'class="font-monospace fw-bold text-decoration-none">{esc(d.barcode)}</a>' in src  # Tag Number — plain link text
    assert 'class="badge bg-light text-dark border"' in src  # entity subline
    assert 'class="badge bg-light text-dark border font-monospace"' in src  # assigned Location ID
    assert 'class="btn btn-sm btn-outline-primary py-0 px-2"' in src  # Assign
    assert 'class="btn btn-sm btn-outline-primary py-0 px-1"' in src  # View
    assert 'class="btn btn-sm btn-outline-warning py-0 px-1"' in src  # Edit
    assert 'class="btn btn-sm btn-outline-danger py-0 px-1 trash-one-btn"' in src  # Trash
    # The Action column's flex wrapper needs its own centering — a flex
    # child ignores the <td>'s text-align:center.
    assert "d-flex gap-1 justify-content-center" in src


def test_devices_table_markup_is_full_width_no_nested_scroll_wrapper(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/devices", follow_redirects=True).text
    assert 'id="devicesTable" class="table table-hover table-sm mb-0" style="width:100%"' in html
    # scrollX's own wrapper handles horizontal scrolling — a nested Bootstrap
    # .table-responsive around the same table would risk a second scrollbar.
    assert '<div class="table-responsive">\n      <table id="devicesTable"' not in html


def test_device_type_column_is_indexed():
    import inspect
    from models import device as dev_module
    src = inspect.getsource(dev_module.Device)
    assert "device_type = Column(String(30), nullable=True, index=True)" in src


def test_devices_data_heavy_load_pagination_is_correct(app_client, make_user):  # noqa: F811
    marker = "GTBLHVY" + uuid.uuid4().hex[:6].upper()
    _seed_heavy_devices(marker, 130)
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)

        started = time.monotonic()
        r = app_client.get("/devices/data", params={
            "draw": 1, "start": 0, "length": 12, "search[value]": marker,
        })
        elapsed = time.monotonic() - started
        assert r.status_code == 200
        body = r.json()
        assert body["recordsFiltered"] == 130
        assert len(body["data"]) == 12
        # Not a hard perf benchmark — just a sanity ceiling that a single
        # page of a 130-row filtered, indexed query stays fast.
        assert elapsed < 8, f"took {elapsed:.2f}s"

        # Second page picks up where the first left off, same filtered total.
        r2 = app_client.get("/devices/data", params={
            "draw": 2, "start": 12, "length": 12, "search[value]": marker,
        })
        body2 = r2.json()
        assert body2["recordsFiltered"] == 130
        assert len(body2["data"]) == 12
        first_page_barcodes = {row[1] for row in body["data"]}
        second_page_barcodes = {row[1] for row in body2["data"]}
        assert first_page_barcodes.isdisjoint(second_page_barcodes)
    finally:
        _cleanup(marker)
