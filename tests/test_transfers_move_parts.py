"""Stock Transfers — Move Parts tab and the list-table column swap.

Move Parts is device-less (a spare-parts stock move, not a specific unit),
which is why stock_transfers.device_id had to become nullable. Part Name is
stored in `model` (the cell the list table already prints as "Make / Model")
and quantity in the new dedicated column.
"""
import re

import pytest

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def _assignable_user_id(html):
    parts_select = html.split('id="parts-assign-user"', 1)[1].split("</select>", 1)[0]
    m = re.search(r'value="([0-9a-f-]{36})"', parts_select)
    assert m, "no employee option found in the Move Parts Assign To Employee dropdown"
    return m.group(1)


def test_transfers_list_hides_hdd_ram_cpu_and_shows_quantity(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/transfers", follow_redirects=True).text
    assert "<th>Quantity</th>" in html
    assert "<th>HDD</th>" not in html
    assert "<th>RAM</th>" not in html
    assert "<th>CPU</th>" not in html


def test_move_parts_tab_present_with_part_name_and_quantity(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/transfers/new", follow_redirects=True).text
    assert 'id="movePartsTab"' in html
    assert 'action="/transfers/new/parts"' in html
    tab = html.split('id="movePartsTab"', 1)[1].split("</form>", 1)[0]
    assert 'name="part_name"' in tab
    assert 'name="quantity"' in tab
    assert 'name="transfer_type"' in tab
    assert 'name="assigned_user_id"' in tab
    assert 'name="notes"' in tab


def test_move_parts_creates_a_device_less_transfer_row(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    form_html = app_client.get("/transfers/new", follow_redirects=True).text
    user_id = _assignable_user_id(form_html)
    csrf = app_client.cookies.get("csrf_token")

    r = app_client.post("/transfers/new/parts", data={
        "csrf_token": csrf,
        "part_name": "Test Keyboard XYZ",
        "quantity": "7",
        "transfer_type": "trc_to_showroom",
        "assigned_user_id": user_id,
        "notes": "test move",
    }, follow_redirects=False)
    assert r.status_code == 302, r.text[:500]
    assert "error" not in (r.headers.get("location") or "")

    listing = app_client.get("/transfers", follow_redirects=True).text
    assert "Test Keyboard XYZ" in listing
    row = listing.split("Test Keyboard XYZ", 1)[1].split("</tr>", 1)[0]
    assert ">7<" in row, "quantity column should show 7"
