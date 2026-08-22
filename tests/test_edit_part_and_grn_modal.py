"""Edit Part field layout and the Add GRN modal's field order.

Both are pure-template changes, so the risk is a Jinja error taking the page to
500 rather than a wrong value — hence a render assertion per page plus order
checks that would catch someone re-sorting the fields back.
"""
import pytest

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

EDIT_PART_FIELDS = ["part_lot", "category", "name", "make", "model",
                    "unit_price", "qty_in_stock", "min_stock_alert"]


def test_edit_part_page_has_all_nine_fields(app_client, make_user):  # noqa: F811
    username, password = make_user("spare_parts_manager")
    _login(app_client, username, password)

    listing = app_client.get("/spare-parts", follow_redirects=True).text
    assert "/edit" in listing, "no part to edit — fixture DB has an empty Part Master"
    import re
    m = re.search(r'/spare-parts/([0-9a-f-]{36})/edit', listing)
    assert m, "could not find an edit link on Part Master"

    html = app_client.get(f"/spare-parts/{m.group(1)}/edit", follow_redirects=True).text
    for field in EDIT_PART_FIELDS:
        assert f'name="{field}"' in html, f"{field} missing from Edit Part"
    for label in ("Part Lot", "Part Make", "Part Model"):
        assert label in html


def test_edit_part_rows_are_in_the_asked_order(app_client, make_user):  # noqa: F811
    username, password = make_user("spare_parts_manager")
    _login(app_client, username, password)
    import re
    listing = app_client.get("/spare-parts", follow_redirects=True).text
    m = re.search(r'/spare-parts/([0-9a-f-]{36})/edit', listing)
    html = app_client.get(f"/spare-parts/{m.group(1)}/edit", follow_redirects=True).text

    pos = [html.index(f'name="{f}"') for f in EDIT_PART_FIELDS]
    assert pos == sorted(pos), (
        "Edit Part fields are out of order; expected "
        "(Code, Lot, Category) (Name, Make, Model) (Price, Stock, Alert)")


def test_add_grn_modal_orders_vendor_then_invoice_after_eway(app_client, make_user):  # noqa: F811
    username, password = make_user("inventory_manager")
    _login(app_client, username, password)
    html = app_client.get("/grn/post-iqc", follow_redirects=True).text

    modal = html.split('id="addGrnModal"', 1)[1].split("</form>", 1)[0]
    assert modal.index('name="e_way_bill"') < modal.index('name="sender_name"')
    assert modal.index('name="sender_name"') < modal.index('name="invoice"')
    # A file input is inert without the multipart encoding.
    assert 'enctype="multipart/form-data"' in modal
    # Still no GRN Number / Lot Number — the number is generated, the lot mapped.
    assert "GRN Number" not in modal
    assert "Lot Number" not in modal
