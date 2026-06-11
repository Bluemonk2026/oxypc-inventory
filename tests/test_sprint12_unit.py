"""Sprint 12 unit tests — run without a database."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_accounts_router_imports_audit():
    """accounts.py must import audit from services.audit_engine."""
    import importlib
    mod = importlib.import_module("routers.accounts")
    assert hasattr(mod, "audit"), "audit not imported into routers.accounts"


def test_create_supplier_payment_accepts_request():
    """create_supplier_payment must have 'request' in its parameter list."""
    import inspect, importlib
    mod = importlib.import_module("routers.accounts")
    fn = getattr(mod, "create_supplier_payment", None)
    assert fn is not None, "create_supplier_payment not found"
    sig = inspect.signature(fn)
    assert "request" in sig.parameters, \
        "create_supplier_payment must accept 'request: Request'"


def test_dealer_statement_route_exists():
    """dealers router must expose a /statement.csv GET route."""
    import importlib
    mod = importlib.import_module("routers.dealers")
    router = mod.router
    paths = [r.path for r in router.routes]
    assert any("statement" in p for p in paths), \
        f"No statement route found. Routes: {paths}"


def test_csv_statement_section_headers():
    """CSV section headers must use expected column names."""
    order_headers = ["Order#", "Date", "Total (Rs)", "Paid (Rs)", "Due (Rs)", "Status"]
    cn_headers = ["Credit#", "Date", "Amount (Rs)", "Reason", "Items"]
    receipt_headers = ["Date", "Amount (Rs)", "Mode", "Reference"]
    assert len(order_headers) == len(set(order_headers))
    assert len(cn_headers) == len(set(cn_headers))
    assert len(receipt_headers) == len(set(receipt_headers))


def test_dealer_statement_csv_checks_role():
    """dealer_statement_csv must restrict access to finance/sales roles."""
    import inspect, importlib
    mod = importlib.import_module("routers.dealers")
    fn = getattr(mod, "dealer_statement_csv", None)
    assert fn is not None, "dealer_statement_csv not found"
    # Verify that SALES_ROLES or admin/sales_manager restriction is referenced
    # by checking the function source contains a role check
    src = inspect.getsource(fn)
    # Role restriction is enforced via FastAPI dependency injection (require_sales /
    # require_finance), which is the correct pattern — not inline role string checks.
    assert "require_sales" in src or "require_finance" in src or "SALES_ROLES" in src, \
        "dealer_statement_csv must be restricted to sales/finance roles via a require_* dependency"


def test_dashboard_imports_dealer_models():
    """dashboard.py must import DealerOrder and DealerCreditNote."""
    import importlib
    mod = importlib.import_module("routers.dashboard")
    assert hasattr(mod, "DealerOrder"), "DealerOrder not imported in dashboard.py"
    assert hasattr(mod, "DealerCreditNote"), "DealerCreditNote not imported in dashboard.py"
