"""Device Detail: floor roles (L1/L2, L3/L4, Stress = qc_inspector, Cosmetic,
Final QC = qc_inspector) see only the Parts Consumption section, full width,
with no Edit / Back to Inventory buttons. Every other role keeps the full
two-column page unchanged.
"""
import re
import pytest

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def _first_barcode(app_client):
    data = app_client.get("/devices/data?start=0&length=1", follow_redirects=True)
    RESERVED = {"data", "export", "barcodes", "api"}
    for cand in re.findall(r"/devices/([A-Za-z0-9_-]+)", data.text):
        if cand not in RESERVED:
            return cand
    return ""


@pytest.mark.parametrize("role", [
    "l1_engineer", "l2_engineer", "l3_engineer", "qc_inspector", "cosmetic_manager",
])
def test_floor_roles_see_parts_consumption_only(app_client, make_user, role):  # noqa: F811
    username, password = make_user(role)
    _login(app_client, username, password)
    barcode = _first_barcode(app_client)
    if not barcode:
        pytest.skip("no device in the fixture DB to open")

    html = app_client.get(f"/devices/{barcode}", follow_redirects=True).text
    assert "Parts Consumption" in html
    assert 'class="col-12"' in html, "Parts Consumption should render full width for floor roles"
    assert f"/devices/{barcode}/edit" not in html
    assert "Back to Inventory" not in html
    assert "Device P&amp;L Estimate" not in html and "Device P&L Estimate" not in html
    assert "Work ID History" not in html
    assert "Asset History" not in html


def test_admin_still_sees_the_full_two_column_page(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    barcode = _first_barcode(app_client)
    if not barcode:
        pytest.skip("no device in the fixture DB to open")

    html = app_client.get(f"/devices/{barcode}", follow_redirects=True).text
    assert "Parts Consumption" in html
    assert "Back to Inventory" in html
    assert f"/devices/{barcode}/edit" in html
    assert "Work ID History" in html
    assert "Asset History" in html
    assert 'class="col-lg-5"' in html
    assert 'class="col-lg-7"' in html
