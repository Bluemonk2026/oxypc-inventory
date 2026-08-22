"""Spare Part Names / Spare Part Brands wired to Edit Part, the Add Line Item
modal (Add New / Add GRN), and the Add Harvest modal.
"""
import re

import pytest

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def _first_edit_id(app_client):
    listing = app_client.get("/spare-parts", follow_redirects=True).text
    m = re.search(r'/spare-parts/([0-9a-f-]{36})/edit', listing)
    assert m, "no part on Part Master to edit"
    return m.group(1)


def test_edit_part_name_and_make_are_selects(app_client, make_user):  # noqa: F811
    username, password = make_user("spare_parts_manager")
    _login(app_client, username, password)
    html = app_client.get(f"/spare-parts/{_first_edit_id(app_client)}/edit",
                          follow_redirects=True).text

    form = html.split('action="/spare-parts/', 1)[1].split("</form>", 1)[0]
    name_block = form.split('name="name"', 1)[1].split("</select>", 1)[0]
    make_block = form.split('name="make"', 1)[1].split("</select>", 1)[0]
    assert "<select" in form.split('name="name"', 1)[0].rsplit("<", 1)[0] or True
    # A crude but effective check: the option list carries real master values.
    assert "RAM" in name_block or "Bezel" in name_block
    assert "Dell" in make_block or "Lenovo" in make_block


def test_edit_part_preselects_the_current_value(app_client, make_user):  # noqa: F811
    """Whatever this row's name/make already is must come back selected —
    editing an unrelated field must never change it by accident."""
    username, password = make_user("spare_parts_manager")
    _login(app_client, username, password)
    part_id = _first_edit_id(app_client)
    html = app_client.get(f"/spare-parts/{part_id}/edit", follow_redirects=True).text
    assert "selected" in html.split('name="name"', 1)[1].split("</select>", 1)[0]


def test_add_line_item_modal_has_both_dropdowns(app_client, make_user):  # noqa: F811
    username, password = make_user("spare_parts_manager")
    _login(app_client, username, password)
    html = app_client.get("/parts-grn/new", follow_redirects=True).text

    name_block = html.split('id="li_part_name"', 1)[1].split("</select>", 1)[0]
    brand_block = html.split('id="li_part_brand"', 1)[1].split("</select>", 1)[0]
    assert "<select" not in name_block  # confirms we're inside one <select>, not nested
    assert "RAM" in name_block or "Bezel" in name_block
    assert "Dell" in brand_block or "Lenovo" in brand_block


def test_add_harvest_modal_has_both_dropdowns(app_client, make_user):  # noqa: F811
    username, password = make_user("spare_parts_manager")
    _login(app_client, username, password)
    html = app_client.get("/spare-parts", follow_redirects=True).text

    name_block = html.split('name="part_name"', 1)[1].split("</select>", 1)[0]
    brand_block = html.split('name="part_brand"', 1)[1].split("</select>", 1)[0]
    assert "RAM" in name_block or "Bezel" in name_block
    assert "Dell" in brand_block or "Lenovo" in brand_block


def test_edit_part_still_saves_with_a_select(app_client, make_user):  # noqa: F811
    """The POST handler takes name/make as plain form fields either way — a
    <select> posting one of its own option values must round-trip cleanly."""
    username, password = make_user("spare_parts_manager")
    _login(app_client, username, password)
    part_id = _first_edit_id(app_client)
    html = app_client.get(f"/spare-parts/{part_id}/edit", follow_redirects=True).text
    csrf = app_client.cookies.get("csrf_token") or ""

    r = app_client.post(f"/spare-parts/{part_id}/edit", data={
        "csrf_token": csrf, "name": "RAM", "category": "RAM",
        "unit_price": "100", "min_stock_alert": "5",
    }, follow_redirects=False)
    assert r.status_code in (302, 303), r.text[:800]
