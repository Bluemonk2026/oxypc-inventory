"""All Inventory's Tags Table silently failed to render for any role with
Pricing Visibility turned off (e.g. a "Production Manager" custom role):
DataTables was initialised with a hard-coded order column (14, "Updated")
that only exists when the 2 pricing columns are present, so a role missing
them got an order[0][column] pointing at a column that doesn't exist,
throwing inside DataTables' init and leaving #devicesTable stuck on
"Processing…" forever — even though /devices/data itself returned correct,
non-empty rows the whole time."""
import inspect

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def test_order_column_shifts_with_pricing_visibility(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/devices", follow_redirects=True).text

    assert "var UPDATED_COL = CAN_VIEW_PRICING ? 14 : 12;" in html
    assert "order: [[UPDATED_COL, 'desc']]" in html
    # The old hard-coded form must be gone, not just supplemented.
    assert "order: [[14, 'desc']]" not in html


def test_server_side_col_map_shifts_with_show_pricing():
    from routers import devices as dv

    src = inspect.getsource(dv.device_search_data)
    assert "updated_col = 14 if show_pricing else 12" in src
    assert "updated_col: Device.updated_at" in src
