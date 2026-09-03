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


def test_devices_in_stress_test_card_header_has_the_failed_fqc_filter_on_the_right():
    # 2026-09-03: moved off DataTables' own .dataTables_filter box (where it
    # used to be JS-injected via initComplete) onto the right side of a new
    # "Devices in Stress Test" card header instead — server-rendered, same
    # relocation as L1/L2's filter bar.
    src = (pathlib.Path(ROOT) / "templates" / "qc" / "list.html").read_text(encoding="utf-8")
    assert ".dataTables_filter" not in src
    header_start = src.index('class="card-header bg-transparent d-flex')
    header_end = src.index('<div class="card-body p-0">')
    header_block = src[header_start:header_end]
    assert ">Devices in Stress Test</span>" in header_block
    assert 'id="qcFailedFqcFilter"' in header_block
