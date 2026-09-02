"""Table row count next to DataTables' "Show N entries" dropdown on the
cosmetic pages (Cleaning, Putty, Dry Sanding, Masking, Painting, Water
Sanding, Cosmetic Completed, All Tags) — a warning badge injected into
.dataTables_length, updated on every draw so it tracks whatever filter
(DataTables' own search box, sorting, paging) is applied. Same pattern as
the L1/L2 page's count badge (templates/repair/l1.html).

Cosmetic Received (2026-09-02) moved to the Global Table module instead
(static/js/global-table.js) — its count badge is now DataTables' own info
slot, re-skinned via language.info, rather than a hand-appended <span>. See
test_received_html_uses_global_table below.
"""
import pathlib

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def test_count_badge_wired_into_dataTables_length_on_all_four_templates():
    for name, table_id in (
        ("stage.html", "cosmeticTable"),
        ("completed.html", "cosmeticCompletedTable"),
        ("all_tags.html", "cosmeticAllTagsTable"),
    ):
        src = open(pathlib.Path(ROOT) / "templates" / "cosmetic" / name, encoding="utf-8").read()
        assert 'id="cosmeticCountBadge" class="badge bg-warning text-dark' in src, name
        assert ".dataTables_length" in src, name
        assert "drawCallback: function() { updateCosmeticCountBadge(this.api()); }" in src, name
        assert f"$('#{table_id}').DataTable(" in src, name


def test_received_html_uses_global_table():
    src = open(pathlib.Path(ROOT) / "templates" / "cosmetic" / "received.html", encoding="utf-8").read()
    assert "initGlobalTable('#cosmeticReceivedTable'" in src
    assert 'id="cosmeticCountBadge"' not in src  # replaced by the module's own badge
    # Admin-only Assign button + the Failed-from-Final-QC filter still prepend
    # into .dataTables_filter, same as before the migration.
    assert ".dataTables_filter" in src
    assert 'id="cosmeticRecvAssignBtn"' in src
    assert 'id="cosmeticRecvFailedFqcFilter"' in src


def test_received_html_card_header_has_no_count_badge():
    """Global Table convention: the card-header shows icon + title on the
    left and this table's own action buttons on the right if it has any —
    never a plain count badge (the table-top toolbar's own row-count badge
    already covers that). Cosmetic Received has no page-level buttons of its
    own (Assign is admin-only and lives in the table-top toolbar instead),
    so its card-header's right side is empty."""
    src = open(pathlib.Path(ROOT) / "templates" / "cosmetic" / "received.html", encoding="utf-8").read()
    header_start = src.index('class="card-header bg-transparent')
    header_end = src.index('<div class="card-body p-0">')
    header_block = src[header_start:header_end]
    assert "Devices in {{ stage_label }}" in header_block
    assert "badge" not in header_block
    assert "device(s)" not in header_block


def test_admin_assign_button_still_injected_alongside_count_badge_on_stage_html():
    # The count-badge addition to stage.html shares initComplete with the
    # existing admin-only bulk-Assign button injection (into a DIFFERENT
    # DataTables control, .dataTables_filter) — confirm neither was dropped.
    src = open(pathlib.Path(ROOT) / "templates" / "cosmetic" / "stage.html", encoding="utf-8").read()
    assert ".dataTables_filter" in src
    assert 'id="cosmeticAssignBtn"' in src
