"""Ready to Sale Tags — Bulk Upload Tags modal (2026-08-31 fix):

templates/sales/ready_list.html's upload-success handler referenced an
undefined `noCheckbox` variable, which threw inside the `try` block on
EVERY successful upload — caught by the generic `catch`, which showed
"Upload failed." (even though the upload had actually succeeded) and, since
the throw happened before the `bootstrap.Modal...hide()` call, left the
modal open. Fixed by dropping the dead `list('Not selectable', noCheckbox)`
line so the success path (selection update, modal close, success alert)
runs to completion.
"""
from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def test_bulk_tag_modal_js_has_no_dangling_reference(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/sales/ready", follow_redirects=True).text
    assert 'id="bulkTagModal"' in html
    assert "noCheckbox" not in html
    # The modal-close call must be reachable on the success path.
    assert "bootstrap.Modal.getInstance(document.getElementById('bulkTagModal')).hide();" in html
