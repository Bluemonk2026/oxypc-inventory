"""Regression: the 2026-09-02 batch that moved Tag Number before WorkID on
Cosmetic Received, the shared Cleaning/Putty/Dry Sanding/Masking/Painting/
Water Sanding template, and Cosmetic Completed left each page's default
DataTables sort column pointing at the OLD position — silently changing the
default sort from Tag Number ascending to WorkID ascending on Cosmetic
Received and Cosmetic Completed (already live in production as commit
5952964 before this fix). The shared stage.html template's own default sort
column ("Since", far to the right of the swapped pair) was unaffected.

Found and fixed while wiring stage.html/completed.html onto initGlobalTable
in the same batch as this test.
"""
import pathlib

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _read(name):
    return open(pathlib.Path(ROOT) / "templates" / "cosmetic" / name, encoding="utf-8").read()


def test_received_html_default_sort_points_at_tag_number_not_workid():
    src = _read("received.html")
    # Tag Number is column 1 with the admin-only checkbox column present, 0
    # without it — WorkID (the old position this used to point at) is one
    # column further right in both cases.
    assert "var orderCol = ADMIN ? 1 : 0;" in src


def test_completed_html_default_sort_points_at_tag_number_not_workid():
    src = _read("completed.html")
    # No checkbox column on this page — Tag Number is column 0.
    assert "order: [[0, 'asc']]" in src


def test_stage_html_default_sort_still_points_at_since_unaffected_by_the_swap():
    src = _read("stage.html")
    assert "var sinceCol = ADMIN ? 9 : 8;" in src


def test_workid_status_table_has_tag_number_before_workid():
    src = open(pathlib.Path(ROOT) / "templates" / "workid_status" / "list.html", encoding="utf-8").read()
    assert "<th>Tag Number</th><th>WorkID</th>" in src
    # The <tr> tag itself references it.work_id earlier (in its
    # class="...highlight..." attribute), so anchor on the WorkID <td>'s own
    # opening tag rather than the bare "it.work_id" substring.
    tag_td_idx = src.index('href="/devices/{{ it.barcode }}"')
    workid_td_idx = src.index('<td class="font-monospace fw-bold">')
    assert tag_td_idx < workid_td_idx
