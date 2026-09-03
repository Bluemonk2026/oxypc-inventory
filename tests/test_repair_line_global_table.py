"""Repair line (L1/L2, L3, L3/L4) moved onto the Global Table module
(static/js/global-table.js) 2026-09-03, alongside QC/Stress Test — same
migration already done for Cosmetic Received/Stage/Completed/All Tags,
WorkID Status, and All Inventory's summary tables.

Tag Number also moved before WorkID on all three pages, matching the
convention already applied to Cosmetic Stages, WorkID Status, and Devices —
Global Table freezes column 0 while scrolling, and the frozen column should
show the physical asset tag, not an internal WorkID string.
"""
import pathlib

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _read(name):
    return (pathlib.Path(ROOT) / "templates" / "repair" / name).read_text(encoding="utf-8")


def test_l1_table_uses_global_table_and_tag_number_first():
    src = _read("l1.html")
    assert "initGlobalTable('#l1Table'" in src
    assert "<th>Tag Number</th><th>WorkID</th>" in src
    assert 'id="l1Table"' in src


def test_l2_table_uses_global_table_and_tag_number_first():
    src = _read("l2.html")
    assert "initGlobalTable('#l2Table'" in src
    assert "<th>Tag Number</th><th>WorkID</th>" in src


def test_l2_card_header_has_no_count():
    src = _read("l2.html")
    assert "Devices in L1/L2 ({{ devices|length }})" not in src
    assert ">Devices in L1/L2</div>" in src


def test_l3_table_uses_global_table_and_tag_number_first():
    src = _read("l3.html")
    assert "initGlobalTable('#l3Table'" in src
    assert "<th>Tag Number</th><th>WorkID</th>" in src


def test_l3_card_header_has_no_count():
    src = _read("l3.html")
    assert "Devices in L3 ({{ devices|length }})" not in src
    assert ">Devices in L3</div>" in src


def test_l3l4_table_uses_global_table_and_tag_number_first():
    src = _read("l3l4.html")
    assert "initGlobalTable('#l3l4Table'" in src
    assert "<th>Tag Number</th><th>WorkID</th>" in src
    # emptyTable language override survives the migration (initGlobalTable
    # deep-merges dtOptions.language onto its own defaults).
    assert 'emptyTable: "No L3/L4 work orders assigned."' in src


def test_l3l4_card_header_has_no_count_and_pna_filter_moved_to_toolbar():
    src = _read("l3l4.html")
    assert "L3/L4 Work Orders (" not in src
    assert ">L3/L4 Work Orders</span>" in src
    # "Only show PNA" now injects into .dataTables_filter via initComplete,
    # same convention as L1/L2's PNA/Failed-from-Final-QC filters.
    assert ".dataTables_filter" in src
    assert 'id="onlyPnaL34"' in src


def test_l3l4_repair_notes_no_longer_manually_pre_truncated():
    # Same fix as Lot Based Summary's Remarks column
    # (templates/devices/list.html): a [:150]-sliced cell with its own
    # title= tooltip fought initGlobalTable's own clamp+tooltip.
    src = _read("l3l4.html")
    assert "it.repair_notes[:150]" not in src
    assert 'class="note-clamp' not in src


def test_none_of_the_four_repair_tables_have_a_table_responsive_wrapper():
    # initGlobalTable's own scrollX owns horizontal scrolling now — a nested
    # .table-responsive would risk a second, redundant scrollbar.
    for name, table_id in [
        ("l1.html", "l1Table"), ("l2.html", "l2Table"),
        ("l3.html", "l3Table"), ("l3l4.html", "l3l4Table"),
    ]:
        src = _read(name)
        table_pos = src.index(f'id="{table_id}"')
        preceding = src[:table_pos]
        assert '<div class="table-responsive">' not in preceding[-300:], name
