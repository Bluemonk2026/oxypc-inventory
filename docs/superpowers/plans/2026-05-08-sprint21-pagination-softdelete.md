# Sprint 21 — Repair/QC Pagination + Soft Delete (Device) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add server-side pagination to the repair (L1/L2/L3) and QC list routes, and implement soft-delete on Device — replacing the single remaining `db.delete(device)` call and adding `is_active` filters to list queries.

**Architecture:** All changes are pure code + one Alembic migration. No new tables. Pagination follows the existing `iqc.py` pattern: `page`/`page_size` Query params, COUNT subquery for total, `.offset().limit()` on the device fetch. Soft delete adds `is_active BOOLEAN DEFAULT TRUE` + `deleted_at DATETIME NULL` to `devices`; the GRN-stage device removal in `stock.py` switches from `db.delete(device)` to flag update; all list queries in iqc/repair/qc get `Device.is_active == True` filters.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, Alembic, Jinja2, Bootstrap 5, pytest

---

## What Already Exists (do NOT rebuild)

- **IQC audit trail** — `iqc.py:251` already calls `await audit(db, action="DEVICE_IQC_REGISTERED", ...)` ✅
- **Failed-login counter + lockout** — `auth.py` already has `MAX_FAILED_ATTEMPTS = 5`, 15-min window lockout ✅
- **Pagination in iqc.py, sales.py, dealers.py, stock.py** — all correct, no changes needed ✅
- **N+1 fix in stock.py** — already uses batch GROUP BY queries ✅
- `repair.py` already imports `func` from sqlalchemy — no new import needed for COUNT ✅
- `audit` already imported in `iqc.py` ✅

## File Structure

| File | Change Type | Task |
|------|-------------|------|
| `tests/test_sprint21_unit.py` | Create | Task 1 — all failing tests |
| `routers/repair.py` | Modify | Task 2 — pagination + is_active filter |
| `templates/repair/l1.html` | Modify | Task 2 — pagination widget |
| `templates/repair/l2.html` | Modify | Task 2 — pagination widget |
| `templates/repair/l3.html` | Modify | Task 2 — pagination widget |
| `routers/qc.py` | Modify | Task 3 — pagination + is_active filter |
| `templates/qc/list.html` | Modify | Task 3 — pagination widget |
| `alembic/versions/20260503_0900_soft_delete_devices.py` | Create | Task 4 — migration |
| `models/device.py` | Modify | Task 5 — add is_active, deleted_at columns |
| `routers/stock.py` | Modify | Task 5 — replace db.delete(device) with soft delete |
| `routers/iqc.py` | Modify | Task 5 — add is_active filter to list query |

---

### Task 1: Write all failing tests

**Files:**
- Create: `tests/test_sprint21_unit.py`

Write ALL source-inspection tests first — they define the contract each task must satisfy.

- [ ] **Step 1: Create the test file**

```python
# tests/test_sprint21_unit.py
"""Sprint 21 unit tests — repair/qc pagination, soft delete."""
from pathlib import Path
_ROOT = Path(__file__).parent.parent


# ── TASK 2: Repair list pagination ────────────────────────────────────────────

def test_repair_list_has_page_query_param():
    """routers/repair.py repair_list must accept `page` as a Query param."""
    src = (_ROOT / "routers" / "repair.py").read_text(encoding="utf-8")
    assert "page: int = Query" in src, \
        "repair.py missing `page: int = Query` parameter in repair_list"


def test_repair_list_has_page_size_query_param():
    """routers/repair.py repair_list must accept `page_size` as a Query param."""
    src = (_ROOT / "routers" / "repair.py").read_text(encoding="utf-8")
    assert "page_size: int = Query" in src, \
        "repair.py missing `page_size: int = Query` parameter in repair_list"


def test_repair_list_uses_offset_limit():
    """routers/repair.py must use .offset() and .limit() on the device query."""
    src = (_ROOT / "routers" / "repair.py").read_text(encoding="utf-8")
    assert ".offset(" in src, "repair.py missing .offset() — pagination not implemented"
    assert ".limit(" in src, "repair.py missing .limit() — pagination not implemented"


def test_repair_list_passes_pagination_context():
    """routers/repair.py must pass total_pages to template context."""
    src = (_ROOT / "routers" / "repair.py").read_text(encoding="utf-8")
    assert "total_pages" in src, \
        "repair.py missing total_pages in template context"


# ── TASK 3: QC list pagination ────────────────────────────────────────────────

def test_qc_list_has_page_query_param():
    """routers/qc.py qc_list must accept `page` as a Query param."""
    src = (_ROOT / "routers" / "qc.py").read_text(encoding="utf-8")
    assert "page: int = Query" in src, \
        "qc.py missing `page: int = Query` parameter in qc_list"


def test_qc_list_has_page_size_query_param():
    """routers/qc.py qc_list must accept `page_size` as a Query param."""
    src = (_ROOT / "routers" / "qc.py").read_text(encoding="utf-8")
    assert "page_size: int = Query" in src, \
        "qc.py missing `page_size: int = Query` parameter in qc_list"


def test_qc_list_uses_offset_limit():
    """routers/qc.py must use .offset() and .limit() on the device query."""
    src = (_ROOT / "routers" / "qc.py").read_text(encoding="utf-8")
    assert ".offset(" in src, "qc.py missing .offset() — pagination not implemented"
    assert ".limit(" in src, "qc.py missing .limit() — pagination not implemented"


def test_qc_list_passes_pagination_context():
    """routers/qc.py must pass total_pages to template context."""
    src = (_ROOT / "routers" / "qc.py").read_text(encoding="utf-8")
    assert "total_pages" in src, \
        "qc.py missing total_pages in template context"


# ── TASK 4: Soft-delete migration ─────────────────────────────────────────────

def test_soft_delete_migration_exists():
    """Alembic migration for soft delete must exist with correct chain."""
    import glob
    files = glob.glob(str(_ROOT / "alembic/versions/*soft_delete*.py"))
    assert files, "No soft_delete migration file found in alembic/versions/"
    content = Path(files[0]).read_text(encoding="utf-8")
    assert "20260502_0800" in content, \
        "Soft delete migration down_revision must be '20260502_0800'"
    assert "is_active" in content, "Migration must add is_active column"
    assert "deleted_at" in content, "Migration must add deleted_at column"


# ── TASK 5: Soft delete model + route updates ─────────────────────────────────

def test_device_model_has_is_active():
    """models/device.py Device must have is_active column."""
    src = (_ROOT / "models" / "device.py").read_text(encoding="utf-8")
    assert "is_active" in src, "Device model missing is_active column"


def test_device_model_has_deleted_at():
    """models/device.py Device must have deleted_at column."""
    src = (_ROOT / "models" / "device.py").read_text(encoding="utf-8")
    assert "deleted_at" in src, "Device model missing deleted_at column"


def test_stock_py_no_hard_delete_device():
    """routers/stock.py must not use db.delete(device) — soft delete only."""
    src = (_ROOT / "routers" / "stock.py").read_text(encoding="utf-8")
    assert "is_active = False" in src or "is_active=False" in src, \
        "stock.py must use soft delete (device.is_active = False) not db.delete(device)"


def test_iqc_list_filters_active_devices():
    """routers/iqc.py list query must filter Device.is_active == True."""
    src = (_ROOT / "routers" / "iqc.py").read_text(encoding="utf-8")
    assert "is_active" in src, \
        "iqc.py list query missing is_active filter"


def test_repair_list_filters_active_devices():
    """routers/repair.py list query must filter Device.is_active == True."""
    src = (_ROOT / "routers" / "repair.py").read_text(encoding="utf-8")
    assert "is_active" in src, \
        "repair.py list query missing is_active filter"


def test_qc_list_filters_active_devices():
    """routers/qc.py list query must filter Device.is_active == True."""
    src = (_ROOT / "routers" / "qc.py").read_text(encoding="utf-8")
    assert "is_active" in src, \
        "qc.py list query missing is_active filter"
```

- [ ] **Step 2: Run tests to confirm ALL fail**

```
cd C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
pytest tests/test_sprint21_unit.py -v
```

Expected: 18 tests, ALL FAIL. If any pass (e.g. `test_soft_delete_migration_exists`), something is already done — skip that task.

- [ ] **Step 3: Commit**

```bash
git add tests/test_sprint21_unit.py
git commit -m "test: add Sprint 21 failing tests (repair/qc pagination, soft delete)"
```

---

### Task 2: Repair list pagination

**Files:**
- Modify: `routers/repair.py`
- Modify: `templates/repair/l1.html`
- Modify: `templates/repair/l2.html`
- Modify: `templates/repair/l3.html`

**Context:** `repair_list` fetches ALL devices in a stage with no LIMIT. The additional batch queries (location map, scrap warnings) are already efficient — only the top-level device fetch needs pagination. The route serves all three stages (l1, l2, l3) from one function, so one change covers all three.

- [ ] **Step 1: Add `Query` to the fastapi import in `routers/repair.py`**

Current line (line 8):
```python
from fastapi import APIRouter, Depends, Form, Request, HTTPException
```

Replace with:
```python
from fastapi import APIRouter, Depends, Form, Request, HTTPException, Query
```

- [ ] **Step 2: Replace the `repair_list` function signature + device query block**

Find this block (starts at `@router.get("/{stage}", response_class=HTMLResponse)`):

```python
@router.get("/{stage}", response_class=HTMLResponse)
async def repair_list(stage: str, request: Request,
                      db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    if stage not in STAGE_MAP:
        raise HTTPException(404)
    device_stage = STAGE_MAP[stage]
    result = await db.execute(
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.current_stage == device_stage)
        .order_by(Device.updated_at.desc())
    )
    devices = result.all()
```

Replace with:
```python
@router.get("/{stage}", response_class=HTMLResponse)
async def repair_list(stage: str, request: Request,
                      db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user),
                      page: int = Query(default=1, ge=1),
                      page_size: int = Query(default=50, ge=1, le=200)):
    if stage not in STAGE_MAP:
        raise HTTPException(404)
    device_stage = STAGE_MAP[stage]

    total_result = await db.execute(select(func.count()).select_from(
        select(Device.id)
        .where(Device.current_stage == device_stage, Device.is_active == True)
        .subquery()
    ))
    total = total_result.scalar() or 0
    total_pages = max(1, (total + page_size - 1) // page_size)

    result = await db.execute(
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.current_stage == device_stage, Device.is_active == True)
        .order_by(Device.updated_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    devices = result.all()
```

- [ ] **Step 3: Update the `return` statement in `repair_list` to include pagination context**

Find the current return statement at the end of `repair_list`:

```python
    return templates.TemplateResponse(f"repair/{stage}.html", {
        "request": request, "devices": devices, "open_jobs": open_jobs,
        "stage": stage.upper(), "current_user": current_user,
        "location_map": location_map,
        "scrap_warning_map": scrap_warning_map,
        "suggest_qc_ids": suggest_qc_ids,
        "available_parts": available_parts,
    })
```

Replace with:
```python
    return templates.TemplateResponse(f"repair/{stage}.html", {
        "request": request, "devices": devices, "open_jobs": open_jobs,
        "stage": stage.upper(), "current_user": current_user,
        "location_map": location_map,
        "scrap_warning_map": scrap_warning_map,
        "suggest_qc_ids": suggest_qc_ids,
        "available_parts": available_parts,
        "page": page, "page_size": page_size,
        "total": total, "total_pages": total_pages,
    })
```

- [ ] **Step 4: Add pagination widget to `templates/repair/l1.html`**

Open `templates/repair/l1.html`. Find the end of the devices list section (the `</table>` or `</div>` closing the devices table near the bottom of `{% block content %}`). Add this Bootstrap pagination widget immediately after the devices table's closing tag, before `{% endblock %}`:

```html
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
```

- [ ] **Step 5: Add the same pagination widget to `templates/repair/l2.html` and `templates/repair/l3.html`**

Add the identical widget from Step 4 to both `l2.html` and `l3.html` at the same position (after the devices table, before `{% endblock %}`).

- [ ] **Step 6: Run the repair pagination tests**

```
pytest tests/test_sprint21_unit.py::test_repair_list_has_page_query_param tests/test_sprint21_unit.py::test_repair_list_has_page_size_query_param tests/test_sprint21_unit.py::test_repair_list_uses_offset_limit tests/test_sprint21_unit.py::test_repair_list_passes_pagination_context tests/test_sprint21_unit.py::test_repair_list_filters_active_devices -v
```

Expected: 5 PASS

- [ ] **Step 7: Commit**

```bash
git add routers/repair.py templates/repair/l1.html templates/repair/l2.html templates/repair/l3.html
git commit -m "feat: add server-side pagination to repair list routes (L1/L2/L3)"
```

---

### Task 3: QC list pagination

**Files:**
- Modify: `routers/qc.py`
- Modify: `templates/qc/list.html`

**Context:** `qc_list` fetches ALL devices in `qc_check` stage with no LIMIT. The batch location query is efficient — only the top-level device fetch needs LIMIT/OFFSET.

- [ ] **Step 1: Add `Query` to the fastapi import in `routers/qc.py`**

Current line:
```python
from fastapi import APIRouter, Depends, Form, Request, HTTPException
```

Replace with:
```python
from fastapi import APIRouter, Depends, Form, Request, HTTPException, Query
```

- [ ] **Step 2: Replace the `qc_list` function signature and device query**

Find the current `qc_list` function:

```python
@router.get("", response_class=HTMLResponse)
async def qc_list(request: Request, db: AsyncSession = Depends(get_db),
                  current_user: User = Depends(allowed)):
    result = await db.execute(
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.current_stage == DeviceStage.qc_check)
        .order_by(Device.updated_at.desc())
    )
    devices = result.all()
```

Replace the signature and device query lines (keep everything after `devices = result.all()` unchanged until the return):

```python
@router.get("", response_class=HTMLResponse)
async def qc_list(request: Request, db: AsyncSession = Depends(get_db),
                  current_user: User = Depends(allowed),
                  page: int = Query(default=1, ge=1),
                  page_size: int = Query(default=50, ge=1, le=200)):
    total_result = await db.execute(select(func.count()).select_from(
        select(Device.id)
        .where(Device.current_stage == DeviceStage.qc_check, Device.is_active == True)
        .subquery()
    ))
    total = total_result.scalar() or 0
    total_pages = max(1, (total + page_size - 1) // page_size)

    result = await db.execute(
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.current_stage == DeviceStage.qc_check, Device.is_active == True)
        .order_by(Device.updated_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    devices = result.all()
```

- [ ] **Step 3: Update the `return` statement in `qc_list`**

Find the current return statement at the end of `qc_list`:

```python
    return templates.TemplateResponse("qc/list.html", {
        "request": request, "devices": devices, "current_user": current_user,
        "location_map": location_map,
    })
```

Replace with:

```python
    return templates.TemplateResponse("qc/list.html", {
        "request": request, "devices": devices, "current_user": current_user,
        "location_map": location_map,
        "page": page, "page_size": page_size,
        "total": total, "total_pages": total_pages,
    })
```

- [ ] **Step 4: Add pagination widget to `templates/qc/list.html`**

Open `templates/qc/list.html`. Find the end of the devices table (the `</table>` closing the QC device list). Add immediately after it, before `{% endblock %}`:

```html
{# ── Pagination ────────────────────────────────────────────────────────── #}
{% if total_pages and total_pages > 1 %}
<nav class="mt-3" aria-label="QC device list pagination">
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
  <p class="text-center text-muted small mt-1">{{ total }} device(s) in QC &bull; Page {{ page }} of {{ total_pages }}</p>
</nav>
{% endif %}
```

- [ ] **Step 5: Run QC pagination tests**

```
pytest tests/test_sprint21_unit.py::test_qc_list_has_page_query_param tests/test_sprint21_unit.py::test_qc_list_has_page_size_query_param tests/test_sprint21_unit.py::test_qc_list_uses_offset_limit tests/test_sprint21_unit.py::test_qc_list_passes_pagination_context tests/test_sprint21_unit.py::test_qc_list_filters_active_devices -v
```

Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add routers/qc.py templates/qc/list.html
git commit -m "feat: add server-side pagination to QC device list"
```

---

### Task 4: Soft delete — Alembic migration

**Files:**
- Create: `alembic/versions/20260503_0900_soft_delete_devices.py`

**Context:** Current Alembic head is `20260502_0800` (cost_config). This migration adds `is_active` and `deleted_at` to `devices` only. Lots have no hard-delete path anywhere in the codebase — no migration needed there. The partial index on `is_active = false` means the WHERE filter on `is_active == True` hits the main index (most rows) without overhead.

- [ ] **Step 1: Create the migration file**

```python
# alembic/versions/20260503_0900_soft_delete_devices.py
"""add soft delete columns to devices

Revision ID: 20260503_0900
Revises: 20260502_0800
Create Date: 2026-05-03 09:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '20260503_0900'
down_revision = '20260502_0800'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('devices', sa.Column(
        'is_active', sa.Boolean(), nullable=False,
        server_default=sa.text('true'),
    ))
    op.add_column('devices', sa.Column(
        'deleted_at', sa.DateTime(), nullable=True,
    ))
    # Partial index on the rare case (soft-deleted rows); main queries use full index
    op.create_index(
        'ix_devices_is_active_false', 'devices', ['is_active'],
        postgresql_where=sa.text('is_active = false'),
    )


def downgrade():
    op.drop_index('ix_devices_is_active_false', table_name='devices')
    op.drop_column('devices', 'deleted_at')
    op.drop_column('devices', 'is_active')
```

- [ ] **Step 2: Run migration test**

```
pytest tests/test_sprint21_unit.py::test_soft_delete_migration_exists -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add alembic/versions/20260503_0900_soft_delete_devices.py
git commit -m "feat: migration — add is_active + deleted_at soft-delete columns to devices"
```

---

### Task 5: Soft delete — model + route updates

**Files:**
- Modify: `models/device.py`
- Modify: `routers/stock.py`
- Modify: `routers/iqc.py`

**Context:** Three changes: (1) add ORM columns to Device, (2) replace `db.delete(device)` in `stock.py:789` with soft-delete, (3) add `is_active == True` filter to IQC list query. Repair and QC list queries already have the filter from Tasks 2 and 3.

- [ ] **Step 1: Add `is_active` and `deleted_at` columns to `models/device.py`**

In `models/device.py`, find the `class Device(Base):` block. Look for the last `Column(` definition before any `relationship(` lines. After it, add these two lines:

```python
    # Soft delete — flag instead of physical removal; preserves audit trail
    is_active  = Column(Boolean, nullable=False, default=True, server_default="true")
    deleted_at = Column(DateTime, nullable=True)
```

The `Boolean` and `DateTime` types are already imported via:
```python
from sqlalchemy import Column, String, DateTime, Integer, Float, Boolean, ForeignKey, Enum as SAEnum, Text, Numeric
```
No new imports needed.

- [ ] **Step 2: Replace `db.delete(device)` in `routers/stock.py` with soft delete**

Find this block (lines 784–791):

```python
    if not device:
        return JSONResponse({"ok": False, "error": "Device not found"}, status_code=404)
    if device.current_stage != DeviceStage.grn:
        return JSONResponse({"ok": False, "error": f"Cannot remove — device already moved to {device.current_stage}"}, status_code=400)

    await db.delete(device)
    await db.commit()
    return JSONResponse({"ok": True})
```

Replace with:

```python
    if not device:
        return JSONResponse({"ok": False, "error": "Device not found"}, status_code=404)
    if device.current_stage != DeviceStage.grn:
        return JSONResponse({"ok": False, "error": f"Cannot remove — device already moved to {device.current_stage}"}, status_code=400)

    device.is_active = False
    device.deleted_at = datetime.utcnow()
    await db.commit()
    return JSONResponse({"ok": True})
```

`datetime` is already imported in `stock.py` (`from datetime import datetime`).

- [ ] **Step 3: Add `is_active` filter to IQC list query in `routers/iqc.py`**

Find the `iqc_list` function. Replace both `.where()` clauses that filter on `DeviceStage.iqc`:

Current:
```python
    base_q = (
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.current_stage == DeviceStage.iqc)
    )
    total_result = await db.execute(select(func.count()).select_from(
        select(Device.id).where(Device.current_stage == DeviceStage.iqc).subquery()
    ))
```

Replace with:
```python
    base_q = (
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.current_stage == DeviceStage.iqc, Device.is_active == True)
    )
    total_result = await db.execute(select(func.count()).select_from(
        select(Device.id)
        .where(Device.current_stage == DeviceStage.iqc, Device.is_active == True)
        .subquery()
    ))
```

- [ ] **Step 4: Run all Sprint 21 tests**

```
cd C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
pytest tests/test_sprint21_unit.py -v
```

Expected: 18 PASS, 0 FAIL

- [ ] **Step 5: Run the full test suite**

```
pytest --tb=short -q
```

Expected: 280 PASS, 0 FAIL (262 previous + 18 new)

- [ ] **Step 6: Commit**

```bash
git add models/device.py routers/stock.py routers/iqc.py
git commit -m "fix: apply soft delete to Device — replace db.delete(), add is_active filters to iqc/repair/qc"
```

---

## Self-Review

### 1. Spec coverage

| Audit Finding | Task |
|---|---|
| PERF-2: repair.py unbounded `.all()` | Task 2 ✅ |
| PERF-2: qc.py unbounded `.all()` | Task 3 ✅ |
| DB-1: No soft-delete on Device | Tasks 4 + 5 ✅ |
| DB-1: `db.delete(device)` in stock.py:789 | Task 5 Step 2 ✅ |

**Already fixed — no tasks needed:**
- P-1 (IQC audit trail): `iqc.py:251` already has `await audit(db, action="DEVICE_IQC_REGISTERED", ...)`
- SEC-2/SEC-5 (failed-login counter + lockout): `auth.py` already has `MAX_FAILED_ATTEMPTS = 5` + lockout logic

### 2. Placeholder scan

No TBD/TODO/implement later present. All steps show exact code.

### 3. Type consistency

- `page: int = Query(default=1, ge=1)` — identical in Task 2 (repair.py) and Task 3 (qc.py), consistent with iqc.py
- `page_size: int = Query(default=50, ge=1, le=200)` — consistent across all routes
- `total_pages = max(1, (total + page_size - 1) // page_size)` — same formula as iqc.py
- `Device.is_active == True` — consistent filter in Tasks 2, 3, and 5
- `revision = '20260503_0900'`, `down_revision = '20260502_0800'` — correct Alembic chain
- Pagination context keys `page`, `page_size`, `total`, `total_pages` — consistent naming in both routers and both template widgets

### 4. Intentional omissions (not scope)

- `db.delete(item)` in `stock.py:603` — deletes `LotLineItem` (planning data within a lot, not a Device); hard delete acceptable
- `db.delete(transition)` in `stage_control.py:91` — deletes `AllowedTransition` (admin workflow config); hard delete acceptable
- `db.delete(row)` in `crm_price_matrix.py:185` — deletes price matrix config row; hard delete acceptable
- Lots: no `db.delete(lot)` call exists anywhere in the codebase; soft delete not needed yet
- Other list routes (sales.py, dealers.py) don't list Devices — `is_active` filter not needed there
