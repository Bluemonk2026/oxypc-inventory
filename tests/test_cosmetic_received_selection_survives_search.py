"""Cosmetic Received — selection state survives a new search (2026-09-15):

Reported: "search is working but auto select with search is not working
also the count in Assign button is showing only 1 selected at a time and
every search remove previously selected item". Root cause: the page's
DataTables instance is plain client-side (no server-side ajax), and
DataTables DETACHES any row that doesn't match the current page/search from
the live document — a document-scoped `$('.cosmeticRecvRowCheck:checked')`
(the old count/submit logic) simply stops seeing a row the moment a later
search moves it off-screen, even though the checkbox itself is still
logically "checked" on its (now detached) DOM node. The actual bulk-assign
submit had the same bug: it silently dropped any previously-ticked tag a
later search had scrolled out of the DOM.

Fixed by tracking selection in a persistent `cosmeticRecvSelected` Set
(same pattern as templates/devices/list.html's devicesSelected) instead of
trusting live DOM :checked state — see templates/cosmetic/received.html.
Also added scan-to-select (opts.scan) on the same search box, which this
page never had at all, addressing "auto select with search is not
working".
"""
import pathlib

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _received_html():
    return (pathlib.Path(ROOT) / "templates" / "cosmetic" / "received.html").read_text(encoding="utf-8")


def test_selection_tracked_in_a_persistent_set_not_dom_checked_state():
    html = _received_html()
    assert "var cosmeticRecvSelected = new Set();" in html
    # The count/button-state function must read the Set, not a DOM query.
    assert "cosmeticRecvSelected.size" in html
    assert "$('.cosmeticRecvRowCheck:checked').length" not in html


def test_bulk_assign_submit_reads_from_the_set_not_dom_checked_state():
    html = _received_html()
    assert "var barcodes = Array.from(cosmeticRecvSelected);" in html
    assert "$('.cosmeticRecvRowCheck:checked').map(" not in html


def test_draw_callback_reapplies_checked_state_from_the_set():
    """A row ticked, then filtered out by a search, then brought back by a
    later search/clear must come back visibly checked — not reset."""
    html = _received_html()
    assert "drawCallback: function() {" in html
    assert "cb.checked = cosmeticRecvSelected.has(cb.value);" in html


def test_scan_to_select_is_wired_on_the_search_box():
    """Previously this table had no opts.scan at all — only plain free-text
    filtering, so typing/scanning a tag number never auto-ticked its row."""
    html = _received_html()
    assert "scan: { inputId: 'cosmeticRecvScanInput'" in html
    assert "selection: cosmeticRecvSelected" in html


def test_tag_scan_autocheck_script_is_loaded():
    """opts.scan calls initScanSelect()/initTagScanAutocheck(), defined in
    static/js/tag-scan-autocheck.js — that file isn't loaded globally
    (base.html), only per-page as needed. Without this <script> tag,
    initGlobalTable() throws a ReferenceError partway through and silently
    never reaches its opts.selectAll wiring either — live-verified in the
    browser 2026-09-15: checking rows did nothing at all (worse than the
    original bug) until this tag was added."""
    html = _received_html()
    assert 'src="/static/js/tag-scan-autocheck.js' in html


def test_select_all_header_reconciles_into_the_same_set():
    """global-table.js's select-all header handler only ever touches
    checkbox .prop() — it has no idea the Set exists. The onChange callback
    must resync from dt.rows({search:'applied'}) so select-all (which can
    toggle off-page rows too) is reflected in the Set, not just the count."""
    html = _received_html()
    assert "cosmeticRecvDt.rows({search: 'applied'}).nodes()" in html
