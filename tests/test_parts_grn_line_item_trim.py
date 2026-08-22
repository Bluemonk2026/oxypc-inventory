"""Spare Part GRN — Add Line Item modal and the Line Item table both drop
Main Category / Invoice Ref / Item Name, and Part Category now leads Part
Name in the modal.
"""
from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def test_add_line_item_modal_and_table_trimmed(app_client, make_user):  # noqa: F811
    username, password = make_user("spare_parts_manager")
    _login(app_client, username, password)
    html = app_client.get("/parts-grn/new", follow_redirects=True).text

    modal = html.split('id="addItemModal"', 1)[1].split("</script>", 1)[0]
    assert 'id="li_main_category"' not in modal
    assert 'id="li_invoice_ref"' not in modal
    assert 'id="li_item_name"' not in modal
    assert modal.index('id="li_category"') < modal.index('id="li_part_name"')

    table = html.split('id="lineItemsTable"', 1)[1].split("</table>", 1)[0]
    assert "Main Cat" not in table
    assert "Invoice Ref" not in table
