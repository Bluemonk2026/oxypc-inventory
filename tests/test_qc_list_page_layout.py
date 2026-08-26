"""Stress Test page layout refinements:
 - "QC a Device" button and the top "N device(s) awaiting QC" line removed.
 - That count now lives next to DataTables' native "Show entries" control,
   and tracks the FILTERED row count (recordsDisplay), not the page total.
 - "All Pass" checkbox sits to the right of the device label.
 - Unchecking "All Pass" unchecks every item's Pass box (not a no-op).
 - Unchecking any single item's Pass box (directly, or via checking that
   item's Fail box) unchecks "All Pass".
 - Only one of Pass/Fail can be checked per line item at a time.
"""
from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def test_qc_device_button_and_top_count_removed(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/qc", follow_redirects=True).text

    assert "QC a Device" not in html
    assert "/qc/new" not in html
    assert "device(s) awaiting QC</span>" not in html  # the old top-bar span


def test_awaiting_count_wired_to_length_control_and_filtered_count(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/qc", follow_redirects=True).text

    assert "dataTables_length" in html
    assert "qcAwaitingCount" in html
    assert "recordsDisplay" in html  # filtered count, not the unfiltered total
    assert "drawCallback" in html  # updates on every filter/search/page change


def test_all_pass_checkbox_is_beside_device_label(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/qc", follow_redirects=True).text

    block = html.split('id="stressActiveArea"', 1)[1].split('id="stressChecklist"', 1)[0]
    # Both live in order (label, then All Pass) inside one flex row that
    # spaces them apart left/right, not stacked on separate lines.
    wrapper_pos = block.index("d-flex align-items-center justify-content-between")
    label_pos = block.index('id="stressDeviceLabel"')
    allpass_pos = block.index('id="allPassCheck"')
    assert wrapper_pos < label_pos < allpass_pos


def test_unchecking_all_pass_unchecks_every_pass_box(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/qc", follow_redirects=True).text

    fn = html.split("function toggleAllPass(checked) {", 1)[1].split("\n}", 1)[0]
    assert "pass.checked = false;" in fn
    # The old short-circuit that made unchecking "All Pass" a no-op must be gone.
    assert "if (!checked) return" not in fn


def test_unchecking_a_pass_box_unchecks_all_pass(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/qc", follow_redirects=True).text

    fn = html.split("function onCheckChanged(slug, which) {", 1)[1].split("\n}", 1)[0]
    assert "if (!pass.checked) document.getElementById('allPassCheck').checked = false;" in fn


def test_pass_and_fail_are_mutually_exclusive_per_item(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/qc", follow_redirects=True).text

    fn = html.split("function onCheckChanged(slug, which) {", 1)[1].split("\n}", 1)[0]
    assert "if (which === 'pass' && pass.checked) fail.checked = false;" in fn
    assert "if (which === 'fail' && fail.checked) pass.checked = false;" in fn
