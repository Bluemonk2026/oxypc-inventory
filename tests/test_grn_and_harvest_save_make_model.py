"""Add Harvest Part modal and Part GRN's Add New Part page both collect
Part Brand (Make) / Part Model, but neither ever carried those two fields
onto the SparePart row it creates — routers/parts_grn.py's SparePart mirror
in both harvest_part() and grn_create() only ever set part_code/name/
category/price/qty/etc, never make=/model=. So a part added either way
always showed a blank Make/Model on Part Master, even though the form asked
for it and a PartsGRNLineItem row recorded it faithfully."""
import json

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def test_harvest_part_saves_make_and_model(app_client, make_user):  # noqa: F811
    username, password = make_user("spare_parts_manager")
    _login(app_client, username, password)
    csrf = app_client.cookies.get("csrf_token") or ""

    r = app_client.post("/parts-grn/harvest", data={
        "csrf_token": csrf,
        "part_name": "ITestHarvestRAM",
        "part_brand": "Dell",
        "part_model": "Latitude 5490",
        "category": "RAM",
        "physical_qty": "2",
        "price": "500",
        "min_stock_alert": "1",
    })
    assert r.status_code == 200, r.text[:500]
    part_id = r.json()["part_id"]

    html = app_client.get("/spare-parts", follow_redirects=True).text
    row = html.split(part_id, 1)[1].split("</tr>", 1)[0]
    assert "Dell" in row, f"Make not saved, row: {row[:600]}"
    assert "Latitude 5490" in row, f"Model not saved, row: {row[:600]}"


def test_grn_new_part_saves_make_and_model(app_client, make_user):  # noqa: F811
    username, password = make_user("spare_parts_manager")
    _login(app_client, username, password)
    csrf = app_client.cookies.get("csrf_token") or ""

    line_items = [{
        "part_id": "",
        "lot_number": "LOT1",
        "part_name": "ITestGRNKeyboard",
        "part_brand": "Lenovo",
        "part_model": "ThinkPad T14",
        "category": "Keyboard",
        "invoice_qty": "3",
        "physical_qty": "3",
        "price": "750",
        "min_stock_alert": "1",
    }]
    r = app_client.post("/parts-grn/new", data={
        "csrf_token": csrf,
        "vendor_name": "Test Vendor",
        "line_items_json": json.dumps(line_items),
    }, follow_redirects=False)
    assert r.status_code in (302, 303), r.text[:800]

    html = app_client.get("/spare-parts", follow_redirects=True).text
    row = html.split("ITestGRNKeyboard", 1)[1].split("</tr>", 1)[0]
    assert "Lenovo" in row, f"Make not saved, row: {row[:600]}"
    assert "ThinkPad T14" in row, f"Model not saved, row: {row[:600]}"
