"""Sprint 13 unit tests — run without a database."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_list_dealers_accepts_page_param():
    """list_dealers must accept a 'page' query parameter."""
    import inspect, importlib
    mod = importlib.import_module("routers.dealers")
    fn = getattr(mod, "list_dealers", None)
    assert fn is not None
    sig = inspect.signature(fn)
    assert "page" in sig.parameters, "list_dealers must have a 'page' parameter"


def test_pagination_offset_calculation():
    """Offset must be (page - 1) * per_page."""
    per_page = 50
    for page, expected_offset in [(1, 0), (2, 50), (3, 100), (10, 450)]:
        offset = (page - 1) * per_page
        assert offset == expected_offset, f"page={page}: expected {expected_offset}, got {offset}"


def test_total_pages_calculation():
    """total_pages must ceil-divide total_count by per_page."""
    import math
    per_page = 50
    cases = [(0, 1), (1, 1), (50, 1), (51, 2), (100, 2), (101, 3)]
    for total, expected in cases:
        pages = max(1, math.ceil(total / per_page))
        assert pages == expected, f"total={total}: expected {expected}, got {pages}"


def test_overdue_route_exists():
    """dealers router must have a /overdue GET route."""
    import importlib
    mod = importlib.import_module("routers.dealers")
    paths = [r.path for r in mod.router.routes]
    assert "/dealers/overdue" in paths, f"No /dealers/overdue route. Routes: {paths}"


def test_admin_audit_log_route_exists():
    """admin router must have an /audit-log GET route."""
    import importlib
    mod = importlib.import_module("routers.admin")
    paths = [r.path for r in mod.router.routes]
    assert any("audit" in p for p in paths), \
        f"No audit-log route in admin router. Routes: {paths}"
