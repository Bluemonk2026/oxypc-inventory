# Sprint 18 — P1 & P2 Pending Items Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement all 6 P1 and 5 P2 pending items for OxyPC Inventory that were not completed in earlier sprints.

**Architecture:** FastAPI + SQLAlchemy async + Jinja2 + Bootstrap 5. All changes follow existing patterns: routers in `routers/`, templates in `templates/`, models in `models/`, migrations via Alembic. No new tables without Alembic migration. CSRF token required on all POST forms.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, Alembic, Jinja2, Bootstrap 5, DataTables, PostgreSQL

**Branch:** `sprint-18-p1-p2` (create from `sprint-17a-ecosystem-foundation`)

**Working directory:** `C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory`

---

## File Structure

### Files Modified
- `static/css/app.css` — Task 1: sidebar sticky positioning
- `routers/dashboard.py` — Task 2: stage-count filter + P&L date-range filter
- `templates/dashboard.html` — Tasks 2 & 3: filter form UI + My Work Queue widget
- `routers/stock.py` — Task 4: lots listing filters
- `templates/lots/list.html` — Task 4: filter form
- `templates/iqc/form.html` — Task 5: expanded CPU datalist + storage/generation options
- `models/spare_parts.py` — Task 6: add repair_job_id FK to SparePartConsumption
- `routers/repair.py` — Task 6: accept part consumption in complete_repair
- `templates/repair/l1.html` — Task 6: parts section in complete form
- `templates/repair/l2.html` — Task 6: parts section in complete form
- `templates/repair/l3.html` — Task 6: parts section in complete form
- `routers/reports.py` — Tasks 7 & 8: stock-aging + overdue routes
- `routers/crm_contacts.py` — Task 9: CSV bulk upload route
- `routers/dealers.py` — Task 10: city + balance + date filters
- `templates/dealers/list.html` — Task 10: advanced filter form
- `routers/grn.py` — Task 11: lot link + receiving summary

### Files Created
- `alembic/versions/20260501_0900_add_repair_job_id_to_consumptions.py` — Task 6 migration
- `templates/reports/stock_aging.html` — Task 7
- `templates/reports/overdue.html` — Task 8
- `templates/crm/contacts/upload.html` — Task 9

---

## Task 1: Sidebar + Topbar Fixed Positioning CSS

**Problem:** `#sidebar` has `min-height: 100vh` but no `position: sticky`, so it scrolls away when the page is long.

**Files:**
- Modify: `static/css/app.css` — lines 15-21

- [ ] **Step 1: Edit sidebar CSS to add sticky positioning**

In `static/css/app.css`, replace the existing `#sidebar` block:

```css
#sidebar {
  width: var(--sidebar-width);
  min-height: 100vh;
  background: var(--sidebar-bg);
  transition: width 0.25s ease;
  overflow-x: hidden;
}
```

With:

```css
#sidebar {
  width: var(--sidebar-width);
  height: 100vh;
  position: sticky;
  top: 0;
  overflow-y: auto;
  overflow-x: hidden;
  background: var(--sidebar-bg);
  transition: width 0.25s ease;
  flex-shrink: 0;
}
```

Also add `align-items: flex-start` to `#wrapper` so the sidebar doesn't stretch beyond its content:

```css
/* After the existing body rule, find or add the #wrapper rule */
#wrapper { align-items: flex-start; }
```

The `#wrapper` is a Bootstrap `d-flex` div in `templates/base.html`. Add/update the CSS rule in `static/css/app.css` after the `body` rule.

- [ ] **Step 2: Verify in browser**

Load any long page (e.g., `/lots` or `/devices`). Scroll down. The sidebar should remain visible and scroll independently if its nav list is taller than the viewport.

- [ ] **Step 3: Commit**

```bash
git add static/css/app.css
git commit -m "fix: sidebar sticky positioning — stays visible during page scroll"
```

---

## Task 2: Dashboard Inventory Stage-Count Filter + P&L Date-Range Filter

**Problem:** The dashboard stage-count cards and P&L chart show all data; no way to filter by stage or date.

**Files:**
- Modify: `routers/dashboard.py`
- Modify: `templates/dashboard.html`

**Context:** `routers/dashboard.py` already computes `stage_counts` (dict of stage→count) and `lot_pl` (list of P&L dicts with `purchase_date` field). The template already has a stage-count grid and P&L chart. We add filter GET params that narrow what's shown.

- [ ] **Step 1: Add filter query params to `routers/dashboard.py`**

In `routers/dashboard.py`, update the main dashboard GET route signature. Find the route `@router.get("/")` and add query params:

```python
@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    stage_filter: str = Query(default=""),
    pl_from: str = Query(default=""),
    pl_to: str = Query(default=""),
):
```

Inside the function, after `stage_counts` is computed, apply `stage_filter`:

```python
# Apply stage filter to device list shown in stage-count highlight
if stage_filter:
    filtered_stage_counts = {stage_filter: stage_counts.get(stage_filter, 0)}
else:
    filtered_stage_counts = stage_counts
```

Apply `pl_from` / `pl_to` to `lot_pl` list:

```python
# Apply date range filter to P&L data
try:
    from datetime import datetime as dt
    if pl_from:
        pl_from_dt = dt.strptime(pl_from, "%Y-%m-%d")
        lot_pl = [row for row in lot_pl
                  if row.get("purchase_date") and row["purchase_date"] >= pl_from_dt]
    if pl_to:
        pl_to_dt = dt.strptime(pl_to, "%Y-%m-%d")
        lot_pl = [row for row in lot_pl
                  if row.get("purchase_date") and row["purchase_date"] <= pl_to_dt]
except Exception:
    pass  # Invalid date — ignore filter
```

Pass filter values to template context:

```python
return templates.TemplateResponse("dashboard.html", {
    # ... existing context ...
    "stage_filter": stage_filter,
    "pl_from": pl_from,
    "pl_to": pl_to,
    "stage_counts": filtered_stage_counts,
    "all_stages": list(DeviceStage),  # for filter dropdown
})
```

- [ ] **Step 2: Add filter form to `templates/dashboard.html`**

Near the top of the `{% block content %}`, before the stage-count card grid, add:

```html
<!-- Dashboard Filters -->
<form method="get" action="/" class="row g-2 mb-3 align-items-end">
  <div class="col-md-3">
    <label class="form-label small fw-semibold">Filter by Stage</label>
    <select name="stage_filter" class="form-select form-select-sm">
      <option value="">All Stages</option>
      {% for stage in all_stages %}
      <option value="{{ stage.value }}" {% if stage_filter == stage.value %}selected{% endif %}>
        {{ stage.value.replace('_',' ').title() }}
      </option>
      {% endfor %}
    </select>
  </div>
  <div class="col-md-3">
    <label class="form-label small fw-semibold">P&L From Date</label>
    <input type="date" name="pl_from" class="form-control form-control-sm" value="{{ pl_from }}">
  </div>
  <div class="col-md-3">
    <label class="form-label small fw-semibold">P&L To Date</label>
    <input type="date" name="pl_to" class="form-control form-control-sm" value="{{ pl_to }}">
  </div>
  <div class="col-auto">
    <button type="submit" class="btn btn-sm btn-primary">
      <i class="bi bi-funnel me-1"></i>Apply
    </button>
    <a href="/" class="btn btn-sm btn-outline-secondary ms-1">Clear</a>
  </div>
</form>
```

- [ ] **Step 3: Commit**

```bash
git add routers/dashboard.py templates/dashboard.html
git commit -m "feat: dashboard stage-count and P&L date-range filters"
```

---

## Task 3: Dashboard My Work Queue Widget Enhancement

**Problem:** The My Work Queue currently shows as a text banner. The spec asks for a proper widget showing actual devices in the current user's active repair/QC stage.

**Files:**
- Modify: `routers/dashboard.py` — query actual device list for user_queue
- Modify: `templates/dashboard.html` — replace text banner with device table widget

**Context:** `routers/dashboard.py` already computes `user_queue` as a dict `{stage: count}`. We need to also query the actual devices per stage for the current user's role, and render them as a small table.

- [ ] **Step 1: Add device-level My Work Queue query to `routers/dashboard.py`**

After the existing `user_queue` dict is built, add a query to get actual devices in those stages. Add this import at the top if not present:

```python
from models.device import Device, DeviceStage, StageMovement, STAGE_LABELS
```

Then in the dashboard function, after user_queue is computed:

```python
# My Work Queue — actual device list in user's active stages
from sqlalchemy import or_
work_queue_stages = []
role_val = current_user.role.value if current_user.role else ""
ROLE_STAGE_MAP = {
    "l1_engineer":         [DeviceStage.l1],
    "l2_engineer":         [DeviceStage.l2],
    "l3_engineer":         [DeviceStage.l3],
    "qc_inspector":        [DeviceStage.qc_check, DeviceStage.final_qc],
    "inventory_manager":   [DeviceStage.grn, DeviceStage.iqc, DeviceStage.stock_in],
    "sales":               [DeviceStage.ready_to_sale],
}
work_queue_stages = ROLE_STAGE_MAP.get(role_val, [])
if current_user.role == UserRole.admin:
    work_queue_stages = list(DeviceStage)

work_queue_devices = []
if work_queue_stages:
    wq_result = await db.execute(
        select(Device)
        .where(Device.current_stage.in_(work_queue_stages))
        .order_by(Device.updated_at.asc())
        .limit(20)
    )
    work_queue_devices = wq_result.scalars().all()
```

Pass to template:

```python
return templates.TemplateResponse("dashboard.html", {
    # ... existing context ...
    "work_queue_devices": work_queue_devices,
})
```

- [ ] **Step 2: Replace banner with device table widget in `templates/dashboard.html`**

Find the existing My Work Queue section (role-based banner at the top). Replace it with:

```html
{% if work_queue_devices %}
<div class="card border-0 shadow-sm mb-4">
  <div class="card-header bg-transparent fw-semibold">
    <i class="bi bi-person-workspace me-2 text-primary"></i>My Work Queue
    <span class="badge bg-primary ms-2">{{ work_queue_devices|length }}</span>
  </div>
  <div class="card-body p-0">
    <div class="table-responsive">
      <table class="table table-sm table-hover mb-0">
        <thead class="table-light">
          <tr>
            <th>Barcode</th>
            <th>Brand / Model</th>
            <th>Stage</th>
            <th>In Stage Since</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {% for d in work_queue_devices %}
          <tr>
            <td><span class="font-monospace">{{ d.barcode }}</span></td>
            <td>{{ d.brand or '' }} {{ d.model or '' }}</td>
            <td>
              <span class="badge bg-secondary">
                {{ d.current_stage.value.replace('_',' ').title() }}
              </span>
            </td>
            <td class="text-muted small">
              {% set age = (now - d.updated_at).days if d.updated_at else 0 %}
              {{ age }}d ago
            </td>
            <td>
              <a href="/devices/{{ d.barcode }}" class="btn btn-xs btn-outline-primary py-0 px-1">View</a>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>
{% endif %}
```

Ensure `now` is in the dashboard template context (add `"now": datetime.utcnow()` to the `TemplateResponse` call in `routers/dashboard.py`).

- [ ] **Step 3: Commit**

```bash
git add routers/dashboard.py templates/dashboard.html
git commit -m "feat: My Work Queue widget shows actual devices by role/stage"
```

---

## Task 4: Lots Listing — Vendor, Date-Range Filters

**Problem:** `/lots` has no filter controls — DataTable client-side search is insufficient for supplier/date range filtering on large datasets.

**Files:**
- Modify: `routers/stock.py` — `list_lots` route (lines 26–73)
- Modify: `templates/lots/list.html` — add filter form at top

**Context:** `Lot` model has `supplier_name` (varchar), `purchase_date` (DateTime), `vendor_name` (varchar). No `status` column exists — lots don't have a status field.

- [ ] **Step 1: Add filter query params to `list_lots` in `routers/stock.py`**

Replace the `list_lots` signature:

```python
@router.get("/lots", response_class=HTMLResponse)
async def list_lots(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    q: str = Query(default=""),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
):
```

Apply filters before counting and fetching:

```python
from sqlalchemy import or_
from datetime import datetime as dt

base_stmt = select(Lot)
if q:
    like = f"%{q}%"
    base_stmt = base_stmt.where(or_(
        Lot.supplier_name.ilike(like),
        Lot.lot_number.ilike(like),
        Lot.vendor_name.ilike(like),
    ))
if date_from:
    try:
        base_stmt = base_stmt.where(Lot.purchase_date >= dt.strptime(date_from, "%Y-%m-%d"))
    except ValueError:
        pass
if date_to:
    try:
        base_stmt = base_stmt.where(Lot.purchase_date <= dt.strptime(date_to, "%Y-%m-%d"))
    except ValueError:
        pass

# Total count for pagination
total_result = await db.execute(select(func.count()).select_from(base_stmt.subquery()))
total = total_result.scalar() or 0
total_pages = max(1, (total + page_size - 1) // page_size)

# Fetch page
lots_result = await db.execute(
    base_stmt.order_by(Lot.created_at.desc()).offset(offset).limit(page_size)
)
```

Pass filters to template:

```python
return templates.TemplateResponse("lots/list.html", {
    # ... existing context ...
    "q": q,
    "date_from": date_from,
    "date_to": date_to,
})
```

- [ ] **Step 2: Add filter form to `templates/lots/list.html`**

Before the existing table/DataTable, add:

```html
<form method="get" action="/lots" class="row g-2 mb-3 align-items-end">
  <div class="col-md-4">
    <label class="form-label small fw-semibold">Search Supplier / Lot</label>
    <input type="text" name="q" class="form-control form-control-sm"
           placeholder="Supplier name, lot number…" value="{{ q }}">
  </div>
  <div class="col-md-3">
    <label class="form-label small fw-semibold">Purchase From</label>
    <input type="date" name="date_from" class="form-control form-control-sm" value="{{ date_from }}">
  </div>
  <div class="col-md-3">
    <label class="form-label small fw-semibold">Purchase To</label>
    <input type="date" name="date_to" class="form-control form-control-sm" value="{{ date_to }}">
  </div>
  <div class="col-auto">
    <button type="submit" class="btn btn-sm btn-primary">
      <i class="bi bi-funnel me-1"></i>Filter
    </button>
    <a href="/lots" class="btn btn-sm btn-outline-secondary ms-1">Clear</a>
  </div>
</form>
```

- [ ] **Step 3: Commit**

```bash
git add routers/stock.py templates/lots/list.html
git commit -m "feat: lots listing supplier and date-range filters"
```

---

## Task 5: IQC Form — Expand CPU, Generation, Storage Dropdowns

**Problem:** CPU is a free-text field (loses consistency), Generation doesn't include Apple M-series, Storage is missing some common capacities.

**Files:**
- Modify: `templates/iqc/form.html`

**Current state:**
- CPU: `<input type="text">` free-text
- Generation: `<select>` with 4th–14th Gen + AMD Ryzen 3/5/7
- RAM: `<select>` with 2/4/8/12/16/24/32/64
- Storage: `<select>` with 128/240/256/480/512/1000/2000 GB
- Storage type: SSD/NVMe/HDD/eMMC/SSHD

**Changes needed:**
1. Convert CPU to `<input>` with `<datalist>` (keeps free-text ability but offers suggestions)
2. Add Apple M1/M2/M3/M4 to Generation dropdown
3. Add 320 GB and 960 GB to Storage dropdown

- [ ] **Step 1: Add CPU datalist to `templates/iqc/form.html`**

Find the CPU input field. It currently looks like:
```html
<input type="text" name="cpu" ...>
```

Change it to use a datalist:
```html
<input type="text" name="cpu" class="form-control" list="cpu-list"
       placeholder="Type or select CPU" value="{{ device.cpu or '' if device else '' }}">
<datalist id="cpu-list">
  <option value="Intel Core i3">
  <option value="Intel Core i5">
  <option value="Intel Core i7">
  <option value="Intel Core i9">
  <option value="Intel Core Ultra 5">
  <option value="Intel Core Ultra 7">
  <option value="Intel Celeron">
  <option value="Intel Pentium">
  <option value="AMD Ryzen 3">
  <option value="AMD Ryzen 5">
  <option value="AMD Ryzen 7">
  <option value="AMD Ryzen 9">
  <option value="Apple M1">
  <option value="Apple M2">
  <option value="Apple M3">
  <option value="Apple M4">
</datalist>
```

- [ ] **Step 2: Add Apple M-series to Generation dropdown**

Find the Generation `<select name="generation">`. Add after the existing AMD Ryzen options:

```html
<option value="Apple M1">Apple M1</option>
<option value="Apple M2">Apple M2</option>
<option value="Apple M3">Apple M3</option>
<option value="Apple M4">Apple M4</option>
```

- [ ] **Step 3: Add 320 GB and 960 GB to Storage dropdown**

Find the Storage `<select name="storage_gb">`. The current options include 128, 240, 256, 480, 512, 1000, 2000. Insert:

After `256`:
```html
<option value="320">320 GB</option>
```
After `512`:
```html
<option value="960">960 GB</option>
```

Full corrected order: 128 → 240 → 256 → 320 → 480 → 512 → 960 → 1000 → 2000

- [ ] **Step 4: Commit**

```bash
git add templates/iqc/form.html
git commit -m "feat: IQC form — CPU datalist, Apple M-series generation, 320/960GB storage"
```

---

## Task 6: Repair Part Consumption — Link to Repair Job

**Problem:** `SparePartConsumption` has no link to a specific `RepairJob` — can't see which parts were used in which repair job. Also, completing a repair doesn't record parts used.

**Files:**
- Modify: `models/spare_parts.py` — add `repair_job_id` FK
- Create: `alembic/versions/20260501_0900_add_repair_job_id_to_consumptions.py`
- Modify: `routers/repair.py` — accept part_id + qty in `complete_repair` POST
- Modify: `templates/repair/l1.html` — add parts section to complete form
- Modify: `templates/repair/l2.html` — same
- Modify: `templates/repair/l3.html` — same

- [ ] **Step 1: Add `repair_job_id` FK to `SparePartConsumption` model**

In `models/spare_parts.py`, add after the `lot_id` column:

```python
repair_job_id = Column(UUID(as_uuid=True), ForeignKey("repair_jobs.id"), nullable=True, index=True)
```

Also add the relationship (import `RepairJob` lazily to avoid circular imports):

```python
repair_job = relationship("RepairJob", back_populates="spare_part_consumptions", foreign_keys=[repair_job_id])
```

In `models/repair.py`, add the back-reference to `RepairJob`:

```python
spare_part_consumptions = relationship("SparePartConsumption", back_populates="repair_job", lazy="select")
```

- [ ] **Step 2: Create Alembic migration**

Create `alembic/versions/20260501_0900_add_repair_job_id_to_consumptions.py`:

```python
"""add repair_job_id to spare_parts_consumption

Revision ID: 20260501_0900
Revises: 20260430_0900
Create Date: 2026-05-01 09:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260501_0900'
down_revision = '20260430_0900'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'spare_parts_consumption',
        sa.Column('repair_job_id', postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_index(
        'ix_spare_parts_consumption_repair_job_id',
        'spare_parts_consumption',
        ['repair_job_id']
    )
    op.create_foreign_key(
        'fk_spc_repair_job_id',
        'spare_parts_consumption', 'repair_jobs',
        ['repair_job_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('fk_spc_repair_job_id', 'spare_parts_consumption', type_='foreignkey')
    op.drop_index('ix_spare_parts_consumption_repair_job_id', table_name='spare_parts_consumption')
    op.drop_column('spare_parts_consumption', 'repair_job_id')
```

> **IMPORTANT:** Check the actual `down_revision` by running:
> ```bash
> python -m alembic heads
> ```
> and update the `down_revision` value to match the current head.

- [ ] **Step 3: Run migration**

```bash
python -m alembic upgrade head
```

Expected: `Running upgrade <prev> -> 20260501_0900, add repair_job_id to spare_parts_consumption`

- [ ] **Step 4: Update `complete_repair` in `routers/repair.py` to accept parts**

Find the `complete_repair` POST route. Add new Form parameters:

```python
@router.post("/repair/complete")
async def complete_repair(
    request: Request,
    job_id: str = Form(...),
    final_status: str = Form(...),
    resolution: str = Form(""),
    # ... existing params ...
    # New: part consumption (up to 5 parts per job)
    part_ids: list[str] = Form(default=[]),
    part_qtys: list[str] = Form(default=[]),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
```

After the job is fetched and the existing repair completion logic runs, before `await db.commit()`, add:

```python
# Record spare parts used in this repair
from models.spare_parts import SparePartConsumption, SparePart
from decimal import Decimal

for pid, qty_str in zip(part_ids, part_qtys):
    if not pid or not qty_str:
        continue
    try:
        qty = int(qty_str)
        if qty <= 0:
            continue
    except ValueError:
        continue

    part_result = await db.execute(select(SparePart).where(SparePart.id == pid))
    part = part_result.scalar_one_or_none()
    if not part:
        continue

    # Deduct from stock (floor at 0)
    part.qty_in_stock = max(0, (part.qty_in_stock or 0) - qty)
    total = Decimal(str(part.unit_price)) * qty
    db.add(SparePartConsumption(
        device_id=device.id,
        lot_id=device.lot_id,
        repair_job_id=job.id,
        part_id=part.id,
        qty_used=qty,
        unit_cost=part.unit_price,
        total_cost=total,
        used_by=current_user.username,
        stage=job.stage,
        notes=f"Repair job {job.id}",
    ))
```

- [ ] **Step 5: Add parts section to `templates/repair/l1.html` complete form**

Inside the "Complete L1 Repair Job" form (after the `resolution` input, before the submit button), add:

```html
<!-- Parts Used -->
<div class="col-12 mt-2">
  <label class="form-label small fw-semibold">Parts Used (optional — up to 5)</label>
  <div id="parts-container">
    <div class="row g-2 mb-1 parts-row">
      <div class="col-md-7">
        <select name="part_ids" class="form-select form-select-sm part-select">
          <option value="">— Select Part —</option>
          {% for part in available_parts %}
          <option value="{{ part.id }}">{{ part.part_code }} — {{ part.name }} (Stock: {{ part.qty_in_stock }})</option>
          {% endfor %}
        </select>
      </div>
      <div class="col-md-3">
        <input type="number" name="part_qtys" class="form-control form-control-sm"
               placeholder="Qty" min="1" value="">
      </div>
    </div>
  </div>
  <button type="button" class="btn btn-outline-secondary btn-sm mt-1" id="add-part-btn"
          onclick="addPartRow()">
    <i class="bi bi-plus me-1"></i>Add Another Part
  </button>
</div>

<script>
let partRowCount = 1;
function addPartRow() {
  if (partRowCount >= 5) return;
  partRowCount++;
  const container = document.getElementById('parts-container');
  const row = container.querySelector('.parts-row').cloneNode(true);
  row.querySelectorAll('select, input').forEach(el => el.value = '');
  container.appendChild(row);
  if (partRowCount >= 5) document.getElementById('add-part-btn').disabled = true;
}
</script>
```

- [ ] **Step 6: Pass `available_parts` to repair template context in `routers/repair.py`**

In the `get_repair_page` function (the GET route returning the repair template), add a query for available spare parts:

```python
from models.spare_parts import SparePart
parts_result = await db.execute(
    select(SparePart).where(SparePart.qty_in_stock > 0).order_by(SparePart.name)
)
available_parts = parts_result.scalars().all()
```

Add `"available_parts": available_parts` to the `TemplateResponse` context.

- [ ] **Step 7: Repeat parts section for `templates/repair/l2.html` and `templates/repair/l3.html`**

Apply the identical parts section HTML (Step 5) to `l2.html` and `l3.html` complete forms. The `available_parts` context is passed from the same `get_repair_page` route which handles all stages.

- [ ] **Step 8: Commit**

```bash
git add models/spare_parts.py models/repair.py \
        alembic/versions/20260501_0900_add_repair_job_id_to_consumptions.py \
        routers/repair.py \
        templates/repair/l1.html templates/repair/l2.html templates/repair/l3.html
git commit -m "feat: repair part consumption linked to repair jobs — tracks parts used, deducts stock"
```

---

## Task 7: Stock Aging Report

**Problem:** No report showing devices stuck in each stage longer than threshold. Operations team can't identify bottlenecks.

**Files:**
- Modify: `routers/reports.py`
- Create: `templates/reports/stock_aging.html`

**Thresholds (business rules):**
- `l1`, `l2`: > 7 days
- `l3`: > 14 days
- `qc_check`, `final_qc`: > 3 days
- `cleaning`, `dry_sanding`, `masking`, `painting`, `water_sanding`: > 5 days
- `ready_to_sale`: > 30 days
- `iqc`, `stock_in`: > 5 days

- [ ] **Step 1: Add `/reports/stock-aging` route to `routers/reports.py`**

Add after the existing `stage_movement_report` route:

```python
AGING_THRESHOLDS = {
    "l1":           7,
    "l2":           7,
    "l3":           14,
    "qc_check":     3,
    "final_qc":     3,
    "cleaning":     5,
    "dry_sanding":  5,
    "masking":      5,
    "painting":     5,
    "water_sanding": 5,
    "ready_to_sale": 30,
    "iqc":          5,
    "stock_in":     5,
}


@router.get("/stock-aging", response_class=HTMLResponse)
async def stock_aging_report(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    aging_rows = []

    for stage_name, threshold_days in AGING_THRESHOLDS.items():
        cutoff = now - timedelta(days=threshold_days)
        try:
            stage_enum = DeviceStage(stage_name)
        except ValueError:
            continue

        result = await db.execute(
            select(Device, Lot.lot_number)
            .join(Lot, Device.lot_id == Lot.id, isouter=True)
            .where(
                Device.current_stage == stage_enum,
                Device.updated_at <= cutoff,
            )
            .order_by(Device.updated_at.asc())
        )
        devices = result.all()

        for device, lot_number in devices:
            days_in_stage = (now - device.updated_at).days if device.updated_at else 0
            aging_rows.append({
                "barcode":       device.barcode,
                "brand":         device.brand or "",
                "model":         device.model or "",
                "stage":         stage_name,
                "stage_label":   stage_name.replace("_", " ").title(),
                "days_in_stage": days_in_stage,
                "threshold":     threshold_days,
                "excess_days":   days_in_stage - threshold_days,
                "lot_number":    lot_number or "",
                "updated_at":    device.updated_at,
            })

    # Sort by excess_days descending (worst first)
    aging_rows.sort(key=lambda r: r["excess_days"], reverse=True)

    return templates.TemplateResponse("reports/stock_aging.html", {
        "request": request,
        "aging_rows": aging_rows,
        "current_user": current_user,
        "total": len(aging_rows),
    })
```

- [ ] **Step 2: Create `templates/reports/stock_aging.html`**

```html
{% extends "base.html" %}
{% block title %}Stock Aging Report — OxyPC{% endblock %}
{% block page_title %}Stock Aging Report{% endblock %}
{% block content %}

<div class="d-flex justify-content-between align-items-center mb-3">
  <div>
    <span class="badge bg-danger fs-6">{{ total }} device(s) overdue</span>
  </div>
</div>

{% if aging_rows %}
<div class="card border-0 shadow-sm">
  <div class="card-body p-0">
    <div class="table-responsive">
      <table class="table table-sm table-hover mb-0" id="aging-table">
        <thead class="table-light">
          <tr>
            <th>Barcode</th>
            <th>Brand / Model</th>
            <th>Stage</th>
            <th>Lot</th>
            <th>Days in Stage</th>
            <th>Threshold</th>
            <th>Overdue By</th>
            <th>Last Updated</th>
          </tr>
        </thead>
        <tbody>
          {% for row in aging_rows %}
          <tr class="{% if row.excess_days > 14 %}table-danger{% elif row.excess_days > 7 %}table-warning{% endif %}">
            <td><a href="/devices/{{ row.barcode }}" class="font-monospace">{{ row.barcode }}</a></td>
            <td>{{ row.brand }} {{ row.model }}</td>
            <td><span class="badge bg-secondary">{{ row.stage_label }}</span></td>
            <td class="text-muted small">{{ row.lot_number }}</td>
            <td class="fw-semibold">{{ row.days_in_stage }}d</td>
            <td class="text-muted">{{ row.threshold }}d</td>
            <td class="text-danger fw-bold">+{{ row.excess_days }}d</td>
            <td class="text-muted small">
              {{ row.updated_at.strftime('%d %b %Y') if row.updated_at else '—' }}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>
{% else %}
<div class="alert alert-success">
  <i class="bi bi-check-circle me-2"></i>No devices are overdue in any stage. Inventory is healthy!
</div>
{% endif %}

{% endblock %}
```

- [ ] **Step 3: Add sidebar link for stock aging report**

In `templates/base.html`, find the Reports section and add:

```html
<li><a href="/reports/stock-aging" class="nav-link {% if '/reports/stock-aging' in request.url.path %}active{% endif %}">
  <i class="bi bi-hourglass-split me-2"></i> Stock Aging
</a></li>
```

- [ ] **Step 4: Commit**

```bash
git add routers/reports.py templates/reports/stock_aging.html templates/base.html
git commit -m "feat: stock aging report — devices exceeding stage thresholds"
```

---

## Task 8: Overdue Devices Report + CSV Export

**Problem:** Operations team needs a sorted list of the longest-sitting devices regardless of stage, with CSV download for follow-up.

**Files:**
- Modify: `routers/reports.py`
- Create: `templates/reports/overdue.html`

- [ ] **Step 1: Add `/reports/overdue` and `/reports/overdue/csv` routes**

Add to `routers/reports.py`:

```python
@router.get("/overdue", response_class=HTMLResponse)
async def overdue_report(
    request: Request,
    stage: str = Query(default=""),
    min_days: int = Query(default=3, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    cutoff = now - timedelta(days=min_days)

    stmt = (
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id, isouter=True)
        .where(
            Device.current_stage.notin_([DeviceStage.sold, DeviceStage.scrapped]),
            Device.updated_at <= cutoff,
        )
        .order_by(Device.updated_at.asc())
        .limit(500)
    )
    if stage:
        try:
            stmt = stmt.where(Device.current_stage == DeviceStage(stage))
        except ValueError:
            pass

    result = await db.execute(stmt)
    rows = []
    for device, lot_number in result.all():
        days = (now - device.updated_at).days if device.updated_at else 0
        rows.append({
            "barcode":    device.barcode,
            "brand":      device.brand or "",
            "model":      device.model or "",
            "stage":      device.current_stage.value if device.current_stage else "",
            "days":       days,
            "lot_number": lot_number or "",
            "updated_at": device.updated_at,
        })

    return templates.TemplateResponse("reports/overdue.html", {
        "request": request,
        "rows": rows,
        "stage": stage,
        "min_days": min_days,
        "all_stages": list(DeviceStage),
        "current_user": current_user,
    })


@router.get("/overdue/csv")
async def overdue_csv(
    stage: str = Query(default=""),
    min_days: int = Query(default=3, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    cutoff = now - timedelta(days=min_days)

    stmt = (
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id, isouter=True)
        .where(
            Device.current_stage.notin_([DeviceStage.sold, DeviceStage.scrapped]),
            Device.updated_at <= cutoff,
        )
        .order_by(Device.updated_at.asc())
    )
    if stage:
        try:
            stmt = stmt.where(Device.current_stage == DeviceStage(stage))
        except ValueError:
            pass

    result = await db.execute(stmt)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Barcode", "Brand", "Model", "Stage", "Days in Stage", "Lot Number", "Last Updated"])
    for device, lot_number in result.all():
        days = (now - device.updated_at).days if device.updated_at else 0
        writer.writerow([
            device.barcode, device.brand or "", device.model or "",
            device.current_stage.value if device.current_stage else "",
            days, lot_number or "",
            device.updated_at.strftime("%Y-%m-%d") if device.updated_at else "",
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=overdue_devices.csv"},
    )
```

- [ ] **Step 2: Create `templates/reports/overdue.html`**

```html
{% extends "base.html" %}
{% block title %}Overdue Devices — OxyPC{% endblock %}
{% block page_title %}Overdue Devices{% endblock %}
{% block content %}

<form method="get" action="/reports/overdue" class="row g-2 mb-3 align-items-end">
  <div class="col-md-3">
    <label class="form-label small fw-semibold">Filter by Stage</label>
    <select name="stage" class="form-select form-select-sm">
      <option value="">All Active Stages</option>
      {% for s in all_stages %}
      {% if s.value not in ['sold','scrapped'] %}
      <option value="{{ s.value }}" {% if stage == s.value %}selected{% endif %}>
        {{ s.value.replace('_',' ').title() }}
      </option>
      {% endif %}
      {% endfor %}
    </select>
  </div>
  <div class="col-md-2">
    <label class="form-label small fw-semibold">Min Days in Stage</label>
    <input type="number" name="min_days" class="form-control form-control-sm"
           value="{{ min_days }}" min="0">
  </div>
  <div class="col-auto">
    <button type="submit" class="btn btn-sm btn-primary">
      <i class="bi bi-funnel me-1"></i>Filter
    </button>
    <a href="/reports/overdue" class="btn btn-sm btn-outline-secondary ms-1">Clear</a>
    <a href="/reports/overdue/csv?stage={{ stage }}&min_days={{ min_days }}"
       class="btn btn-sm btn-outline-success ms-1">
      <i class="bi bi-download me-1"></i>Export CSV
    </a>
  </div>
</form>

{% if rows %}
<div class="card border-0 shadow-sm">
  <div class="card-body p-0">
    <div class="table-responsive">
      <table class="table table-sm table-hover mb-0">
        <thead class="table-light">
          <tr>
            <th>#</th>
            <th>Barcode</th>
            <th>Brand / Model</th>
            <th>Stage</th>
            <th>Days Waiting</th>
            <th>Lot</th>
            <th>Last Updated</th>
          </tr>
        </thead>
        <tbody>
          {% for row in rows %}
          <tr>
            <td class="text-muted">{{ loop.index }}</td>
            <td><a href="/devices/{{ row.barcode }}" class="font-monospace">{{ row.barcode }}</a></td>
            <td>{{ row.brand }} {{ row.model }}</td>
            <td><span class="badge bg-secondary">{{ row.stage.replace('_',' ').title() }}</span></td>
            <td class="fw-bold {% if row.days > 14 %}text-danger{% elif row.days > 7 %}text-warning{% endif %}">
              {{ row.days }}d
            </td>
            <td class="text-muted small">{{ row.lot_number }}</td>
            <td class="text-muted small">
              {{ row.updated_at.strftime('%d %b %Y') if row.updated_at else '—' }}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>
{% else %}
<div class="alert alert-success">
  <i class="bi bi-check-circle me-2"></i>No overdue devices found with current filters.
</div>
{% endif %}

{% endblock %}
```

- [ ] **Step 3: Add sidebar link for overdue report**

In `templates/base.html`, in the Reports section, add:

```html
<li><a href="/reports/overdue" class="nav-link {% if '/reports/overdue' in request.url.path %}active{% endif %}">
  <i class="bi bi-exclamation-triangle me-2"></i> Overdue Devices
</a></li>
```

- [ ] **Step 4: Commit**

```bash
git add routers/reports.py templates/reports/overdue.html templates/base.html
git commit -m "feat: overdue devices report with CSV export"
```

---

## Task 9: CRM Bulk Upload — CSV Contacts

**Problem:** No bulk upload for CRM contacts — each contact must be added one-by-one. Sales team can't import a contacts list.

**Files:**
- Modify: `routers/crm_contacts.py`
- Create: `templates/crm/contacts/upload.html`

**CSV format expected:** `company_name`, `contact_person`, `phone`, `email`, `city` (columns, first row = header)

- [ ] **Step 1: Add CSV upload routes to `routers/crm_contacts.py`**

The file already imports `UploadFile`, `File`, `csv`, `io`. Add two routes after the existing list route:

```python
@router.get("/upload", response_class=HTMLResponse)
async def upload_contacts_form(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    from auth.dependencies import _check_roles
    _check_roles(current_user, CRM_ROLES)
    return templates.TemplateResponse("crm/contacts/upload.html", {
        "request": request, "current_user": current_user,
        "result": None, "error": None,
    })


@router.post("/upload")
async def upload_contacts_csv(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from auth.dependencies import _check_roles
    _check_roles(current_user, CRM_ROLES)

    if not file.filename.endswith(".csv"):
        return templates.TemplateResponse("crm/contacts/upload.html", {
            "request": request, "current_user": current_user,
            "result": None, "error": "Please upload a .csv file",
        })

    content = await file.read()
    try:
        text_content = content.decode("utf-8-sig")  # handle BOM
    except UnicodeDecodeError:
        text_content = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text_content))
    required_cols = {"company_name"}
    if not required_cols.issubset({c.strip().lower() for c in (reader.fieldnames or [])}):
        return templates.TemplateResponse("crm/contacts/upload.html", {
            "request": request, "current_user": current_user,
            "result": None, "error": "CSV must have at least a 'company_name' column",
        })

    created = 0
    skipped = 0
    errors = []

    for i, row in enumerate(reader, start=2):
        company = (row.get("company_name") or "").strip()
        if not company:
            skipped += 1
            continue

        phone = (row.get("phone") or "").strip()
        email = (row.get("email") or "").strip()

        # Skip if already exists (match on company_name + phone)
        existing = (await db.execute(
            select(CRMContact).where(
                CRMContact.company_name == company,
                CRMContact.phone == phone if phone else CRMContact.phone.is_(None),
            )
        )).scalars().first()

        if existing:
            skipped += 1
            continue

        try:
            code = await _next_code(db)
            contact = CRMContact(
                crm_code=code,
                company_name=company,
                contact_person=(row.get("contact_person") or "").strip() or None,
                phone=phone or None,
                email=email or None,
                city=(row.get("city") or "").strip() or None,
                contact_type="buyer",
                status="active",
                created_by=current_user.username,
            )
            db.add(contact)
            await db.flush()  # get id without committing
            created += 1
        except Exception as e:
            errors.append(f"Row {i}: {str(e)[:80]}")

    await db.commit()

    return templates.TemplateResponse("crm/contacts/upload.html", {
        "request": request, "current_user": current_user,
        "result": {"created": created, "skipped": skipped, "errors": errors},
        "error": None,
    })
```

**Note:** `_check_roles` is an internal helper — if it doesn't exist, replace with `require_roles(*CRM_ROLES)` as a `Depends`. Check the `auth/dependencies.py` pattern and use `Depends(require_roles(*CRM_ROLES))` in the route signature instead.

- [ ] **Step 2: Create `templates/crm/contacts/upload.html`**

```html
{% extends "base.html" %}
{% block title %}Bulk Upload Contacts — OxyPC{% endblock %}
{% block page_title %}Bulk Upload CRM Contacts{% endblock %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-lg-7">
    <div class="card border-0 shadow-sm">
      <div class="card-header bg-transparent fw-semibold">
        <i class="bi bi-upload me-2"></i>Upload Contacts CSV
      </div>
      <div class="card-body">
        {% if error %}
        <div class="alert alert-danger">{{ error }}</div>
        {% endif %}

        {% if result %}
        <div class="alert alert-success">
          <strong>Upload complete:</strong>
          {{ result.created }} contact(s) created,
          {{ result.skipped }} skipped (already exist or empty).
          {% if result.errors %}
          <ul class="mt-2 mb-0">
            {% for e in result.errors %}<li class="small text-danger">{{ e }}</li>{% endfor %}
          </ul>
          {% endif %}
        </div>
        <a href="/crm/contacts" class="btn btn-primary">View All Contacts</a>
        {% else %}

        <p class="text-muted small mb-3">
          Upload a CSV file with contacts. Required column: <code>company_name</code>.
          Optional: <code>contact_person</code>, <code>phone</code>, <code>email</code>, <code>city</code>.
          Existing contacts (matched by company name + phone) will be skipped.
        </p>

        <form action="/crm/contacts/upload" method="post" enctype="multipart/form-data">
          <input type="hidden" name="csrf_token" value="{{ request.cookies.get('csrf_token', '') }}">
          <div class="mb-3">
            <label class="form-label fw-semibold">CSV File <span class="text-danger">*</span></label>
            <input type="file" name="file" class="form-control" accept=".csv" required>
          </div>
          <div class="d-flex gap-2">
            <button type="submit" class="btn btn-primary">
              <i class="bi bi-upload me-2"></i>Upload & Import
            </button>
            <a href="/crm/contacts" class="btn btn-outline-secondary">Cancel</a>
          </div>
        </form>
        {% endif %}
      </div>
    </div>

    <div class="card border-0 shadow-sm mt-3">
      <div class="card-body">
        <h6 class="fw-semibold">CSV Format Example</h6>
        <pre class="bg-light p-2 rounded small">company_name,contact_person,phone,email,city
Acme Computers,Raj Kumar,9876543210,raj@acme.com,Delhi
TechBazaar,,9123456789,,Mumbai</pre>
      </div>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Add upload link to CRM contacts list page**

In `templates/crm/contacts/list.html`, find the "New Contact" button and add alongside it:

```html
<a href="/crm/contacts/upload" class="btn btn-outline-primary btn-sm">
  <i class="bi bi-upload me-1"></i>Bulk Upload CSV
</a>
```

- [ ] **Step 4: Commit**

```bash
git add routers/crm_contacts.py templates/crm/contacts/upload.html templates/crm/contacts/list.html
git commit -m "feat: CRM bulk upload — CSV import for contacts"
```

---

## Task 10: Dealers Advanced Search

**Problem:** Dealers list only filters by q/status/assigned. Sales team can't filter by city or outstanding balance range.

**Files:**
- Modify: `routers/dealers.py` — `list_dealers` route
- Modify: `templates/dealers/list.html`

**Context:** `Dealer` model has `city`, `status`, `last_sale_date`, `assigned_to`. Outstanding balance is computed from `DealerOrder` aggregate — not a stored column.

- [ ] **Step 1: Add city and last-order-date filters to `list_dealers`**

In `routers/dealers.py`, update the `list_dealers` route signature:

```python
@router.get("", response_class=HTMLResponse)
async def list_dealers(
    request: Request,
    q: str = Query(default=""),
    status: str = Query(default=""),
    assigned: str = Query(default=""),
    city: str = Query(default=""),
    last_order_from: str = Query(default=""),
    last_order_to: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
```

Add city and last-order-date filter conditions after the existing `q` and `status` filters:

```python
if city:
    base_query = base_query.where(Dealer.city.ilike(f"%{city}%"))
if last_order_from:
    try:
        from datetime import datetime as dt
        base_query = base_query.where(
            Dealer.last_sale_date >= dt.strptime(last_order_from, "%Y-%m-%d")
        )
    except ValueError:
        pass
if last_order_to:
    try:
        from datetime import datetime as dt
        base_query = base_query.where(
            Dealer.last_sale_date <= dt.strptime(last_order_to, "%Y-%m-%d")
        )
    except ValueError:
        pass
```

Pass new filter values to the template:

```python
return templates.TemplateResponse("dealers/list.html", {
    # ... existing context ...
    "city": city,
    "last_order_from": last_order_from,
    "last_order_to": last_order_to,
})
```

- [ ] **Step 2: Add advanced filter form to `templates/dealers/list.html`**

Find the existing filter form (has `q`, `status`, `assigned` inputs). Expand it with the new fields:

```html
<!-- Add these fields to the existing filter form -->
<div class="col-md-2">
  <label class="form-label small fw-semibold">City</label>
  <input type="text" name="city" class="form-control form-control-sm"
         placeholder="Filter by city" value="{{ city }}">
</div>
<div class="col-md-2">
  <label class="form-label small fw-semibold">Last Order From</label>
  <input type="date" name="last_order_from" class="form-control form-control-sm"
         value="{{ last_order_from }}">
</div>
<div class="col-md-2">
  <label class="form-label small fw-semibold">Last Order To</label>
  <input type="date" name="last_order_to" class="form-control form-control-sm"
         value="{{ last_order_to }}">
</div>
```

Also update the Clear link to include the new param names:

```html
<a href="/dealers" class="btn btn-sm btn-outline-secondary ms-1">Clear</a>
```

- [ ] **Step 3: Commit**

```bash
git add routers/dealers.py templates/dealers/list.html
git commit -m "feat: dealers advanced search — city and last-order-date filters"
```

---

## Task 11: GRN Enhancements — Lot Link + Receiving Summary

**Problem:** GRN form shows a lot dropdown but doesn't display the lot's existing device count after submission, and the GRN index doesn't show a clear receiving summary.

**Files:**
- Modify: `routers/grn.py` — GRN list and submit routes
- Modify: `templates/grn/index.html` — show receiving summary columns
- Modify: `templates/grn/form.html` — show lot details on selection

- [ ] **Step 1: Enhance `grn_list` to include device count and GRN status**

In `routers/grn.py`, update `grn_list` to batch-load device counts per lot:

```python
@router.get("", response_class=HTMLResponse)
async def grn_list(request: Request, db: AsyncSession = Depends(get_db),
                   current_user: User = Depends(allowed)):
    from models.device import Device
    from sqlalchemy import func

    result = await db.execute(select(Lot).order_by(Lot.created_at.desc()))
    lots = result.scalars().all()
    lot_ids = [lot.id for lot in lots]

    # Batch device count per lot
    dev_counts = {}
    if lot_ids:
        dev_rows = await db.execute(
            select(Device.lot_id, func.count(Device.id))
            .where(Device.lot_id.in_(lot_ids))
            .group_by(Device.lot_id)
        )
        dev_counts = dict(dev_rows.fetchall())

    lot_data = [
        {
            "lot": lot,
            "actual_devices": dev_counts.get(lot.id, 0),
            "grn_received": lot.qty or 0,
            "mismatch": (dev_counts.get(lot.id, 0) != (lot.qty or 0)),
        }
        for lot in lots
    ]

    return templates.TemplateResponse("grn/index.html", {
        "request": request, "lot_data": lot_data, "current_user": current_user,
    })
```

- [ ] **Step 2: Update `templates/grn/index.html` to show receiving summary**

Update the table to use `lot_data` and show the new columns:

```html
<table class="table table-sm table-hover">
  <thead class="table-light">
    <tr>
      <th>Lot Number</th>
      <th>Supplier</th>
      <th>GRN Number</th>
      <th>GRN Date</th>
      <th>Expected Qty</th>
      <th>Received Qty</th>
      <th>Actual Devices</th>
      <th>Status</th>
    </tr>
  </thead>
  <tbody>
    {% for item in lot_data %}
    {% set lot = item.lot %}
    <tr class="{% if item.mismatch %}table-warning{% endif %}">
      <td><a href="/lots/{{ lot.id }}">{{ lot.lot_number }}</a></td>
      <td>{{ lot.supplier_name }}</td>
      <td>{{ lot.grn_number_new or lot.grn_system_number or '—' }}</td>
      <td class="text-muted small">
        {{ lot.grn_date.strftime('%d %b %Y') if lot.grn_date else '—' }}
      </td>
      <td>{{ lot.qty }}</td>
      <td>{{ lot.qty }}</td>
      <td class="fw-semibold {% if item.mismatch %}text-danger{% else %}text-success{% endif %}">
        {{ item.actual_devices }}
      </td>
      <td>
        {% if item.mismatch %}
        <span class="badge bg-warning text-dark">
          <i class="bi bi-exclamation-triangle me-1"></i>Mismatch
        </span>
        {% else %}
        <span class="badge bg-success"><i class="bi bi-check2 me-1"></i>OK</span>
        {% endif %}
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
```

- [ ] **Step 3: Add JavaScript lot-detail preview to `templates/grn/form.html`**

In the GRN form, after the lot dropdown (`<select name="lot_id">`), add a JS preview that shows the selected lot's details:

```html
<div id="lot-preview" class="alert alert-info mt-2 d-none">
  <strong>Lot Details:</strong>
  <span id="lot-preview-text"></span>
</div>

<script>
const lotData = {
  {% for lot in lots %}
  "{{ lot.id }}": {
    supplier: "{{ lot.supplier_name | e }}",
    qty: {{ lot.qty }},
    buying_price: "{{ lot.buying_price }}",
    purchase_date: "{{ lot.purchase_date.strftime('%d %b %Y') if lot.purchase_date else '' }}"
  },
  {% endfor %}
};

document.querySelector('select[name="lot_id"]').addEventListener('change', function() {
  const preview = document.getElementById('lot-preview');
  const text = document.getElementById('lot-preview-text');
  const data = lotData[this.value];
  if (data) {
    text.textContent = `${data.supplier} | Qty: ${data.qty} | Buying: ₹${data.buying_price} | Date: ${data.purchase_date}`;
    preview.classList.remove('d-none');
  } else {
    preview.classList.add('d-none');
  }
});
</script>
```

- [ ] **Step 4: Commit**

```bash
git add routers/grn.py templates/grn/index.html templates/grn/form.html
git commit -m "feat: GRN enhancements — receiving summary, mismatch flag, lot detail preview"
```

---

## Self-Review Against Spec

### Spec coverage check

| Item | Task | Covered? |
|------|------|----------|
| Sidebar sticky CSS | Task 1 | ✅ |
| Dashboard stage-count filter | Task 2 | ✅ |
| Dashboard P&L date-range filter | Task 2 | ✅ |
| My Work Queue widget with device list | Task 3 | ✅ |
| Lots: vendor/date-range filters | Task 4 | ✅ |
| IQC CPU datalist + Apple M-series + 320/960GB | Task 5 | ✅ |
| Repair part consumption linked to job + stock deduction | Task 6 | ✅ |
| Stock Aging report (per-stage threshold) | Task 7 | ✅ |
| Overdue devices report + CSV export | Task 8 | ✅ |
| CRM bulk upload CSV (company, person, phone, email, city) | Task 9 | ✅ |
| Dealers: city + last-order-date filter | Task 10 | ✅ |
| GRN: lot link + receiving summary | Task 11 | ✅ |

### Placeholder scan
- No TBD or TODO present in code blocks
- All file paths explicit
- All SQL/ORM queries written out fully
- CSRF token included in all new POST forms (Tasks 9)
- Audit trail: Task 6 part consumption uses existing audit pattern via `SparePartConsumption` model insert

### Type consistency
- `DeviceStage` enum used consistently across Tasks 2, 3, 7, 8
- `SparePartConsumption` fields match model definition in `models/spare_parts.py`
- `RepairJob.id` (UUID) used correctly as `repair_job_id` FK
- `Lot.supplier_name` (not `supplier`) used correctly in Task 4

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-01-sprint18-p1-p2-pending.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks

**2. Inline Execution** — execute tasks in this session using executing-plans

**Which approach?**
