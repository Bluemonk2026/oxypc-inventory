"""Table row count next to DataTables' "Show N entries" dropdown on the
cosmetic pages. Originally a warning badge hand-injected into
.dataTables_length, updated on every draw — same pattern as the L1/L2 page's
count badge (templates/repair/l1.html). Only All Tags still uses that
original pattern; the three Cosmetic Stage templates below (Cosmetic
Received 2026-09-02, then Cleaning/Putty/Dry Sanding/Masking/Painting/Water
Sanding and Cosmetic Completed 2026-09-02) all moved to the Global Table
module instead (static/js/global-table.js) — their count badge is now
DataTables' own info slot, re-skinned via language.info, rather than a
hand-appended <span>.
"""
import pathlib

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _read(name):
    return open(pathlib.Path(ROOT) / "templates" / "cosmetic" / name, encoding="utf-8").read()


def test_count_badge_wired_into_dataTables_length_on_all_tags():
    src = _read("all_tags.html")
    assert 'id="cosmeticCountBadge" class="badge bg-warning text-dark' in src
    assert ".dataTables_length" in src
    assert "drawCallback: function() { updateCosmeticCountBadge(this.api()); }" in src
    assert "$('#cosmeticAllTagsTable').DataTable(" in src


def _assert_uses_global_table_no_hand_badge(name, table_id):
    src = _read(name)
    assert f"initGlobalTable('#{table_id}'" in src, name
    assert 'id="cosmeticCountBadge"' not in src, name  # replaced by the module's own badge


def _assert_card_header_has_no_count_badge(name):
    """Global Table convention: the card-header shows icon + title on the
    left and this table's own action buttons on the right if it has any —
    never a plain count badge (the table-top toolbar's own row-count badge
    already covers that)."""
    src = _read(name)
    header_start = src.index('class="card-header bg-transparent')
    header_end = src.index('<div class="card-body p-0">')
    header_block = src[header_start:header_end]
    assert "Devices in {{ stage_label }}" in header_block
    assert "badge" not in header_block
    assert "device(s)" not in header_block


def test_received_html_uses_global_table():
    _assert_uses_global_table_no_hand_badge("received.html", "cosmeticReceivedTable")
    # Admin-only Assign button + the Failed-from-Final-QC filter still prepend
    # into .dataTables_filter, same as before the migration.
    src = _read("received.html")
    assert ".dataTables_filter" in src
    assert 'id="cosmeticRecvAssignBtn"' in src
    assert 'id="cosmeticRecvFailedFqcFilter"' in src


def test_received_html_card_header_has_no_count_badge():
    # Cosmetic Received has no page-level buttons of its own (Assign is
    # admin-only and lives in the table-top toolbar instead), so its
    # card-header's right side is empty.
    _assert_card_header_has_no_count_badge("received.html")


def test_stage_html_uses_global_table():
    _assert_uses_global_table_no_hand_badge("stage.html", "cosmeticTable")


def test_stage_html_card_header_has_no_count_badge():
    _assert_card_header_has_no_count_badge("stage.html")


def test_completed_html_uses_global_table():
    _assert_uses_global_table_no_hand_badge("completed.html", "cosmeticCompletedTable")


def test_completed_html_card_header_has_no_count_badge():
    _assert_card_header_has_no_count_badge("completed.html")


def test_admin_assign_button_still_injected_into_filter_box_on_stage_html():
    # The admin-only bulk-Assign button still injects into DataTables' own
    # filter box (.dataTables_filter) inside initComplete, unaffected by the
    # count badge moving to initGlobalTable's own info slot.
    src = _read("stage.html")
    assert ".dataTables_filter" in src
    assert 'id="cosmeticAssignBtn"' in src
