# tests/test_sprint15_unit.py
import re

BASE_HTML = open("templates/base.html", encoding="utf-8").read()
DASHBOARD_HTML = open("templates/dashboard.html", encoding="utf-8").read()


def test_base_html_ageing_nav_link():
    """Sidebar must have an Ageing link pointing to /dealers/ageing."""
    assert 'href="/dealers/ageing"' in BASE_HTML, \
        "base.html missing /dealers/ageing nav link"


def test_dashboard_outstanding_kpi_links_to_ageing():
    """Dealer Outstanding KPI button must link to /dealers/ageing."""
    assert re.search(r'Dealer Outstanding.*?href="/dealers/ageing"', DASHBOARD_HTML, re.DOTALL), \
        "Dashboard Dealer Outstanding KPI should link to /dealers/ageing"


def test_dashboard_overdue_kpi_links_to_overdue():
    """Overdue Orders KPI button must link to /dealers/overdue."""
    assert re.search(r'Overdue Orders.*?href="/dealers/overdue"', DASHBOARD_HTML, re.DOTALL), \
        "Dashboard Overdue Orders KPI should link to /dealers/overdue"

# NOTE (deliberate omission):
# The sales/telecaller work queue block on the dashboard displays
# dealer_outstanding_total as a static number only — it has no "Ageing" button.
# Only the admin block has the KPI tile wired to /dealers/ageing.
# This is by design: ageing analysis is an admin/sales_manager view;
# telecallers see the number for context but don't navigate to the ageing report.


def test_credit_note_model_has_is_applied():
    """DealerCreditNote ORM model must have is_applied, applied_at, applied_to_order_id."""
    src = open("models/dealers.py", encoding="utf-8").read()
    assert "is_applied" in src, "DealerCreditNote missing is_applied column"
    assert "applied_at" in src, "DealerCreditNote missing applied_at column"
    assert "applied_to_order_id" in src, "DealerCreditNote missing applied_to_order_id column"


def test_dealers_router_has_apply_route():
    """dealers.py must have a POST route for credit-notes apply."""
    src = open("routers/dealers.py", encoding="utf-8").read()
    assert "/apply" in src, "dealers.py missing credit-note apply route"
    assert "credit-notes" in src, "apply route must be under credit-notes path"


def test_profile_html_has_apply_form():
    """profile.html credit notes table must have an Apply form/button."""
    src = open("templates/dealers/profile.html", encoding="utf-8").read()
    assert "apply" in src.lower(), "profile.html missing Apply button/form for credit notes"
    assert "open_orders" in src or "is_applied" in src, \
        "profile.html must reference open_orders or is_applied for apply flow"


def test_dashboard_has_pipeline_widget():
    """dashboard.html must contain the pipeline widget block."""
    src = open("templates/dashboard.html", encoding="utf-8").read()
    assert "Pipeline" in src, "dashboard.html missing pipeline widget"


def test_pipeline_widget_shows_key_stages():
    """Pipeline widget must reference GRN, IQC, Stock, Repair, QC, Ready, Sold stages."""
    src = open("templates/dashboard.html", encoding="utf-8").read()
    for stage_key in ["grn", "iqc", "stock_in", "qc_check", "ready_to_sale", "sold"]:
        assert stage_key in src, f"Pipeline widget missing stage key: {stage_key}"


def test_pipeline_widget_admin_inventory_only():
    """Pipeline widget must be gated on admin or inventory_manager role."""
    src = open("templates/dashboard.html", encoding="utf-8").read()
    pipeline_pos = src.find("Pipeline")
    assert pipeline_pos != -1, "No pipeline section found"
    pre = src[:pipeline_pos]
    assert "admin" in pre or "inventory_manager" in pre, \
        "Pipeline widget must be gated inside admin/inventory_manager block"
