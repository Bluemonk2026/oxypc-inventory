"""
Week 2 Recovery — unit tests for pure-Python functions.
Run: python tests/test_week2_unit.py
All tests use assert statements; no DB or server required.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_mock_dealer(outstanding_amount=0, last_sale_date=None, preferred_categories=None):
    """Create a minimal dealer-like object for unit testing."""
    class MockDealer:
        pass
    d = MockDealer()
    d.outstanding_amount = outstanding_amount
    d.last_sale_date = last_sale_date
    d.preferred_categories = preferred_categories
    return d


def test_upsell_suggestions_with_outstanding_live():
    """_upsell_suggestions must accept outstanding_live keyword arg."""
    from routers.dealers import _upsell_suggestions
    dealer = make_mock_dealer()
    result = _upsell_suggestions(dealer, outstanding_live=5000.0)
    assert isinstance(result, list), "must return a list"
    assert any("5,000" in s for s in result), f"expected outstanding hint, got: {result}"


def test_upsell_suggestions_zero_outstanding():
    """With outstanding_live=0, no outstanding hint should appear."""
    from routers.dealers import _upsell_suggestions
    dealer = make_mock_dealer()
    result = _upsell_suggestions(dealer, outstanding_live=0.0)
    assert not any("Outstanding" in s for s in result), f"unexpected hint: {result}"


def test_upsell_suggestions_default_zero():
    """outstanding_live should default to 0 (backward-compatible)."""
    from routers.dealers import _upsell_suggestions
    dealer = make_mock_dealer()
    result = _upsell_suggestions(dealer)
    assert isinstance(result, list)


def test_audit_engine_importable():
    """audit_engine must be importable (smoke check)."""
    from services.audit_engine import audit
    import inspect
    sig = inspect.signature(audit)
    assert "action" in sig.parameters, "audit() must accept 'action' parameter"
    assert "db" in sig.parameters, "audit() must accept 'db' parameter"


def test_health_router_importable():
    """health router must exist and expose a FastAPI APIRouter with /health route."""
    from routers.health import router
    from fastapi import APIRouter
    assert isinstance(router, APIRouter), "health.router must be an APIRouter"
    routes = [r.path for r in router.routes]
    assert "/health" in routes, f"/health not in routes: {routes}"


if __name__ == "__main__":
    test_upsell_suggestions_with_outstanding_live()
    test_upsell_suggestions_zero_outstanding()
    test_upsell_suggestions_default_zero()
    test_audit_engine_importable()
    test_health_router_importable()
    print("All unit tests passed.")
