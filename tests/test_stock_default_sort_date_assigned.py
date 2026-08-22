"""Inventory Manager's Inventory Stock table defaults to Date Assigned (most
recent first) instead of Tag Number — that date is the same
StockTransfer.transfer_date the Assigned User badge is already derived from,
via a correlated subquery, not a stand-in like Device.updated_at."""
import pytest

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def test_stock_table_default_order_is_date_assigned_desc(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/stock", follow_redirects=True).text
    assert "order: [[9, 'desc']]" in html


def test_stock_data_endpoint_sorts_by_date_assigned_without_error(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    r = app_client.get(
        "/stock/data",
        params={"draw": 1, "start": 0, "length": 12,
                "order[0][column]": 9, "order[0][dir]": "desc"},
    )
    assert r.status_code == 200, r.text[:1000]
    body = r.json()
    assert "data" in body and "recordsTotal" in body
