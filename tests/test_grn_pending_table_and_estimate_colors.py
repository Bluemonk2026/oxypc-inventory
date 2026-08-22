"""Two independent fixes bundled together because both are template/JS-only:

1. /grn/post-iqc's "GRN Pending for these Tag Numbers" table never showed a
   row: `window.dtPend =` sat on its own line directly above the real
   `var dtPend = $('#pendingTable').DataTable({...})` statement — invalid JS
   (assigning a `var` DECLARATION as a value), which aborted the whole
   <script> block before the DataTable, and so the AJAX call that actually
   fetches rows, ever ran. The table looked "empty" but was really just never
   initialized.
2. Part Estimate's Create Estimate matrix gives each Model column a light,
   name-hashed background color so a wide matrix is easier to scan.
"""
import re

import pytest

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def test_grn_pending_datatable_init_is_valid_js(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/grn/post-iqc", follow_redirects=True).text

    # The exact broken pattern must be gone: a bare `window.dtPend =` with
    # nothing after it on the same statement.
    assert not re.search(r"window\.dtPend\s*=\s*\n\s*var\s+dtPend", html), (
        "the invalid split assignment is back — DataTable init would be dead code again")
    # The fix: a single valid chained assignment feeding both names.
    assert "var dtPend = window.dtPend = $('#pendingTable').DataTable(" in html
    # And the later reload call this was broken for still has its target.
    assert "window.dtPend.ajax.reload(" in html


def test_create_estimate_matrix_colors_each_model_column(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/part-estimation", follow_redirects=True).text

    assert "function ceModelColor(" in html
    assert "ceModelColor(m.model)" in html
    # Applied at three call sites — header, field-row cells, and the
    # column-totals row — not just the header, or the columns would stop
    # being distinguishable once you scroll past the header row.
    js = html.split("function ceRenderTable(", 1)[1]
    assert js.count("ceModelColor(m.model)") == 3
