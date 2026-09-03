"""Stress Test page (templates/qc/list.html) row count next to "Show N
entries". Originally a hand-appended warning-badge <span> (#qcAwaitingCount,
updated via drawCallback), same pattern as L1/L2 and the cosmetic pages —
moved onto the Global Table module instead (static/js/global-table.js,
2026-09-03): the badge is now DataTables' own info slot, re-skinned via
language.info, rather than a hand-appended <span>. Same migration already
done for Cosmetic Received/Stage/Completed/All Tags and WorkID Status.
"""
import pathlib

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def test_qc_table_uses_global_table_not_the_old_hand_built_badge():
    src = (pathlib.Path(ROOT) / "templates" / "qc" / "list.html").read_text(encoding="utf-8")
    assert "initGlobalTable('#qcTable'" in src
    assert 'id="qcAwaitingCount"' not in src
    assert "function updateAwaitingCount" not in src


def test_qc_table_has_no_table_responsive_wrapper():
    # initGlobalTable's own scrollX owns horizontal scrolling now — a nested
    # .table-responsive would risk a second, redundant scrollbar.
    src = (pathlib.Path(ROOT) / "templates" / "qc" / "list.html").read_text(encoding="utf-8")
    table_pos = src.index('id="qcTable"')
    preceding = src[:table_pos]
    assert '<div class="table-responsive">' not in preceding[-200:]


def test_failed_from_final_qc_filter_still_injected_into_filter_box():
    # Unaffected by the badge migration — same .dataTables_filter prepend.
    src = (pathlib.Path(ROOT) / "templates" / "qc" / "list.html").read_text(encoding="utf-8")
    assert ".dataTables_filter" in src
    assert 'id="qcFailedFqcFilter"' in src
