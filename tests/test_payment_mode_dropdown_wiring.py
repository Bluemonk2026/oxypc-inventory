"""New Tag Sale / New Part Sale — Payment Mode dropdown (2026-08-31):
now sourced from Master Data's Dropdown Configuration ("payment_mode"
category, same pattern the Customer State field on both pages already
uses), replacing the previously hardcoded Cash/UPI/Card/Credit options."""
from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def test_new_tag_sale_payment_mode_uses_master_data(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/sales/new", follow_redirects=True).text
    assert 'name="payment_mode"' in html
    # Seeded Master Data values (models/master.py MASTER_SEED["payment_mode"]).
    assert ">Cash<" in html
    assert "UPI" in html
    # The old hardcoded lowercase option values are gone.
    assert '<option value="cash">Cash</option>' not in html
    assert '<option value="upi">UPI</option>' not in html


def test_new_part_sale_payment_mode_uses_master_data():
    # /part-sales/new only renders the sale form (with the Payment Mode
    # field) once at least one part has an approved, unconsumed sale
    # request AND stock on hand — seeding that whole chain just to reach
    # this one field isn't worth it, so this checks the template source
    # directly, same as the New Tag Sale test checks the rendered page.
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "templates" / "parts" / "sale_new.html").read_text(encoding="utf-8")
    assert "master_options('payment_mode')" in src
    assert '<option value="cash">Cash</option>' not in src
    assert '<option value="upi">UPI</option>' not in src
