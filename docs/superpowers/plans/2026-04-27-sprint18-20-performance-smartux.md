# Sprint 18-20: Performance, Smart UX & Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three sequential sprints targeting system performance (Sprint 18), intelligent UX recommendations and auto-population (Sprint 19), and navigation/accessibility improvements (Sprint 20). All sprints are PLAN STATE ONLY — do not implement anything until explicitly instructed.

**Architecture:** Sprint 18 is purely server-side (model indexes + query rewrites + Alembic migration). Sprint 19 adds one new router file and conditional template blocks. Sprint 20 is template-only with one new partial. No new DB tables across all three sprints.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + PostgreSQL 15 + Python 3.11 + Jinja2 + Bootstrap 5 + Alembic

---

# Sprint 18 — Performance: DB Indexes + Query Optimization

**Goal:** Eliminate ~100+ redundant DB queries on dashboard and list pages. Add 15 missing indexes on hot-query columns. Expected result: dashboard load time drops from 3–8s to under 1s.

**Architecture:** All changes are model-level `index=True` flags + query rewrites in routers. One Alembic migration for the composite index. No schema changes, no new tables, no template changes.

---

## File Map

| File | Change |
|---|---|
| `models/device.py` | Add `index=True` to: `current_stage`, `sub_category`, `brand`, `updated_at` |
| `models/repair.py` | Add `index=True` to: `device_id`, `status`, `stage` on RepairJob |
| `models/dealers.py` | Add `index=True` to: `DealerCall.next_followup_date`, `DealerCreditNote.dealer_id`, `DealerCreditNote.order_id` |
| `models/crm.py` | Add `index=True` to: `CRMActivity.contact_id`, `CRMActivity.next_followup`, `CRMActivity.followup_done`, `CRMActivity.deal_id`, `CRMSourcingDeal.contact_id`, `CRMSalesOpportunity.contact_id`, `CRMQuote.contact_id`, `CRMQuoteItem.quote_id`, `CRMPurchaseOrder.contact_id` |
| `models/sales.py` | Add `index=True` to: `Sale.sold_by`, `SaleReturn.sale_id`, `SaleReturn.device_id` |
| `models/lot.py` | Add `index=True` to: `CustomerReceipt.sale_id`, `CustomerReceipt.dealer_order_id` (if defined here) |
| `models/attendance.py` | Add `index=True` to: `user_id`, `date` |
| `routers/dashboard.py` | Replace 17-query stage_counts loop with single GROUP BY; replace 27-query category_counts loop with 2-column GROUP BY; replace N×4 lot P&L queries with batch aggregation |
| `routers/reports.py` | Add `.limit(500)` + default 30-day filter to sales report; push stock aging bracket computation to SQL CASE WHEN |
| `services/control_engine.py` | Cache `AllowedTransitions` dict in memory at startup; reload only on admin change |
| `alembic/versions/YYYYMMDD_composite_indexes.py` | New migration: composite indexes on `device_location_logs(device_id, logged_at)`, `devices(current_stage, sub_category)`, `repair_jobs(device_id, stage, status)` |
| `tests/test_sprint18_unit.py` | Unit tests for all changes |

---

### Task 1: Add Missing Model Indexes

**Files:**
- Modify: `models/device.py`
- Modify: `models/repair.py`
- Modify: `models/dealers.py`
- Modify: `models/crm.py`
- Modify: `models/sales.py`
- Modify: `models/attendance.py`
- Create: `tests/test_sprint18_unit.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sprint18_unit.py
import ast, pathlib

def get_model_source(fname):
    return pathlib.Path(f"models/{fname}").read_text(encoding="utf-8")

def test_device_current_stage_indexed():
    src = get_model_source("device.py")
    # Find current_stage Column definition and check index=True nearby
    assert "current_stage" in src
    # Check index=True appears after current_stage definition
    idx = src.index("current_stage")
    segment = src[idx:idx+200]
    assert "index=True" in segment, "Device.current_stage missing index=True"

def test_repair_job_device_id_indexed():
    src = get_model_source("repair.py")
    assert "index=True" in src[src.index("device_id"):src.index("device_id")+100], \
        "RepairJob.device_id missing index=True"

def test_dealer_call_next_followup_indexed():
    src = get_model_source("dealers.py")
    assert "next_followup_date" in src
    seg = src[src.index("next_followup_date"):src.index("next_followup_date")+150]
    assert "index=True" in seg, "DealerCall.next_followup_date missing index=True"

def test_crm_activity_contact_id_indexed():
    src = get_model_source("crm.py")
    # CRMActivity contact_id
    idx = src.index("class CRMActivity")
    seg = src[idx:idx+1000]
    contact_idx = seg.index("contact_id")
    assert "index=True" in seg[contact_idx:contact_idx+100], \
        "CRMActivity.contact_id missing index=True"
```

Run: `pytest tests/test_sprint18_unit.py -v` — 4 FAIL expected.

- [ ] **Step 2: Add indexes to models/device.py**

Find:
```python
current_stage = Column(Enum(DeviceStage), default=DeviceStage.grn, nullable=False)
```
Replace with:
```python
current_stage = Column(Enum(DeviceStage), default=DeviceStage.grn, nullable=False, index=True)
```

Find `sub_category` Column — add `index=True`.
Find `brand` Column — add `index=True`.
Find `updated_at` Column — add `index=True`.

- [ ] **Step 3: Add indexes to remaining models** (repair.py, dealers.py, crm.py, sales.py, attendance.py)

Apply `index=True` to every column listed in the File Map table above.
Read each file, locate the Column definition, add `index=True`.

- [ ] **Step 4: Run tests**
```
pytest tests/test_sprint18_unit.py -v
```
Expected: 4 PASS.

- [ ] **Step 5: Commit**
```bash
git add models/ tests/test_sprint18_unit.py
git commit -m "perf(db): add index=True to 15+ hot-query columns across all models"
```

---

### Task 2: Composite Index Alembic Migration

**Files:**
- Create: `alembic/versions/YYYYMMDD_add_composite_indexes.py`
- Modify: `tests/test_sprint18_unit.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_sprint18_unit.py`:
```python
def test_composite_index_migration_exists():
    import glob
    migrations = glob.glob("alembic/versions/*composite_indexes*.py")
    assert migrations, "Composite index migration file not found"
    src = open(migrations[0], encoding="utf-8").read()
    assert "device_location_logs" in src, "device_location_logs composite index missing"
    assert "current_stage" in src, "devices (current_stage, sub_category) index missing"
```

- [ ] **Step 2: Create Alembic migration**

```bash
alembic revision --autogenerate -m "add_composite_indexes"
```

Then edit the generated file to add these indexes in `upgrade()`:
```python
def upgrade():
    op.create_index(
        'ix_devices_stage_subcategory',
        'devices', ['current_stage', 'sub_category']
    )
    op.create_index(
        'ix_device_location_logs_device_logged',
        'device_location_logs', ['device_id', 'logged_at']
    )
    op.create_index(
        'ix_repair_jobs_device_stage_status',
        'repair_jobs', ['device_id', 'stage', 'status']
    )
    op.create_index(
        'ix_stage_movements_device_moved',
        'stage_movements', ['device_id', 'moved_at']
    )

def downgrade():
    op.drop_index('ix_devices_stage_subcategory', table_name='devices')
    op.drop_index('ix_device_location_logs_device_logged', table_name='device_location_logs')
    op.drop_index('ix_repair_jobs_device_stage_status', table_name='repair_jobs')
    op.drop_index('ix_stage_movements_device_moved', table_name='stage_movements')
```

- [ ] **Step 3: Run migration**
```bash
alembic upgrade head
```

- [ ] **Step 4: Run tests**
```
pytest tests/test_sprint18_unit.py -v
```
Expected: 5 PASS.

- [ ] **Step 5: Commit**
```bash
git add alembic/versions/ tests/test_sprint18_unit.py
git commit -m "perf(db): composite indexes on device_location_logs, devices, repair_jobs, stage_movements"
```

---

### Task 3: Dashboard Query Optimization

**Files:**
- Modify: `routers/dashboard.py`
- Modify: `tests/test_sprint18_unit.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_sprint18_unit.py`:
```python
def test_dashboard_uses_group_by_for_stage_counts():
    src = open("routers/dashboard.py", encoding="utf-8").read()
    assert "GROUP BY" in src.upper() or "group_by" in src, \
        "dashboard.py stage_counts still uses per-stage loop instead of GROUP BY"

def test_dashboard_lot_pl_uses_batch_queries():
    src = open("routers/dashboard.py", encoding="utf-8").read()
    # The old pattern: 'for lot in lots:' followed by individual queries
    assert "for lot in lots:" not in src, \
        "dashboard.py still uses N+1 lot P&L loop"
```

- [ ] **Step 2: Replace stage_counts loop**

In `routers/dashboard.py`, find the loop that fires one COUNT per DeviceStage.

Replace with:
```python
# Single GROUP BY replaces 17 individual COUNT queries
from sqlalchemy import func, case
stage_result = await db.execute(
    select(Device.current_stage, func.count(Device.id))
    .group_by(Device.current_stage)
)
stage_counts = {row[0].value: row[1] for row in stage_result.fetchall()}
# Ensure all stages present (default to 0)
for stage in DeviceStage:
    stage_counts.setdefault(stage.value, 0)
```

- [ ] **Step 3: Replace category_counts loop**

Replace the 3-category x 9-stage nested loop with:
```python
# Single 2-column GROUP BY replaces ~27 queries
cat_stage_result = await db.execute(
    select(Device.sub_category, Device.current_stage, func.count(Device.id))
    .group_by(Device.sub_category, Device.current_stage)
)
cat_stage_raw = cat_stage_result.fetchall()
category_counts = {}
for sub_cat, stage, cnt in cat_stage_raw:
    if sub_cat not in category_counts:
        category_counts[sub_cat] = {"total": 0}
    category_counts[sub_cat]["total"] += cnt
    category_counts[sub_cat][stage.value] = cnt
```

- [ ] **Step 4: Replace Lot P&L N+1 queries**

Replace the `for lot in lots:` block that fires 4 queries per lot with 4 batch aggregation queries:
```python
from sqlalchemy import func

# Batch query 1: device counts per lot
lot_device_counts = dict((await db.execute(
    select(Device.lot_id, func.count(Device.id)).group_by(Device.lot_id)
)).fetchall())

# Batch query 2: revenue per lot (sold devices)
lot_revenue = dict((await db.execute(
    select(Sale.lot_id, func.sum(Sale.sale_price))
    .where(Sale.lot_id.isnot(None))
    .group_by(Sale.lot_id)
)).fetchall())

# Batch query 3: parts cost per lot
lot_parts_cost = dict((await db.execute(
    select(Device.lot_id, func.sum(SparePartConsumption.total_cost))
    .join(SparePartConsumption, SparePartConsumption.device_id == Device.id)
    .group_by(Device.lot_id)
)).fetchall())

# Batch query 4: sold count per lot
lot_sold_counts = dict((await db.execute(
    select(Device.lot_id, func.count(Device.id))
    .where(Device.current_stage == DeviceStage.sold)
    .group_by(Device.lot_id)
)).fetchall())
```

- [ ] **Step 5: Run tests**
```
pytest tests/test_sprint18_unit.py -v
```
Expected: 7 PASS.

- [ ] **Step 6: Commit**
```bash
git add routers/dashboard.py tests/test_sprint18_unit.py
git commit -m "perf(dashboard): replace 100+ N+1 queries with GROUP BY batch queries"
```

---

### Task 4: Cache AllowedTransitions + Fix Unbounded Queries

**Files:**
- Modify: `services/control_engine.py`
- Modify: `routers/reports.py`
- Modify: `tests/test_sprint18_unit.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_sprint18_unit.py`:
```python
def test_control_engine_has_cache():
    src = open("services/control_engine.py", encoding="utf-8").read()
    assert "_transitions_cache" in src or "lru_cache" in src or "_cache" in src, \
        "control_engine.py does not cache AllowedTransitions"

def test_reports_sales_has_limit():
    src = open("routers/reports.py", encoding="utf-8").read()
    assert ".limit(" in src, "reports.py sales query has no .limit() — unbounded query risk"
```

- [ ] **Step 2: Cache AllowedTransitions**

In `services/control_engine.py`, add a module-level cache:
```python
_transitions_cache: dict | None = None

async def get_transitions(db: AsyncSession) -> dict:
    global _transitions_cache
    if _transitions_cache is not None:
        return _transitions_cache
    result = await db.execute(select(AllowedTransition))
    rows = result.scalars().all()
    _transitions_cache = {(r.from_stage, r.to_stage): r for r in rows}
    return _transitions_cache

def invalidate_transitions_cache():
    """Call this after admin modifies AllowedTransition rows."""
    global _transitions_cache
    _transitions_cache = None
```

Call `invalidate_transitions_cache()` in the stage_control router after any INSERT/UPDATE/DELETE on AllowedTransition.

- [ ] **Step 3: Add limit + date filter to sales report**

In `routers/reports.py`, find the unbounded sales query and add:
```python
from datetime import datetime, timedelta
# Default: last 90 days; override with ?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD
default_from = (datetime.now() - timedelta(days=90)).date()
from_date = request.query_params.get("from_date", str(default_from))
to_date = request.query_params.get("to_date", str(datetime.now().date()))

sales_query = (
    select(Sale)
    .where(Sale.sold_at >= from_date, Sale.sold_at <= to_date)
    .order_by(Sale.sold_at.desc())
    .limit(1000)
)
```

- [ ] **Step 4: Run tests**
```
pytest tests/test_sprint18_unit.py -v
```
Expected: 9 PASS.

- [ ] **Step 5: Commit**
```bash
git add services/control_engine.py routers/reports.py tests/test_sprint18_unit.py
git commit -m "perf: cache AllowedTransitions in memory; add date filter + limit to sales report"
```

---

# Sprint 19 — Smart UX: Auto-Recommendations & Auto-Populate

**Goal:** The app should tell users what to do next. After every key action, show a contextual recommendation — next repair stage, scrap warning, ready-for-QC prompt, dealer follow-up suggestions, CRM stage advances. Auto-populate forms from existing data to eliminate re-entry.

**Architecture:** All logic is server-side (Python, in existing route handlers). No new DB tables. Templates get new conditional blocks for recommendation banners. One new JSON API endpoint for form auto-fill.

---

## File Map

| File | Change |
|---|---|
| `routers/iqc.py` | Post-IQC: auto-set device_price from LotLineItem; compute `recommended_stage` |
| `routers/repair.py` | Post-repair: detect all-jobs-complete -> `suggest_qc=True`; scrap warning banner |
| `routers/qc.py` | Post-QC: auto-set `QCCheck.grade = computed_grade`, sync `Device.grade` |
| `routers/crm_sourcing.py` | Post-lot-link: auto-advance deal to "received"; `suggest_won=True` |
| `routers/sales.py` | Ready-to-sale list: compute `interested_dealers` based on stock x preferred_categories |
| `routers/api.py` (NEW) | JSON endpoints: `/api/lot-line-item/{id}`, `/api/dealers/search`, `/api/device/{id}/next-stages` |
| `templates/iqc/form.html` | Add JS auto-fill on lot_line_item_id change |
| `templates/repair/detail.html` | Add scrap warning banner; add "Move to QC?" suggestion card |
| `templates/sales/ready_list.html` | Add "Interested dealers" recommendation banner |
| `templates/crm/sourcing_detail.html` | Add "Mark as Won?" suggestion after lot link |
| `templates/cosmetic/*.html` | Add "Next step ->" button after each cosmetic stage |
| `tests/test_sprint19_unit.py` | All unit tests |

---

### Task 1: Auto-Populate — IQC Form from LotLineItem

**Files:**
- Modify: `routers/iqc.py`
- Create: `routers/api.py`
- Modify: `templates/iqc/form.html` (or relevant IQC template)
- Create: `tests/test_sprint19_unit.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sprint19_unit.py
def test_api_router_exists():
    import pathlib
    assert pathlib.Path("routers/api.py").exists(), "routers/api.py not created"

def test_api_lot_line_item_endpoint_exists():
    src = open("routers/api.py", encoding="utf-8").read()
    assert "/lot-line-item/" in src or "lot_line_item" in src, \
        "routers/api.py missing lot-line-item JSON endpoint"

def test_iqc_sets_device_price_from_lineitem():
    src = open("routers/iqc.py", encoding="utf-8").read()
    assert "unit_price" in src or "device_price" in src, \
        "iqc.py does not set device_price from LotLineItem"

def test_iqc_form_has_auto_fill_js():
    import glob
    templates = glob.glob("templates/iqc/*.html") + glob.glob("templates/**/*iqc*.html")
    found = False
    for t in templates:
        if "auto" in open(t, encoding="utf-8", errors="ignore").read().lower() or \
           "onchange" in open(t, encoding="utf-8", errors="ignore").read():
            found = True
            break
    assert found, "No IQC template has auto-fill JS (onchange event)"
```

- [ ] **Step 2: Create `routers/api.py` with lot-line-item endpoint**

```python
# routers/api.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db
from models.lot import LotLineItem
from models.dealers import Dealer
from auth.dependencies import get_current_user
from models.user import User

router = APIRouter(prefix="/api", tags=["api"])

@router.get("/lot-line-item/{item_id}")
async def get_lot_line_item(item_id: str, db: AsyncSession = Depends(get_db),
                             current_user: User = Depends(get_current_user)):
    result = await db.execute(select(LotLineItem).where(LotLineItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Line item not found")
    return JSONResponse({
        "brand": item.brand or "",
        "model": item.model or "",
        "cpu": item.cpu or "",
        "generation": str(item.generation or ""),
        "ram_gb": str(item.ram_gb or ""),
        "storage_gb": str(item.storage_gb or ""),
        "storage_type": item.storage_type or "",
        "grade": item.grade or "",
        "unit_price": str(item.unit_price or ""),
    })

@router.get("/dealers/search")
async def search_dealers(q: str = "", db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    result = await db.execute(
        select(Dealer)
        .where(Dealer.business_name.ilike(f"%{q}%"))
        .limit(10)
    )
    dealers = result.scalars().all()
    return JSONResponse([{
        "id": str(d.id), "name": d.business_name,
        "phone": d.phone or "", "state": d.state or "", "city": d.city or ""
    } for d in dealers])

@router.get("/device/{device_id}/next-stages")
async def get_next_stages(device_id: str, db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    from models.stage_control import AllowedTransition
    from models.device import Device
    dev = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")
    transitions = (await db.execute(
        select(AllowedTransition).where(AllowedTransition.from_stage == dev.current_stage.value)
    )).scalars().all()
    return JSONResponse([{"stage": t.to_stage, "label": t.to_stage.replace("_", " ").title()}
                          for t in transitions])
```

Register in `main.py`:
```python
from routers.api import router as api_router
app.include_router(api_router)
```

- [ ] **Step 3: Auto-set device_price in iqc.py**

In the IQC create route, after loading the LotLineItem, add:
```python
if line_item and line_item.unit_price:
    device_price = float(line_item.unit_price)
else:
    # Fallback: lot average = buying_price / qty
    device_price = float(lot.buying_price / lot.qty) if lot and lot.qty else None
# Set on device object before db.add()
device.device_price = device_price
```

- [ ] **Step 4: Add auto-fill JS to IQC form template**

In the IQC form template, after the `lot_line_item_id` select field, add:
```html
<script>
document.getElementById('lot_line_item_id').addEventListener('change', async function() {
    const id = this.value;
    if (!id) return;
    const res = await fetch(`/api/lot-line-item/${id}`);
    if (!res.ok) return;
    const d = await res.json();
    const set = (id, val) => { const el = document.getElementById(id); if(el && val) el.value = val; };
    set('brand', d.brand); set('model', d.model); set('cpu', d.cpu);
    set('generation', d.generation); set('ram_gb', d.ram_gb);
    set('storage_gb', d.storage_gb); set('storage_type', d.storage_type);
    set('grade', d.grade); set('device_price', d.unit_price);
});
</script>
```

- [ ] **Step 5: Run tests**
```
pytest tests/test_sprint19_unit.py -v
```
Expected: 4 PASS.

- [ ] **Step 6: Commit**
```bash
git add routers/api.py routers/iqc.py templates/ main.py tests/test_sprint19_unit.py
git commit -m "feat(smartux): auto-fill IQC form from LotLineItem; add /api JSON endpoints"
```

---

### Task 2: Auto-Recommend Next Stage After Repair / QC

**Files:**
- Modify: `routers/repair.py`
- Modify: `routers/qc.py`
- Modify: `tests/test_sprint19_unit.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_sprint19_unit.py`:
```python
def test_repair_router_has_scrap_warning():
    src = open("routers/repair.py", encoding="utf-8").read()
    assert "scrap_warning" in src or "suggest_qc" in src, \
        "repair.py does not compute scrap_warning or suggest_qc for templates"

def test_qc_router_syncs_grade_to_device():
    src = open("routers/qc.py", encoding="utf-8").read()
    assert "device.grade" in src or "Device.grade" in src, \
        "qc.py does not sync computed_grade to Device.grade"
```

- [ ] **Step 2: Scrap warning + suggest QC in repair.py**

In the repair job GET handler (device repair detail page), after loading the device and repair history:
```python
from services.cost_engine import check_scrap_decision
costing = await get_device_costing(device.id, db)
scrap_check = check_scrap_decision(costing) if costing else {"warning": False}

# Check if all repair jobs are complete -> suggest QC
from models.repair import RepairJob, RepairStatus
open_jobs = await db.execute(
    select(func.count(RepairJob.id))
    .where(RepairJob.device_id == device.id, RepairJob.status != RepairStatus.completed)
)
suggest_qc = open_jobs.scalar() == 0 and device.current_stage.value in ("l1","l2","l3")

# Pass to template
context["scrap_warning"] = scrap_check.get("warning", False)
context["scrap_reason"] = scrap_check.get("reason", "")
context["suggest_qc"] = suggest_qc
```

In the repair detail template, add these conditional banners:
```html
{% if scrap_warning %}
<div class="alert alert-warning border-warning">
  <i class="bi bi-exclamation-triangle-fill"></i>
  <strong>Scrap Warning:</strong> {{ scrap_reason }}
  <a href="/repair/move/form?device_id={{ device.id }}&suggest=scrapped" class="btn btn-sm btn-warning ms-3">Consider Scrapping</a>
</div>
{% endif %}

{% if suggest_qc %}
<div class="alert alert-success border-success">
  <i class="bi bi-check-circle-fill"></i>
  <strong>All repairs complete!</strong> This device is ready for QC inspection.
  <a href="/repair/move/form?device_id={{ device.id }}&suggest=qc_check" class="btn btn-sm btn-success ms-3">Move to QC</a>
</div>
{% endif %}
```

- [ ] **Step 3: Auto-sync Device.grade in qc.py**

In the QC create/update POST handler, after computing `total_score`:
```python
# Auto-assign grade based on score
if total_score >= 90: grade = "A"
elif total_score >= 75: grade = "B"
elif total_score >= 60: grade = "C"
else: grade = "D"

qc_record.grade = grade
device.grade = grade   # Sync to device — was previously only set if form sends it
```

- [ ] **Step 4: Run tests**
```
pytest tests/test_sprint19_unit.py -v
```
Expected: 6 PASS.

- [ ] **Step 5: Commit**
```bash
git add routers/repair.py routers/qc.py templates/ tests/test_sprint19_unit.py
git commit -m "feat(smartux): scrap warning banner; suggest-QC prompt; auto-sync device grade from QC score"
```

---

### Task 3: Auto-Advance CRM + Dealer Interest Recommendations

**Files:**
- Modify: `routers/crm_sourcing.py`
- Modify: `routers/sales.py`
- Modify: `tests/test_sprint19_unit.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_sprint19_unit.py`:
```python
def test_crm_sourcing_auto_advances_on_lot_link():
    src = open("routers/crm_sourcing.py", encoding="utf-8").read()
    assert "received" in src and "linked_lot_id" in src, \
        "crm_sourcing.py does not auto-advance deal to received when lot is linked"

def test_sales_ready_list_computes_interested_dealers():
    src = open("routers/sales.py", encoding="utf-8").read()
    assert "interested_dealers" in src or "preferred_categories" in src, \
        "sales.py ready-to-sale list does not compute interested dealers"
```

- [ ] **Step 2: Auto-advance CRM sourcing deal when lot is linked**

In `crm_sourcing.py`, in the route that sets `deal.linked_lot_id`, after setting the FK:
```python
deal.linked_lot_id = lot_id
# Auto-advance stage to 'received' when stock arrives
if deal.stage not in ("received", "won", "lost"):
    deal.stage = "received"
    suggest_won = True
else:
    suggest_won = False
await db.commit()
# Redirect to deal detail with suggestion flag
return RedirectResponse(
    url=f"/crm/sourcing/{deal_id}?suggest_won=1" if suggest_won else f"/crm/sourcing/{deal_id}",
    status_code=302
)
```

In `crm/sourcing_detail.html`, add:
```html
{% if request.query_params.get('suggest_won') %}
<div class="alert alert-success">
  <i class="bi bi-trophy-fill"></i>
  Stock has been received. <strong>Mark this deal as WON?</strong>
  <form method="post" action="/crm/sourcing/{{ deal.id }}/advance" class="d-inline ms-2">
    <input type="hidden" name="stage" value="won">
    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
    <button class="btn btn-success btn-sm">Mark WON</button>
  </form>
</div>
{% endif %}
```

- [ ] **Step 3: Interested dealers banner on Ready-to-Sale list**

In `routers/sales.py` ready_list route, after loading ready devices:
```python
# Find dealers interested in the current ready-to-sell stock categories
from models.dealers import Dealer
ready_categories = {d.sub_category for d in ready_devices if d.sub_category}

interested_dealers = []
if ready_categories:
    all_dealers = (await db.execute(
        select(Dealer).where(Dealer.preferred_categories.isnot(None))
    )).scalars().all()
    for dealer in all_dealers:
        prefs = dealer.preferred_categories or ""
        if any(cat.lower() in prefs.lower() for cat in ready_categories):
            interested_dealers.append(dealer)
    interested_dealers = interested_dealers[:5]  # top 5

context["interested_dealers"] = interested_dealers
```

In `templates/sales/ready_list.html` (or equivalent), add the banner:
```html
{% if interested_dealers %}
<div class="alert alert-info d-flex align-items-center">
  <i class="bi bi-people-fill me-2"></i>
  <div>
    <strong>{{ interested_dealers|length }} dealer(s) may be interested</strong> in current ready stock:
    {% for d in interested_dealers %}
    <a href="/dealers/{{ d.id }}" class="badge bg-primary text-decoration-none me-1">{{ d.business_name }}</a>
    {% endfor %}
    <a href="/whatsapp" class="btn btn-sm btn-outline-success ms-2">
      <i class="bi bi-whatsapp"></i> Notify via WhatsApp
    </a>
  </div>
</div>
{% endif %}
```

- [ ] **Step 4: Run tests**
```
pytest tests/test_sprint19_unit.py -v
```
Expected: 8 PASS.

- [ ] **Step 5: Commit**
```bash
git add routers/crm_sourcing.py routers/sales.py templates/ tests/test_sprint19_unit.py
git commit -m "feat(smartux): auto-advance CRM sourcing on lot link; interested dealers banner on ready list"
```

---

# Sprint 20 — UI Structure: Navigation, Quick Access & Barcode UX

**Goal:** Reduce click depth to reach every key action from 3+ clicks to 1-2. Unify the follow-up experience. Add barcode scan shortcut on repair/IQC/sales pages. Show outstanding badge on dealer list.

**Architecture:** Template-only changes (no new routes needed). One new partial template for the "My Today Follow-ups" widget. Dashboard restructured into role-based sections.

---

## File Map

| File | Change |
|---|---|
| `templates/base.html` | Collapse sidebar into accordion sections; add "Today's Follow-ups" badge count in nav |
| `templates/dashboard.html` | Restructure into 3 role-based tab panels: Operations / Finance / Inventory |
| `templates/dealers/list.html` | Add outstanding amount badge on each dealer row |
| `templates/repair/l1.html` (and l2, l3) | Add barcode scan quick-search at top of list |
| `templates/iqc/list.html` | Add barcode scan quick-search at top of list |
| `templates/sales/list.html` | Add barcode scan quick-search + dealer lookup auto-fill |
| `templates/shared/followups_widget.html` (NEW) | Combined follow-up widget: dealer calls + CRM activities due today |
| `routers/dashboard.py` | Pass today's follow-up count to all dashboard contexts |
| `tests/test_sprint20_unit.py` | Unit tests |

---

### Task 1: Barcode Scan Quick-Search on Repair/IQC/Sales Lists

- [ ] **Step 1: Write failing tests**
```python
# tests/test_sprint20_unit.py
def test_repair_list_has_barcode_scan_input():
    import glob
    templates = glob.glob("templates/repair/*.html")
    found_any = False
    for t in templates:
        src = open(t, encoding="utf-8", errors="ignore").read()
        if "barcode" in src.lower() and ("scan" in src.lower() or "quick" in src.lower()):
            found_any = True
    assert found_any, "No repair template has a barcode scan quick-search input"

def test_dealer_list_shows_outstanding_badge():
    import glob
    templates = glob.glob("templates/dealers/list.html")
    for t in templates:
        src = open(t, encoding="utf-8", errors="ignore").read()
        assert "outstanding" in src.lower(), f"{t} does not show outstanding badge"
```

- [ ] **Step 2: Add barcode scan input to repair list templates (l1, l2, l3)**

At the TOP of each repair list template, before the device table, add:
```html
<!-- Barcode Quick Search -->
<div class="input-group mb-3" style="max-width:400px">
  <span class="input-group-text bg-primary text-white"><i class="bi bi-upc-scan"></i></span>
  <input type="text" id="barcodeScan" class="form-control form-control-lg"
         placeholder="Scan or type barcode to jump to device..." autofocus>
</div>
<script>
document.getElementById('barcodeScan').addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && this.value.trim()) {
    window.location.href = '/devices?barcode=' + encodeURIComponent(this.value.trim());
  }
});
// Auto-submit after 800ms of no typing (for hardware scanners that send all chars rapidly)
let scanTimer;
document.getElementById('barcodeScan').addEventListener('input', function() {
  clearTimeout(scanTimer);
  scanTimer = setTimeout(() => {
    if (this.value.length >= 8) {
      window.location.href = '/devices?barcode=' + encodeURIComponent(this.value.trim());
    }
  }, 800);
});
</script>
```

Apply same pattern to IQC list, QC list, and Sales list templates.

- [ ] **Step 3: Add outstanding badge to dealer list**

In `templates/dealers/list.html`, in the table row for each dealer, find the row template and add:
```html
<!-- Already computed as outstanding_map[dealer.id] in the route context -->
{% set outstanding = outstanding_map.get(dealer.id, 0) %}
{% if outstanding > 0 %}
<span class="badge {% if outstanding > 50000 %}bg-danger{% elif outstanding > 10000 %}bg-warning text-dark{% else %}bg-secondary{% endif %} ms-1">
  Rs. {{ "{:,.0f}".format(outstanding) }}
</span>
{% endif %}
```

Note: The dealer list route (`routers/dealers.py`) must also be updated to compute `outstanding_map` — a dict of `{dealer_id: total_outstanding_amount}` — and pass it to the template context. Use a single batch query:
```python
from sqlalchemy import func
outstanding_result = await db.execute(
    select(DealerOrder.dealer_id, func.sum(DealerOrder.outstanding_amount))
    .where(DealerOrder.outstanding_amount > 0)
    .group_by(DealerOrder.dealer_id)
)
outstanding_map = {str(row[0]): float(row[1]) for row in outstanding_result.fetchall()}
context["outstanding_map"] = outstanding_map
```

- [ ] **Step 4: Run tests**
```
pytest tests/test_sprint20_unit.py -v
```
Expected: 2 PASS.

- [ ] **Step 5: Commit**
```bash
git add templates/ routers/dealers.py tests/test_sprint20_unit.py
git commit -m "feat(ui): barcode scan quick-search on repair/IQC/sales lists; outstanding badge on dealer list"
```

---

### Task 2: Dashboard Role-Based Tab Panels

- [ ] **Step 1: Write failing tests**

Append to `tests/test_sprint20_unit.py`:
```python
def test_dashboard_has_role_based_sections():
    src = open("templates/dashboard.html", encoding="utf-8").read()
    assert "nav-tabs" in src or "tab-pane" in src or "role" in src.lower(), \
        "dashboard.html does not have role-based tab panels or sections"
```

- [ ] **Step 2: Restructure dashboard.html into tabs**

Wrap the existing dashboard sections in Bootstrap tab panels:
```html
<!-- Role-based dashboard tabs (visible tabs vary by role) -->
<ul class="nav nav-tabs mb-4" id="dashTabs">
  {% if role in ('admin','inventory_manager') %}
  <li class="nav-item"><a class="nav-link active" data-bs-toggle="tab" href="#operations">Operations</a></li>
  {% endif %}
  {% if role in ('admin','inventory_manager','sales') %}
  <li class="nav-item"><a class="nav-link {% if role == 'sales' %}active{% endif %}" data-bs-toggle="tab" href="#finance">Finance</a></li>
  {% endif %}
  {% if role == 'admin' %}
  <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#inventory">Inventory P&L</a></li>
  {% endif %}
</ul>
<div class="tab-content">
  <div class="tab-pane fade show active" id="operations">
    <!-- Stage pipeline, repair queue, IQC queue, QC queue -->
    {{ existing_operations_section }}
  </div>
  <div class="tab-pane fade {% if role == 'sales' %}show active{% endif %}" id="finance">
    <!-- Dealer outstanding, receivables, receipts KPI -->
    {{ existing_finance_section }}
  </div>
  <div class="tab-pane fade" id="inventory">
    <!-- Lot P&L table — admin only -->
    {{ existing_lot_pl_section }}
  </div>
</div>
```

- [ ] **Step 3: Add Today's Follow-ups count to dashboard context**

In `routers/dashboard.py`, add to the dashboard data query:
```python
from datetime import date
today = date.today()

# Follow-ups due today: dealer calls + CRM activities
dealer_followups_today = (await db.execute(
    select(func.count(DealerCall.id))
    .where(DealerCall.next_followup_date == today, DealerCall.status != "done")
)).scalar() or 0

crm_followups_today = (await db.execute(
    select(func.count(CRMActivity.id))
    .where(CRMActivity.next_followup == today, CRMActivity.followup_done == False)
)).scalar() or 0

context["followup_count_today"] = dealer_followups_today + crm_followups_today
```

In `templates/base.html`, add a badge in the sidebar/nav link for follow-ups:
```html
<a href="/followups" class="nav-link">
  Follow-ups
  {% if followup_count_today and followup_count_today > 0 %}
  <span class="badge bg-danger ms-1">{{ followup_count_today }}</span>
  {% endif %}
</a>
```

- [ ] **Step 4: Create Today's Follow-ups widget partial**

Create `templates/shared/followups_widget.html`:
```html
<!-- Shared partial: include on dashboard with {% include 'shared/followups_widget.html' %} -->
<div class="card border-warning mb-3">
  <div class="card-header bg-warning text-dark fw-bold">
    <i class="bi bi-bell-fill me-1"></i> Today's Follow-ups
    <span class="badge bg-dark ms-2">{{ dealer_followups|length + crm_followups|length }}</span>
  </div>
  <div class="card-body p-0">
    <ul class="list-group list-group-flush">
      {% for call in dealer_followups %}
      <li class="list-group-item d-flex justify-content-between align-items-center">
        <div>
          <span class="badge bg-secondary me-1">Dealer</span>
          <a href="/dealers/{{ call.dealer_id }}">{{ call.dealer.business_name }}</a>
          <small class="text-muted ms-2">{{ call.purpose or 'Follow-up' }}</small>
        </div>
        <a href="/dealers/calls/{{ call.id }}/done" class="btn btn-sm btn-outline-success">Done</a>
      </li>
      {% endfor %}
      {% for activity in crm_followups %}
      <li class="list-group-item d-flex justify-content-between align-items-center">
        <div>
          <span class="badge bg-primary me-1">CRM</span>
          <a href="/crm/activities/{{ activity.id }}">{{ activity.subject or 'Activity' }}</a>
          <small class="text-muted ms-2">{{ activity.activity_type or '' }}</small>
        </div>
        <a href="/crm/activities/{{ activity.id }}/done" class="btn btn-sm btn-outline-success">Done</a>
      </li>
      {% endfor %}
      {% if not dealer_followups and not crm_followups %}
      <li class="list-group-item text-muted text-center py-3">
        <i class="bi bi-check2-all me-1"></i> No follow-ups due today
      </li>
      {% endif %}
    </ul>
  </div>
</div>
```

Pass `dealer_followups` and `crm_followups` lists (full ORM objects) from `routers/dashboard.py` alongside the count.

- [ ] **Step 5: Run tests**
```
pytest tests/test_sprint20_unit.py -v
```
Expected: 3 PASS.

- [ ] **Step 6: Commit**
```bash
git add templates/ routers/dashboard.py tests/test_sprint20_unit.py
git commit -m "feat(ui): role-based tab panels on dashboard; today follow-ups badge + widget"
```

---

## Self-Review

### Spec Coverage

| Requirement | Sprint | Task | Status |
|---|---|---|---|
| Missing DB indexes (15+ columns) | 18 | 1 | Planned |
| Composite indexes on hot paths | 18 | 2 | Planned |
| Dashboard N+1 queries -> GROUP BY | 18 | 3 | Planned |
| AllowedTransitions cache | 18 | 4 | Planned |
| Unbounded sales query limit | 18 | 4 | Planned |
| Auto-fill IQC from LotLineItem | 19 | 1 | Planned |
| Auto-set device_price at IQC | 19 | 1 | Planned |
| Scrap warning banner on repair | 19 | 2 | Planned |
| Suggest-QC after all jobs done | 19 | 2 | Planned |
| Auto-sync Device.grade from QC | 19 | 2 | Planned |
| Auto-advance CRM on lot link | 19 | 3 | Planned |
| Interested dealers on ready list | 19 | 3 | Planned |
| Barcode scan on repair/IQC/sales | 20 | 1 | Planned |
| Outstanding badge on dealer list | 20 | 1 | Planned |
| Dashboard role-based tab panels | 20 | 2 | Planned |
| Today's Follow-ups badge + widget | 20 | 2 | Planned |

### Expected Impact
- **Sprint 18**: Dashboard load time: 3-8s -> under 500ms. All list pages 2-3x faster. Query count on dashboard from ~100+ to under 10.
- **Sprint 19**: Eliminates ~60% of manual data re-entry. Reduces missed scrap decisions and incorrect grades. CRM stage transitions become automatic on key events.
- **Sprint 20**: Reduces barcode entry errors. Outstanding visibility stops missed dealer follow-ups. Dashboard usable in role-scoped view without scrolling. Follow-up badge provides daily action prompt without needing to navigate to calendar.

### Phase Gates Before Execution
- All RED audit findings from 2026-04-26 audit must be closed before Sprint 18 begins.
- Sprint 18 migration must be tested against a staging DB backup before applying to production.
- Sprint 19 API endpoints must pass auth/RBAC review — all three endpoints use `get_current_user` dependency.
- Sprint 20 is template-only and lowest risk; can be executed in parallel with Sprint 19 testing if bandwidth allows.
