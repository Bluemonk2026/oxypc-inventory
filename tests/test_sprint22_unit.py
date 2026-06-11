# tests/test_sprint22_unit.py
"""Sprint 22 unit tests — dashboard batching, export limits, stock_in pagination, role checks."""
from pathlib import Path

_ROOT = Path(__file__).parent.parent


# ── TASK 2: PERF-3 Dashboard query batching ───────────────────────────────────

def test_dashboard_no_direct_count_queries_for_stages():
    """routers/dashboard.py must not call _count() for stage-based counts — use stage_counts dict."""
    src = (_ROOT / "routers" / "dashboard.py").read_text(encoding="utf-8")
    count = src.count("await _count(")
    assert count == 0, (
        f"dashboard.py has {count} await _count() call(s). "
        "Replace with stage_counts.get(DeviceStage.X.value, 0) lookups."
    )


def test_dashboard_stage_counts_dict_lookup_used():
    """routers/dashboard.py must use stage_counts.get(DeviceStage...) for user_queue counts."""
    src = (_ROOT / "routers" / "dashboard.py").read_text(encoding="utf-8")
    assert "stage_counts.get(DeviceStage." in src, (
        "dashboard.py missing stage_counts.get(DeviceStage.X.value, 0) pattern — "
        "add it to replace _count() calls in user_queue block."
    )


# ── TASK 3: PERF-4 Report export row limits ───────────────────────────────────

def test_reports_has_max_export_rows_constant():
    """routers/reports.py must define MAX_EXPORT_ROWS module-level constant."""
    src = (_ROOT / "routers" / "reports.py").read_text(encoding="utf-8")
    assert "MAX_EXPORT_ROWS" in src, (
        "reports.py missing MAX_EXPORT_ROWS constant. "
        "Add: MAX_EXPORT_ROWS = 5_000 after imports."
    )


def test_reports_export_functions_apply_row_limit():
    """routers/reports.py export routes must apply .limit(MAX_EXPORT_ROWS) to prevent OOM."""
    src = (_ROOT / "routers" / "reports.py").read_text(encoding="utf-8")
    count = src.count(".limit(MAX_EXPORT_ROWS)")
    assert count >= 3, (
        f"reports.py has .limit(MAX_EXPORT_ROWS) {count} time(s) — need at least 3 "
        "(export_lot_pl, export_sales, overdue_csv)."
    )


# ── TASK 3: SEC-1 receivables inline role check ───────────────────────────────

def test_reports_receivables_no_inline_role_check():
    """reports.py receivables_report must not use inline role check — use require_roles() dependency."""
    src = (_ROOT / "routers" / "reports.py").read_text(encoding="utf-8")
    assert "if current_user.role not in ALLOWED" not in src, (
        "reports.py receivables_report has inline role check. "
        "Replace with a require_roles() Depends on the route signature."
    )


# ── TASK 4: stock_in_list pagination ─────────────────────────────────────────

def test_stock_in_list_has_page_param():
    """routers/stock.py stock_in_list must accept `page` as a Query param."""
    src = (_ROOT / "routers" / "stock.py").read_text(encoding="utf-8")
    count = src.count("page: int = Query")
    assert count >= 2, (
        f"stock.py has page: int = Query {count} time(s) — need at least 2 "
        "(list_lots already has one; stock_in_list needs one too)."
    )


def test_stock_in_list_has_page_size_param():
    """routers/stock.py stock_in_list must accept `page_size` as a Query param."""
    src = (_ROOT / "routers" / "stock.py").read_text(encoding="utf-8")
    count = src.count("page_size: int = Query")
    assert count >= 2, (
        f"stock.py has page_size: int = Query {count} time(s) — need at least 2 "
        "(list_lots already has one; stock_in_list needs one too)."
    )


def test_stock_in_list_passes_total_pages():
    """routers/stock.py stock_in_list must pass total_pages to template context."""
    src = (_ROOT / "routers" / "stock.py").read_text(encoding="utf-8")
    count = src.count("total_pages")
    assert count >= 2, (
        f"stock.py has 'total_pages' {count} time(s) — need at least 2 "
        "(list_lots already has one; stock_in_list needs one too)."
    )


def test_stock_in_template_uses_server_paging():
    """templates/lots/stock_in.html must disable DataTables client paging (conflicts with server paging)."""
    src = (_ROOT / "templates" / "lots" / "stock_in.html").read_text(encoding="utf-8")
    assert "pageLength:25" not in src, (
        "stock_in.html DataTables still uses pageLength:25 — change to {paging:false}."
    )


# ── TASK 5: SEC-1 dealers.py role checks ─────────────────────────────────────

def test_dealers_no_bare_get_current_user_in_routes():
    """dealers.py route signatures must not use Depends(get_current_user) — use require_sales."""
    src = (_ROOT / "routers" / "dealers.py").read_text(encoding="utf-8")
    count = src.count("Depends(get_current_user)")
    assert count == 0, (
        f"dealers.py has {count} route(s) using bare Depends(get_current_user). "
        "Replace with Depends(require_sales) or Depends(require_sales_mgr)."
    )


# ── TASK 5: SEC-1 admin.py role check ────────────────────────────────────────

def test_admin_audit_log_no_inline_role_check():
    """admin.py audit_log_view must use require_admin dependency, not inline role check."""
    src = (_ROOT / "routers" / "admin.py").read_text(encoding="utf-8")
    assert "if current_user.role != UserRole.admin:" not in src, (
        "admin.py has inline 'if current_user.role != UserRole.admin:' check. "
        "Replace Depends(get_current_user) with Depends(require_admin) in audit_log_view."
    )


def test_admin_no_bare_get_current_user_in_routes():
    """admin.py route signatures must not use Depends(get_current_user) — use require_admin."""
    src = (_ROOT / "routers" / "admin.py").read_text(encoding="utf-8")
    count = src.count("Depends(get_current_user)")
    assert count == 0, (
        f"admin.py has {count} route(s) using bare Depends(get_current_user). "
        "Replace with Depends(require_admin)."
    )
