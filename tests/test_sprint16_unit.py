# tests/test_sprint16_unit.py
import os


def test_dealers_router_has_invoice_route():
    """dealers.py must have a GET route for order invoice."""
    src = open("routers/dealers.py", encoding="utf-8").read()
    assert "/invoice" in src, "dealers.py missing order invoice route"


def test_order_invoice_template_exists():
    """order_invoice.html must exist in templates/dealers/."""
    assert os.path.exists("templates/dealers/order_invoice.html"), \
        "templates/dealers/order_invoice.html does not exist"


def test_order_invoice_template_has_key_fields():
    """Invoice template must show order number, dealer name, amounts, and print button."""
    src = open("templates/dealers/order_invoice.html", encoding="utf-8").read()
    for field in ["order_number", "total_amount", "paid_amount", "due_amount", "invoice_number"]:
        assert field in src, f"order_invoice.html missing field: {field}"
    assert "print" in src.lower(), "order_invoice.html missing print button/action"


def test_accounts_router_accepts_dealer_order_id():
    """accounts.py create_customer_receipt must accept dealer_order_id form param."""
    src = open("routers/accounts.py", encoding="utf-8").read()
    assert "dealer_order_id" in src, \
        "accounts.py create_customer_receipt missing dealer_order_id param"


def test_accounts_router_reconciles_dealer_order():
    """accounts.py must update DealerOrder when dealer_order_id is provided."""
    src = open("routers/accounts.py", encoding="utf-8").read()
    assert "DealerOrder" in src, "accounts.py must import/use DealerOrder for reconciliation"
    assert "due_amount" in src, "accounts.py must update due_amount on reconciliation"


def test_customer_receipts_template_has_order_field():
    """customer_receipts.html form must have a dealer_order_id field."""
    src = open("templates/accounts/customer_receipts.html", encoding="utf-8").read()
    assert "dealer_order_id" in src, \
        "customer_receipts.html missing dealer_order_id input field"


def test_reports_router_has_receivables_route():
    """reports.py must have a GET /receivables route."""
    src = open("routers/reports.py", encoding="utf-8").read()
    assert "receivables" in src, "reports.py missing receivables route"


def test_receivables_template_exists():
    """templates/reports/receivables.html must exist."""
    import os
    assert os.path.exists("templates/reports/receivables.html"), \
        "templates/reports/receivables.html does not exist"


def test_receivables_template_has_ageing_buckets():
    """Receivables template must show 4 ageing buckets."""
    src = open("templates/reports/receivables.html", encoding="utf-8").read()
    for label in ["0-30", "31-60", "61-90", "90+"]:
        assert label in src, f"receivables.html missing ageing bucket: {label}"
    assert "export" in src.lower() or "csv" in src.lower(), \
        "receivables.html missing CSV export option"
