# Sprint 22 — Dashboard Perf + Report Limits + Role Checks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close 4 audit findings from `docs/audits/2026-04-29-claude-md-full-audit.md` — PERF-3 (dashboard fires 15+ sequential DB queries), PERF-4 (report CSV exports have no row cap), stock_in_list unbounded fetch, and SEC-1 (ad-hoc inline role checks in dealers.py and admin.py).

**Architecture:** All changes are surgical — no new models, no migrations, no template infrastructure changes. Dashboard batching replaces `await _count()` calls with dictionary lookups against the existing `stage_counts` GROUP BY result. Export limits add a module-level constant and `.limit()` to three CSV routes. Pagination on stock_in_list follows the identical pattern already in place for repair.py and qc.py. Role enforcement replaces `Depends(get_current_user)` with the existing `require_sales` / `require_admin` dependencies already imported in each file.

**Tech Stack:** FastAPI, SQLAlchemy async, Jinja2 templates, pytest source-inspection tests (no DB fixture needed — same pattern as test_sprint21_unit.py).

---

## File Map

| File | Action | Why |
|---|---|---|
| `tests/test_sprint22_unit.py` | **Create** | TDD — 14 source-inspection tests, all must fail before implementation |
| `routers/dashboard.py` | **Modify** | PERF-3: replace 8 `await _count()` stage-count calls with `stage_counts.get()` dict lookups |
| `routers/reports.py` | **Modify** | PERF-4: add `MAX_EXPORT_ROWS = 5_000` constant, `.limit()` on 3 export routes; SEC-1: inline role check in `receivables_report` → `require_roles()` dependency |
| `routers/stock.py` | **Modify** | stock_in_list: add `page`/`page_size` Query params + COUNT subquery + `.offset().limit()` |
| `templates/lots/stock_in.html` | **Modify** | Add pagination widget; change DataTables `pageLength:25` → `paging:false` |
| `routers/dealers.py` | **Modify** | SEC-1: 9 routes using `Depends(get_current_user)` → `Depends(require_sales)` |
| `routers/admin.py` | **Modify** | SEC-1: `audit_log_view` inline `if current_user.role !=` check → `Depends(require_admin)` |

---

## Background for the implementer

### Codebase patterns

**Test pattern** — All Sprint 21+ tests are pure source inspection (no DB):
```python
from pathlib import Path
_ROOT = Path(__file__).parent.parent

def test_something():
    src = (_ROOT / "routers" / "foo.py").read_text(encoding="utf-8")
    assert "some_string" in src, "clear failure message"
```
Run with: `cd C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory && venv\Scripts\python -m pytest tests\test_sprint22_unit.py -v`

**Pagination pattern** (already in `routers/repair.py`, `routers/qc.py`):
```python
@router.get("/something", response_class=HTMLResponse)
async def some_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    offset = (page - 1) * page_size
    base_stmt = select(Device).where(...)
    total_result = await db.execute(select(func.count()).select_from(base_stmt.subquery()))
    total = total_result.scalar() or 0
    total_pages = max(1, (total + page_size - 1) // page_size)
    result = await db.execute(base_stmt.order_by(...).offset(offset).limit(page_size))
    devices = result.scalars().all()
    return templates.TemplateResponse("...", {
        ..., "page": page, "page_size": page_size, "total": total, "total_pages": total_pages,
    })
```

**Pagination widget** (HTML — same block in all repair templates, copy verbatim):
```html
{% if total_pages and total_pages > 1 %}
<nav class="mt-3" aria-label="Device list pagination">
  <ul class="pagination pagination-sm justify-content-center mb-0">
    <li class="page-item {% if page <= 1 %}disabled{% endif %}">
      <a class="page-link" href="?page={{ page - 1 }}&page_size={{ page_size }}">‹ Prev</a>
    </li>
    {% for p in range(1, total_pages + 1) %}
      {% if p == page %}
        <li class="page-item active"><span class="page-link">{{ p }}</span></li>
      {% elif p == 1 or p == total_pages or (p >= page - 2 and p <= page + 2) %}
        <li class="page-item"><a class="page-link" href="?page={{ p }}&page_size={{ page_size }}">{{ p }}</a></li>
      {% elif p == page - 3 or p == page + 3 %}
        <li class="page-item disabled"><span class="page-link">…</span></li>
      {% endif %}
    {% endfor %}
    <li class="page-item {% if page >= total_pages %}disabled{% endif %}">
      <a class="page-link" href="?page={{ page + 1 }}&page_size={{ page_size }}">Next ›</a>
    </li>
  </ul>
  <p class="text-center text-muted small mt-1">{{ total }} device(s) in stage &bull; Page {{ page }} of {{ total_pages }}</p>
</nav>
{% endif %}
```

**Role enforcement helper** (already in `auth/dependencies.py`):
```python
def require_roles(*roles: UserRole):
    async def checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles and current_user.role != UserRole.admin:
            raise HTTPException(status_code=403, detail="Access denied")
        return current_user
    return checker
```
Admin is always granted access regardless of the roles listed. So `require_roles(UserRole.sales, UserRole.sales_manager, UserRole.telecaller)` allows admin too.

**`require_sales` already declared** in `routers/dealers.py` at line 24:
```python
SALES_ROLES = (UserRole.admin, UserRole.sales, UserRole.sales_manager, UserRole.telecaller)
require_sales = require_roles(*SALES_ROLES)
```

**`require_admin` already declared** in `routers/admin.py` at line 58:
```python
require_admin = require_roles(UserRole.admin)
```

**`stage_counts` dict** — computed at the top of `dashboard()` with a GROUP BY query:
```python
stage_counts = {
    row[0].value: row[1]          # e.g. {"iqc": 15, "l1": 23, "stock_in": 47, ...}
    for row in stage_result.fetchall()
    if row[0] is not None
}
for stage in DeviceStage:
    stage_counts.setdefault(stage.value, 0)   # ensures every key exists
```
Keys are enum `.value` strings: `"iqc"`, `"l1"`, `"l2"`, `"l3"`, `"qc_check"`, `"ready_to_sale"`, `"stock_in"`, `"sold"`, etc.

---

## Task 1: Write failing Sprint 22 tests

**Files:**
- Create: `tests/test_sprint22_unit.py`

- [ ] **Step 1: Write the test file**

Create `tests/test_sprint22_unit.py` with the following content exactly:

```python
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
```

- [ ] **Step 2: Run tests to verify all fail**

```bash
cd C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
venv\Scripts\python -m pytest tests\test_sprint22_unit.py -v
```

Expected: **14 FAILED** — none of the implementation exists yet.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests\test_sprint22_unit.py
git commit -m "test: Sprint 22 failing source-inspection tests (14 tests)"
```

---

## Task 2: PERF-3 — Dashboard query batching

**Files:**
- Modify: `routers/dashboard.py` — `dashboard()` function, user_queue block (lines ~95–213)

**Context:** The `dashboard()` function runs a GROUP BY query (lines 58–71) that populates `stage_counts` — a dict keyed by stage value strings (`"iqc"`, `"l1"`, `"l2"`, `"l3"`, `"qc_check"`, `"ready_to_sale"`, `"stock_in"`, `"sold"`, etc.). All keys are guaranteed to exist after the `setdefault` loop. The `_count()` helper at line 40 fires a fresh `SELECT COUNT(*)` per call. Eight `_count()` calls can be eliminated by reading from `stage_counts` instead.

- [ ] **Step 1: Write the failing tests (already done in Task 1)**

Confirm: `test_dashboard_no_direct_count_queries_for_stages` and `test_dashboard_stage_counts_dict_lookup_used` fail.

- [ ] **Step 2: Replace `_count()` calls with dict lookups in `routers/dashboard.py`**

Find the `user_queue` try block (starts at line ~98) and make the following replacements:

**Replace** the entire `if role == UserRole.iqc_inspector:` block:
```python
# OLD:
        if role == UserRole.iqc_inspector:
            user_queue["iqc_pending"] = await _count(db, Device.current_stage == DeviceStage.iqc)

# NEW:
        if role == UserRole.iqc_inspector:
            user_queue["iqc_pending"] = stage_counts.get(DeviceStage.iqc.value, 0)
```

**Replace** the `elif role == UserRole.l1_engineer:` block:
```python
# OLD:
        elif role == UserRole.l1_engineer:
            user_queue["l1_count"] = await _count(db, Device.current_stage == DeviceStage.l1)

# NEW:
        elif role == UserRole.l1_engineer:
            user_queue["l1_count"] = stage_counts.get(DeviceStage.l1.value, 0)
```

**Replace** the `elif role == UserRole.l2_engineer:` block:
```python
# OLD:
        elif role == UserRole.l2_engineer:
            user_queue["l2_count"] = await _count(db, Device.current_stage == DeviceStage.l2)

# NEW:
        elif role == UserRole.l2_engineer:
            user_queue["l2_count"] = stage_counts.get(DeviceStage.l2.value, 0)
```

**Replace** the `elif role == UserRole.l3_engineer:` block:
```python
# OLD:
        elif role == UserRole.l3_engineer:
            user_queue["l3_count"] = await _count(db, Device.current_stage == DeviceStage.l3)

# NEW:
        elif role == UserRole.l3_engineer:
            user_queue["l3_count"] = stage_counts.get(DeviceStage.l3.value, 0)
```

**Replace** the `elif role == UserRole.qc_inspector:` block:
```python
# OLD:
        elif role == UserRole.qc_inspector:
            user_queue["qc_pending"] = await _count(db, Device.current_stage == DeviceStage.qc_check)

# NEW:
        elif role == UserRole.qc_inspector:
            user_queue["qc_pending"] = stage_counts.get(DeviceStage.qc_check.value, 0)
```

**Replace** `ready_to_sale` count in the sales role block (line ~115):
```python
# OLD:
        elif role in (UserRole.sales, UserRole.sales_manager, UserRole.telecaller):
            user_queue["ready_to_sale"] = await _count(db, Device.current_stage == DeviceStage.ready_to_sale)

# NEW:
        elif role in (UserRole.sales, UserRole.sales_manager, UserRole.telecaller):
            user_queue["ready_to_sale"] = stage_counts.get(DeviceStage.ready_to_sale.value, 0)
```

**Replace** `stock_in_count` in the inventory_manager block (line ~161):
```python
# OLD:
        elif role == UserRole.inventory_manager:
            user_queue["stock_in_count"] = await _count(db, Device.current_stage == DeviceStage.stock_in)

# NEW:
        elif role == UserRole.inventory_manager:
            user_queue["stock_in_count"] = stage_counts.get(DeviceStage.stock_in.value, 0)
```

**Replace** the 6 `_count()` calls + `stock_in_count` in the admin block (lines ~166–186):
```python
# OLD (in admin block):
        elif role == UserRole.admin:
            user_queue["iqc_pending"] = await _count(db, Device.current_stage == DeviceStage.iqc)
            user_queue["l1_count"] = await _count(db, Device.current_stage == DeviceStage.l1)
            user_queue["l2_count"] = await _count(db, Device.current_stage == DeviceStage.l2)
            user_queue["l3_count"] = await _count(db, Device.current_stage == DeviceStage.l3)
            user_queue["qc_pending"] = await _count(db, Device.current_stage == DeviceStage.qc_check)
            user_queue["ready_to_sale"] = await _count(db, Device.current_stage == DeviceStage.ready_to_sale)
            ...
            user_queue["stock_in_count"] = await _count(db, Device.current_stage == DeviceStage.stock_in)

# NEW (in admin block):
        elif role == UserRole.admin:
            user_queue["iqc_pending"]   = stage_counts.get(DeviceStage.iqc.value, 0)
            user_queue["l1_count"]      = stage_counts.get(DeviceStage.l1.value, 0)
            user_queue["l2_count"]      = stage_counts.get(DeviceStage.l2.value, 0)
            user_queue["l3_count"]      = stage_counts.get(DeviceStage.l3.value, 0)
            user_queue["qc_pending"]    = stage_counts.get(DeviceStage.qc_check.value, 0)
            user_queue["ready_to_sale"] = stage_counts.get(DeviceStage.ready_to_sale.value, 0)
            ...
            user_queue["stock_in_count"] = stage_counts.get(DeviceStage.stock_in.value, 0)
```

Keep all non-stage queries in admin block unchanged (today_sales, month_revenue, low_stock_count, lot_count, dealer_outstanding, dealer_overdue, dealer_credit_notes).

- [ ] **Step 3: Run the 2 PERF-3 tests to verify they pass**

```bash
venv\Scripts\python -m pytest tests\test_sprint22_unit.py::test_dashboard_no_direct_count_queries_for_stages tests\test_sprint22_unit.py::test_dashboard_stage_counts_dict_lookup_used -v
```

Expected: **2 PASSED**

- [ ] **Step 4: Run all existing tests to confirm no regressions**

```bash
venv\Scripts\python -m pytest tests\test_sprint21_unit.py tests\test_sprint22_unit.py -v
```

Expected: Sprint 21 all PASSED, Sprint 22 = 2 PASSED + 12 FAILED (Tasks 3–5 not yet done).

- [ ] **Step 5: Commit**

```bash
git add routers\dashboard.py
git commit -m "perf: replace _count() stage queries with stage_counts dict lookups in dashboard (PERF-3)"
```

---

## Task 3: PERF-4 Report export limits + SEC-1 receivables role check

**Files:**
- Modify: `routers/reports.py` — add `MAX_EXPORT_ROWS`, apply to 3 export routes, fix `receivables_report`

**Context:** Three CSV export endpoints fetch unlimited rows: `export_lot_pl` (all lots), `export_sales` (all sales ever), `overdue_csv` (all overdue devices). At 5,000+ records these will OOM the process. Fix: add module-level constant `MAX_EXPORT_ROWS = 5_000` and apply `.limit(MAX_EXPORT_ROWS)` to each export query. Also add a `# TRUNCATED` warning row at end of CSV when the result hits the limit.

`receivables_report` currently uses `get_current_user` + inline role check. Fix: add a module-level dependency and use it in the route signature.

- [ ] **Step 1: Add `MAX_EXPORT_ROWS` constant after the imports in `routers/reports.py`**

Find the block just before `_REPORT_ROLES = require_roles(...)` (line ~20) and insert:

```python
# Maximum rows returned by any CSV export endpoint — prevents OOM on large datasets
MAX_EXPORT_ROWS = 5_000
```

The file should now have this near the top:
```python
from auth.dependencies import get_current_user, require_roles

# Maximum rows returned by any CSV export endpoint — prevents OOM on large datasets
MAX_EXPORT_ROWS = 5_000

# Financial reports — restricted to management/senior roles only
_REPORT_ROLES = require_roles(...)
```

- [ ] **Step 2: Apply `.limit(MAX_EXPORT_ROWS)` to `export_lot_pl` (line ~148)**

In `export_lot_pl`, the lot fetch is:
```python
# OLD:
    lots_result = await db.execute(select(Lot).order_by(Lot.created_at.desc()))
    lots = lots_result.scalars().all()

# NEW:
    lots_result = await db.execute(
        select(Lot).order_by(Lot.created_at.desc()).limit(MAX_EXPORT_ROWS)
    )
    lots = lots_result.scalars().all()
```

Also add a truncation warning row at the end of the writer loop (after the `for lot in lots:` block):
```python
    if len(lots) == MAX_EXPORT_ROWS:
        writer.writerow(["# TRUNCATED", f"Export capped at {MAX_EXPORT_ROWS} rows", "", "", "", "", "", "", "", "", ""])
```

- [ ] **Step 3: Apply `.limit(MAX_EXPORT_ROWS)` to `export_sales` (line ~190)**

In `export_sales`, the sales fetch is:
```python
# OLD:
    result = await db.execute(
        select(Sale, Device.barcode, Device.brand, Device.model, Lot.lot_number)
        .join(Device, Sale.device_id == Device.id)
        .join(Lot, Device.lot_id == Lot.id)
        .order_by(Sale.sold_at.desc())
    )
    sales = result.all()

# NEW:
    result = await db.execute(
        select(Sale, Device.barcode, Device.brand, Device.model, Lot.lot_number)
        .join(Device, Sale.device_id == Device.id)
        .join(Lot, Device.lot_id == Lot.id)
        .order_by(Sale.sold_at.desc())
        .limit(MAX_EXPORT_ROWS)
    )
    sales = result.all()
```

Add truncation warning after the writer loop:
```python
    if len(sales) == MAX_EXPORT_ROWS:
        writer.writerow(["# TRUNCATED", f"Export capped at {MAX_EXPORT_ROWS} rows", "", "", "", "", "", "", "", "", ""])
```

- [ ] **Step 4: Apply `.limit(MAX_EXPORT_ROWS)` to `overdue_csv` (line ~533)**

In `overdue_csv`, `stmt` is built and then executed. Change:
```python
# OLD:
    result = await db.execute(stmt)
    output = io.StringIO()

# NEW:
    result = await db.execute(stmt.limit(MAX_EXPORT_ROWS))
    rows_all = result.all()
    output = io.StringIO()
```

Then change the loop body from:
```python
    for device, lot_number in result.all():
```
to:
```python
    for device, lot_number in rows_all:
```

And add after the loop:
```python
    if len(rows_all) == MAX_EXPORT_ROWS:
        writer.writerow(["# TRUNCATED", f"Export capped at {MAX_EXPORT_ROWS} rows", "", "", "", "", ""])
```

- [ ] **Step 5: Fix `receivables_report` inline role check (SEC-1)**

Add a module-level dependency near the other `_REPORT_ROLES` declaration (add just after `_REPORT_ROLES`):
```python
_require_receivables = require_roles(
    UserRole.sales_manager,
    UserRole.inventory_manager,
)  # admin is always granted by require_roles() — matches the previous ALLOWED tuple
```

Then in `receivables_report` route signature, replace:
```python
# OLD:
@router.get("/receivables", response_class=HTMLResponse)
async def receivables_report(
    request: Request,
    export: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ...
    ALLOWED = (UserRole.admin, UserRole.sales_manager, UserRole.inventory_manager)
    if current_user.role not in ALLOWED:
        return RedirectResponse(url="/?error=Access+denied", status_code=302)

# NEW:
@router.get("/receivables", response_class=HTMLResponse)
async def receivables_report(
    request: Request,
    export: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_receivables),
):
    ...
    # (remove the ALLOWED / if current_user.role not in ALLOWED block entirely)
```

- [ ] **Step 6: Run the PERF-4 + SEC-1 reports tests**

```bash
venv\Scripts\python -m pytest tests\test_sprint22_unit.py::test_reports_has_max_export_rows_constant tests\test_sprint22_unit.py::test_reports_export_functions_apply_row_limit tests\test_sprint22_unit.py::test_reports_receivables_no_inline_role_check -v
```

Expected: **3 PASSED**

- [ ] **Step 7: Run the full Sprint 22 test suite**

```bash
venv\Scripts\python -m pytest tests\test_sprint22_unit.py -v
```

Expected: 5 PASSED, 9 FAILED (Tasks 4–5 not done yet).

- [ ] **Step 8: Commit**

```bash
git add routers\reports.py
git commit -m "perf: cap CSV export at 5000 rows; fix receivables role check (PERF-4, SEC-1)"
```

---

## Task 4: stock_in_list pagination

**Files:**
- Modify: `routers/stock.py` — `stock_in_list` function (currently at line ~382)
- Modify: `templates/lots/stock_in.html` — add pagination widget, fix DataTables

**Context:** `stock_in_list` (GET `/stock`) currently does an unbounded `.all()` — at 500 devices/day capacity, this will grow to thousands. The fix follows the identical pattern already in `list_lots` (same file) and `repair_list` / `qc_list`. The template uses `{% for device, lot_number in devices %}` — this tuple structure is preserved after the fix.

- [ ] **Step 1: Replace `stock_in_list` function in `routers/stock.py`**

Find the function starting at `@router.get("/stock", response_class=HTMLResponse)` and replace the entire function:

```python
# OLD:
@router.get("/stock", response_class=HTMLResponse)
async def stock_in_list(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(allowed)):
    result = await db.execute(
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.current_stage == DeviceStage.stock_in, Device.is_active == True)
        .order_by(Device.updated_at.desc())
    )
    devices = result.all()
    return templates.TemplateResponse("lots/stock_in.html", {
        "request": request, "devices": devices, "current_user": current_user
    })

# NEW:
@router.get("/stock", response_class=HTMLResponse)
async def stock_in_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    offset = (page - 1) * page_size

    base_stmt = (
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.current_stage == DeviceStage.stock_in, Device.is_active == True)
    )

    total_result = await db.execute(
        select(func.count()).select_from(base_stmt.subquery())
    )
    total = total_result.scalar() or 0
    total_pages = max(1, (total + page_size - 1) // page_size)

    result = await db.execute(
        base_stmt.order_by(Device.updated_at.desc()).offset(offset).limit(page_size)
    )
    devices = result.all()

    return templates.TemplateResponse("lots/stock_in.html", {
        "request": request, "devices": devices, "current_user": current_user,
        "page": page, "page_size": page_size, "total": total, "total_pages": total_pages,
    })
```

- [ ] **Step 2: Update `templates/lots/stock_in.html`**

**Change 1:** Fix DataTables (line 39) — `pageLength:25` conflicts with server-side pagination:
```html
<!-- OLD: -->
<script>$(document).ready(function(){ $('#stockTable').DataTable({pageLength:25}); });</script>

<!-- NEW: -->
<script>$(document).ready(function(){ $('#stockTable').DataTable({paging:false}); });</script>
```

**Change 2:** Add the pagination widget after `</div>` closing the `.card` (insert before `{% endblock %}` at line 37):
```html
  </div>
</div>

{# ── Pagination ────────────────────────────────────────────────────────── #}
{% if total_pages and total_pages > 1 %}
<nav class="mt-3" aria-label="Device list pagination">
  <ul class="pagination pagination-sm justify-content-center mb-0">
    <li class="page-item {% if page <= 1 %}disabled{% endif %}">
      <a class="page-link" href="?page={{ page - 1 }}&page_size={{ page_size }}">‹ Prev</a>
    </li>
    {% for p in range(1, total_pages + 1) %}
      {% if p == page %}
        <li class="page-item active"><span class="page-link">{{ p }}</span></li>
      {% elif p == 1 or p == total_pages or (p >= page - 2 and p <= page + 2) %}
        <li class="page-item"><a class="page-link" href="?page={{ p }}&page_size={{ page_size }}">{{ p }}</a></li>
      {% elif p == page - 3 or p == page + 3 %}
        <li class="page-item disabled"><span class="page-link">…</span></li>
      {% endif %}
    {% endfor %}
    <li class="page-item {% if page >= total_pages %}disabled{% endif %}">
      <a class="page-link" href="?page={{ page + 1 }}&page_size={{ page_size }}">Next ›</a>
    </li>
  </ul>
  <p class="text-center text-muted small mt-1">{{ total }} device(s) in stage &bull; Page {{ page }} of {{ total_pages }}</p>
</nav>
{% endif %}
{% endblock %}
```

(Remove the original `{% endblock %}` and `{% block scripts %}` lines and reattach them after the pagination widget; the `{% block scripts %}` with DataTables should stay last.)

- [ ] **Step 3: Run the stock_in_list tests**

```bash
venv\Scripts\python -m pytest tests\test_sprint22_unit.py::test_stock_in_list_has_page_param tests\test_sprint22_unit.py::test_stock_in_list_has_page_size_param tests\test_sprint22_unit.py::test_stock_in_list_passes_total_pages tests\test_sprint22_unit.py::test_stock_in_template_uses_server_paging -v
```

Expected: **4 PASSED**

- [ ] **Step 4: Run full Sprint 22 suite**

```bash
venv\Scripts\python -m pytest tests\test_sprint22_unit.py -v
```

Expected: 9 PASSED, 5 FAILED (Task 5 not done).

- [ ] **Step 5: Commit**

```bash
git add routers\stock.py templates\lots\stock_in.html
git commit -m "perf: add server-side pagination to stock_in_list (50/page); fix DataTables conflict"
```

---

## Task 5: SEC-1 — Role check standardisation in dealers.py and admin.py

**Files:**
- Modify: `routers/dealers.py` — 9 routes using `Depends(get_current_user)` → `Depends(require_sales)`
- Modify: `routers/admin.py` — 1 route using `Depends(get_current_user)` + inline check → `Depends(require_admin)`

**Context:**

In `dealers.py`, `require_sales` and `require_sales_mgr` are already declared at lines 24–25:
```python
require_sales = require_roles(*SALES_ROLES)      # admin, sales, sales_manager, telecaller
require_sales_mgr = require_roles(UserRole.admin, UserRole.sales_manager)
```
`get_current_user` is still imported and needed for internal use (the `current_user.role` filter at line ~73 in `list_dealers`). The import stays — we're only changing route Depends.

In `admin.py`, `require_admin` is declared at line 58:
```python
require_admin = require_roles(UserRole.admin)
```

The 9 routes in `dealers.py` using `Depends(get_current_user)` that need fixing:
1. `list_dealers` — GET `/dealers`
2. `followups_due` — GET `/dealers/followups-due`
3. `new_dealer_form` — GET `/dealers/new`
4. `create_dealer` — POST `/dealers/new`
5. `dealer_profile` — GET `/dealers/{dealer_id}`
6. `edit_dealer_form` — GET `/dealers/{dealer_id}/edit`
7. `update_dealer` — POST `/dealers/{dealer_id}/edit`
8. `call_form` — GET `/dealers/{dealer_id}/call`
9. `log_call` — POST `/dealers/{dealer_id}/call`

The 1 route in `admin.py` to fix:
- `audit_log_view` — GET `/admin/audit-log` — uses `Depends(get_current_user)` + `if current_user.role != UserRole.admin: return RedirectResponse(...)`

- [ ] **Step 1: Replace all 9 `Depends(get_current_user)` in `routers/dealers.py`**

Use your editor's global search-and-replace to change every `Depends(get_current_user)` to `Depends(require_sales)` in this file. **Verify** the count: there should be exactly 9 occurrences before the change and 0 afterwards.

After replace, the `current_user` parameter in each function still has type `User` because `require_sales` returns the same `User` object as `get_current_user`. No other code in the function bodies changes.

Verification — grep before touching to confirm the count:
The 9 occurrences are at these approximate lines: 57, 162, 313, 347, 507, 682, 721, 754, 779.

Full replace command (PowerShell):
```powershell
$path = "C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory\routers\dealers.py"
$content = Get-Content $path -Raw
$fixed = $content -replace 'Depends\(get_current_user\)', 'Depends(require_sales)'
Set-Content $path $fixed -NoNewline
```

Then verify count is 0:
```powershell
(Get-Content $path -Raw).Split("Depends(get_current_user)").Count - 1
```
Expected: `0`

- [ ] **Step 2: Fix `audit_log_view` in `routers/admin.py`**

Find the function at line ~238 and change:

```python
# OLD:
@router.get("/audit-log", response_class=HTMLResponse)
async def audit_log_view(
    request: Request,
    username: str = Query(default=""),
    action: str = Query(default=""),
    table_name: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.admin:
        return RedirectResponse(url="/?error=Admin+only", status_code=302)

# NEW:
@router.get("/audit-log", response_class=HTMLResponse)
async def audit_log_view(
    request: Request,
    username: str = Query(default=""),
    action: str = Query(default=""),
    table_name: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    # (remove the inline role check — require_admin already enforces admin-only)
```

Delete the two lines:
```python
    if current_user.role != UserRole.admin:
        return RedirectResponse(url="/?error=Admin+only", status_code=302)
```

- [ ] **Step 3: Run all SEC-1 tests**

```bash
venv\Scripts\python -m pytest tests\test_sprint22_unit.py::test_dealers_no_bare_get_current_user_in_routes tests\test_sprint22_unit.py::test_admin_audit_log_no_inline_role_check tests\test_sprint22_unit.py::test_admin_no_bare_get_current_user_in_routes -v
```

Expected: **3 PASSED**

- [ ] **Step 4: Run the complete Sprint 22 test suite**

```bash
venv\Scripts\python -m pytest tests\test_sprint22_unit.py -v
```

Expected: **14 PASSED, 0 FAILED**

- [ ] **Step 5: Run the full project test suite to confirm zero regressions**

```bash
venv\Scripts\python -m pytest tests\ --ignore=tests\test_uat.py -v 2>&1 | tail -20
```

Expected: All previously-passing tests still PASS. Zero new failures.

- [ ] **Step 6: Commit**

```bash
git add routers\dealers.py routers\admin.py
git commit -m "sec: replace inline role checks with require_sales/require_admin dependencies (SEC-1)"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Task | Covered? |
|---|---|---|
| PERF-3: eliminate N+1 stage-count queries in dashboard | Task 2 | ✅ — 8 `_count()` calls replaced with dict lookups |
| PERF-4: report CSV exports have no row cap | Task 3 | ✅ — `MAX_EXPORT_ROWS = 5_000` + `.limit()` on 3 routes |
| stock_in_list unbounded | Task 4 | ✅ — pagination added, DataTables conflict fixed |
| SEC-1: inline role checks in dealers.py | Task 5 | ✅ — 9 routes fixed |
| SEC-1: inline role checks in admin.py | Task 5 | ✅ — audit_log_view fixed |
| SEC-1: inline role check in reports.py receivables | Task 3 | ✅ — fixed with `_require_receivables` dependency |
| TDD — failing tests before implementation | Task 1 | ✅ — 14 tests, all fail before Tasks 2–5 |

**Placeholder scan:** None — all steps have exact code blocks.

**Type consistency:** `stage_counts.get(DeviceStage.X.value, 0)` — `stage_counts` keys are `str` (`.value`), `DeviceStage.iqc.value == "iqc"` etc. `setdefault` at line 70 ensures all keys exist. Return is `int`. Consistent throughout.

**No new migrations, no new models.** Sprint 22 is pure performance and security hardening.
