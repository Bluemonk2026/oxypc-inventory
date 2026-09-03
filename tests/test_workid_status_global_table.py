"""WorkID Status (/workid-status) moved onto the Global Table module
(static/js/global-table.js) 2026-09-03 — frozen Tag Number column (already
first per the 2026-09-02 reorder), 32-char clamp+tooltip (most useful on the
free-text Notes column, which had no truncation at all before), and the
standard toolbar/count-badge convention in place of a plain header count.
"""
import pathlib

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _read():
    return (pathlib.Path(ROOT) / "templates" / "workid_status" / "list.html").read_text(encoding="utf-8")


def test_workid_table_uses_global_table():
    src = _read()
    assert "initGlobalTable('#workidTable'" in src


def test_workid_table_keeps_the_empty_table_guard():
    # DataTables errors if initialized on a table with only the "No WorkIDs
    # found." colspan row — this guard predates the Global Table move and
    # must survive it unchanged.
    src = _read()
    assert "if ($('#workidTable tbody tr td').length > 1) {" in src


def test_workid_table_card_header_has_no_count_badge():
    src = _read()
    header_start = src.index('class="card-header bg-transparent fw-semibold')
    header_end = src.index('<div class="card-body p-0">')
    header_block = src[header_start:header_end]
    assert "Work ID Details" in header_block
    assert "WorkID(s)" not in header_block


def test_workid_table_has_no_table_responsive_wrapper():
    # initGlobalTable's own scrollX owns horizontal scrolling now — a nested
    # .table-responsive would risk a second, redundant scrollbar (same
    # convention as templates/devices/list.html's #devicesTable).
    src = _read()
    table_pos = src.index('id="workidTable"')
    preceding = src[:table_pos]
    assert '<div class="table-responsive">' not in preceding[-200:]
