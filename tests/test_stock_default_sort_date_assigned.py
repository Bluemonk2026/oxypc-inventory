"""Inventory Manager's Inventory Stock table default order.

History: it used to default to "Date Assigned" (column 9, Assigned User). That
column was replaced by "Returned" (2026-10-12), so the table now starts
unsorted client-side (`order: []`) and the server falls back to flagged (urgent)
tags first, then most recently updated. Column 9 (Returned) is still sortable,
by the tag's latest customer-return date."""
import pytest

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def test_stock_table_has_no_default_client_sort(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/stock", follow_redirects=True).text
    assert "order: []" in html
    assert "order: [[9, 'desc']]" not in html


def test_stock_data_endpoint_sorts_by_returned_without_error(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    for direction in ("desc", "asc"):
        r = app_client.get(
            "/stock/data",
            params={"draw": 1, "start": 0, "length": 12,
                    "order[0][column]": 9, "order[0][dir]": direction},
        )
        assert r.status_code == 200, r.text[:1000]
        body = r.json()
        assert "data" in body and "recordsTotal" in body


def test_stock_data_endpoint_default_order_without_error(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    r = app_client.get("/stock/data", params={"draw": 1, "start": 0, "length": 12})
    assert r.status_code == 200, r.text[:1000]
