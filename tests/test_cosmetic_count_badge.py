"""Table row count next to DataTables' "Show N entries" dropdown on all 8
cosmetic pages (Cosmetic Received, Cleaning, Putty, Dry Sanding, Masking,
Painting, Water Sanding, Cosmetic Completed) — a warning badge injected into
.dataTables_length, updated on every draw so it tracks whatever filter
(DataTables' own search box, sorting, paging) is applied. Same pattern as
the L1/L2 page's count badge (templates/repair/l1.html).
"""
import pathlib

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def test_count_badge_wired_into_dataTables_length_on_all_four_templates():
    for name, table_id in (
        ("received.html", "cosmeticReceivedTable"),
        ("stage.html", "cosmeticTable"),
        ("completed.html", "cosmeticCompletedTable"),
        ("all_tags.html", "cosmeticAllTagsTable"),
    ):
        src = open(pathlib.Path(ROOT) / "templates" / "cosmetic" / name, encoding="utf-8").read()
        assert 'id="cosmeticCountBadge" class="badge bg-warning text-dark' in src, name
        assert ".dataTables_length" in src, name
        assert "drawCallback: function() { updateCosmeticCountBadge(this.api()); }" in src, name
        assert f"$('#{table_id}').DataTable(" in src, name


def test_admin_assign_button_still_injected_alongside_count_badge_on_stage_html():
    # The count-badge addition to stage.html shares initComplete with the
    # existing admin-only bulk-Assign button injection (into a DIFFERENT
    # DataTables control, .dataTables_filter) — confirm neither was dropped.
    src = open(pathlib.Path(ROOT) / "templates" / "cosmetic" / "stage.html", encoding="utf-8").read()
    assert ".dataTables_filter" in src
    assert 'id="cosmeticAssignBtn"' in src
