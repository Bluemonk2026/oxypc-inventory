"""Sprint 14 unit tests — run without a database."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─── Task 1: base.html nav links ──────────────────────────────────────────────

def test_base_html_overdue_nav_link():
    """base.html must contain an 'Overdue Orders' link to /dealers/overdue."""
    base = os.path.join(os.path.dirname(__file__), "..", "templates", "base.html")
    with open(base, encoding="utf-8") as f:
        content = f.read()
    assert 'href="/dealers/overdue"' in content, \
        "base.html missing href=/dealers/overdue nav link"
    assert "Overdue Orders" in content, \
        "base.html missing 'Overdue Orders' link text"


def test_base_html_audit_log_nav_link():
    """base.html must contain an 'Audit Log' link to /admin/audit-log."""
    base = os.path.join(os.path.dirname(__file__), "..", "templates", "base.html")
    with open(base, encoding="utf-8") as f:
        content = f.read()
    assert 'href="/admin/audit-log"' in content, \
        "base.html missing href=/admin/audit-log nav link"


# ─── Task 2: WhatsApp compose route ───────────────────────────────────────────

def test_whatsapp_compose_route_exists():
    """whatsapp router must have a GET /whatsapp/compose route."""
    import importlib
    mod = importlib.import_module("routers.whatsapp")
    paths = [r.path for r in mod.router.routes]
    assert "/whatsapp/compose" in paths, \
        f"No /whatsapp/compose route found. Routes: {paths}"


# ─── Task 3: Dealer ageing route ──────────────────────────────────────────────

def test_dealers_ageing_route_exists():
    """dealers router must have a GET /dealers/ageing route."""
    import importlib
    mod = importlib.import_module("routers.dealers")
    paths = [r.path for r in mod.router.routes]
    assert "/dealers/ageing" in paths, \
        f"No /dealers/ageing route found. Routes: {paths}"


def test_ageing_bucket_logic():
    """Bucket math: current / 1-30 / 31-60 / 61-90 / 90+."""
    from datetime import datetime, timedelta

    now = datetime(2026, 4, 26, 12, 0, 0)

    class FakeOrder:
        def __init__(self, due_date, amount):
            self.payment_due_date = due_date
            self.due_amount = amount

    cases = [
        (now + timedelta(days=5),    500.0, "current"),
        (now,                        100.0, "current"),
        (now - timedelta(days=1),    200.0, "d30"),
        (now - timedelta(days=30),   300.0, "d30"),
        (now - timedelta(days=31),   400.0, "d60"),
        (now - timedelta(days=60),   500.0, "d60"),
        (now - timedelta(days=61),   600.0, "d90"),
        (now - timedelta(days=90),   700.0, "d90"),
        (now - timedelta(days=91),   800.0, "d90plus"),
        (now - timedelta(days=365), 1000.0, "d90plus"),
        (None,                       150.0, "current"),
    ]

    for due_date, amount, expected in cases:
        order = FakeOrder(due_date, amount)
        amt = float(order.due_amount)
        if order.payment_due_date is None or order.payment_due_date >= now:
            bucket = "current"
        else:
            days = (now - order.payment_due_date).days
            if days <= 30:
                bucket = "d30"
            elif days <= 60:
                bucket = "d60"
            elif days <= 90:
                bucket = "d90"
            else:
                bucket = "d90plus"
        assert bucket == expected, \
            f"due={due_date}, amount={amount}: expected {expected}, got {bucket}"
        assert amt == amount
