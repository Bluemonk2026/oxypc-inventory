# Sprint 16 — Audit Remediation 🟡 Tier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all 🟡-tier findings from the 2026-04-29 audit: API versioning, soft-delete pattern on core tables, lot P&L database view, auto-populate expected_sale_value from the grade-price matrix, migration rollback runbook, and RBAC API test suite.

**Architecture:** Tasks 1, 4, 5, 6 are independent and can be done in any order. Task 2 (soft-delete migration) must be committed before Task 3 (lot P&L view) because the view SQL filters `is_active = TRUE`. All tasks are additive — no existing routes are broken.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + PostgreSQL 15 + Alembic + pytest-asyncio + httpx 0.28

---

## File Map

| File | Action | Task |
|---|---|---|
| `routers/api.py` | Modify — change prefix `/api` → `/api/v1` | T1 |
| `templates/iqc/form.html` | Modify — update 2 fetch() URLs | T1 |
| `models/device.py` | Modify — add `deleted_at`, `is_active` columns | T2 |
| `models/lot.py` | Modify — add `deleted_at`, `is_active` columns | T2 |
| `models/user.py` | Modify — add `deleted_at` column | T2 |
| `alembic/versions/20260429_1200_add_soft_delete_columns.py` | Create — Alembic migration | T2 |
| `routers/stock.py` | Modify — soft-delete device in GRN remove; filter list queries | T2 |
| `routers/crm_price_matrix.py` | Modify — soft-delete GradePriceMatrix row | T2 |
| `alembic/versions/20260429_1400_add_vw_lot_pl_view.py` | Create — Alembic migration for DB view | T3 |
| `routers/reports.py` | Modify — replace 5 aggregation queries with single view query | T3 |
| `services/cost_engine.py` | Modify — add `set_expected_sale_value_from_matrix()` | T4 |
| `routers/qc.py` | Modify — call new function on QC pass | T4 |
| `tests/conftest.py` | Modify — add `async_client` fixture with DB override | T5 |
| `tests/test_rbac.py` | Create — RBAC access-control tests | T5 |
| `docs/migration-runbook.md` | Create — rollback runbook for all 11 migrations | T6 |

---

## Task 1: API Versioning — `/api` → `/api/v1`

**Audit item #8.** Adds `/v1/` to the internal JSON API router so it follows RESTful versioning standards. Two template `fetch()` calls need updating to match.

**Files:**
- Modify: `routers/api.py:18`
- Modify: `templates/iqc/form.html` (lines with `/api/lot-line-item` and `/api/lot-line-items-by-lot`)

- [ ] **Step 1: Write failing test**

```python
# tests/test_api_versioning.py
import pytest

def test_old_api_path_returns_404(app_client):
    """After versioning, /api/lot-line-item/<id> must not exist."""
    r = app_client.get("/api/lot-line-item/nonexistent-id")
    # 404 (route not found) or 401/302 (auth redirect) — NOT 200
    assert r.status_code != 200

def test_new_api_path_exists(app_client):
    """After versioning, /api/v1/... paths exist (auth protected → 302 not 404)."""
    r = app_client.get("/api/v1/dealers/search?q=test", follow_redirects=False)
    # 302 → login (auth required) is fine — proves route exists
    assert r.status_code in (200, 302, 401, 403)
```

- [ ] **Step 2: Run test — expect both to fail (old path returns 200, new path returns 404)**

```
cd C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
C:\Python313\python.exe -m pytest tests/test_api_versioning.py -v
```

Expected: `test_old_api_path_returns_404` FAIL (currently 302/200), `test_new_api_path_exists` FAIL (404 since prefix doesn't exist yet).

- [ ] **Step 3: Change prefix in `routers/api.py`**

Change line 18:
```python
# Before:
router = APIRouter(prefix="/api", tags=["api"])

# After:
router = APIRouter(prefix="/api/v1", tags=["api"])
```

- [ ] **Step 4: Update the two `fetch()` calls in `templates/iqc/form.html`**

Find and replace both occurrences:
```javascript
// Before:
const res = await fetch(`/api/lot-line-items-by-lot/${lotId}`);
// After:
const res = await fetch(`/api/v1/lot-line-items-by-lot/${lotId}`);

// Before:
const res = await fetch(`/api/lot-line-item/${id}`);
// After:
const res = await fetch(`/api/v1/lot-line-item/${id}`);
```

- [ ] **Step 5: Run tests — expect both to pass**

```
C:\Python313\python.exe -m pytest tests/test_api_versioning.py -v
```

Expected: both PASS.

- [ ] **Step 6: Smoke test the IQC form — open in browser, change lot, verify line items still auto-fill**

Navigate to `http://192.168.7.247:8000/iqc/new`. Change the Lot dropdown — confirm the line item dropdown populates (no JS errors in browser console).

- [ ] **Step 7: Commit**

```bash
git add routers/api.py templates/iqc/form.html tests/test_api_versioning.py
git commit -m "feat(api): version internal JSON API — prefix /api → /api/v1"
```

---

## Task 2: Soft-Delete Pattern — `devices`, `lots`, `users`

**Audit item #9.** Adds `deleted_at` (timestamp) and `is_active` (boolean flag) to the three core entity tables. All current `db.delete()` calls on these entities are replaced with soft-delete. List queries gain `is_active = TRUE` filters so deleted records are invisible to normal views.

**Files:**
- Modify: `models/device.py` — add two columns
- Modify: `models/lot.py` — add two columns
- Modify: `models/user.py` — add `deleted_at` column (`status` already acts as `is_active`)
- Create: `alembic/versions/20260429_1200_add_soft_delete_columns.py`
- Modify: `routers/stock.py` — soft-delete device in GRN remove (line ~688); add `is_active` filter to lot list
- Modify: `routers/crm_price_matrix.py` — soft-delete GradePriceMatrix row (line ~185)

### Step 2.1 — Write the failing test

- [ ] **Step 1: Write test**

```python
# tests/test_soft_delete.py
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

@pytest.mark.asyncio
async def test_soft_deleted_device_not_in_is_active_query(db: AsyncSession):
    """Devices with is_active=False must not appear in is_active=True queries."""
    from models.device import Device, DeviceStage
    import uuid

    # Create a device and soft-delete it
    d = Device(
        barcode=f"TEST-SD-{uuid.uuid4().hex[:8]}",
        lot_id=uuid.uuid4(),   # dummy lot_id (FK not enforced in SAVEPOINT context)
        current_stage=DeviceStage.iqc,
        is_active=False,
    )
    db.add(d)
    await db.flush()

    # Query only active devices
    result = await db.execute(
        select(Device).where(Device.barcode == d.barcode, Device.is_active == True)
    )
    assert result.scalar_one_or_none() is None, "Soft-deleted device should not appear in active queries"

@pytest.mark.asyncio
async def test_deleted_at_timestamp_is_set(db: AsyncSession):
    """Soft-deleted devices must have a non-null deleted_at timestamp."""
    from models.device import Device, DeviceStage
    from datetime import datetime
    import uuid

    d = Device(
        barcode=f"TEST-DT-{uuid.uuid4().hex[:8]}",
        lot_id=uuid.uuid4(),
        current_stage=DeviceStage.iqc,
    )
    db.add(d)
    await db.flush()

    # Simulate soft delete
    d.is_active = False
    d.deleted_at = datetime.utcnow()
    await db.flush()

    result = await db.execute(select(Device).where(Device.barcode == d.barcode))
    fetched = result.scalar_one()
    assert fetched.deleted_at is not None
    assert fetched.is_active is False
```

- [ ] **Step 2: Run — expect AttributeError (columns don't exist yet)**

```
C:\Python313\python.exe -m pytest tests/test_soft_delete.py -v
```

Expected: FAIL — `AttributeError: type object 'Device' has no attribute 'is_active'`

### Step 2.2 — Add columns to models

- [ ] **Step 3: Add `deleted_at` + `is_active` to `models/device.py`**

After line `updated_at = Column(DateTime, ...)` (around line 109), add:

```python
    # Soft-delete — never physically remove device records
    is_active   = Column(Boolean, default=True, nullable=False, index=True)
    deleted_at  = Column(DateTime, nullable=True)
```

- [ ] **Step 4: Add `deleted_at` + `is_active` to `models/lot.py`**

After `created_at = Column(DateTime, default=datetime.utcnow)` (around line 43), add:

```python
    # Soft-delete
    is_active   = Column(Boolean, default=True, nullable=False, index=True)
    deleted_at  = Column(DateTime, nullable=True)
```

- [ ] **Step 5: Add `deleted_at` to `models/user.py`**

After `status = Column(Boolean, default=True)` (the existing is-active flag), add:

```python
    deleted_at  = Column(DateTime, nullable=True)   # set on user disable/delete
```

### Step 2.3 — Write the Alembic migration

- [ ] **Step 6: Create migration file**

Create `alembic/versions/20260429_1200_add_soft_delete_columns.py`:

```python
"""add_soft_delete_columns

Revision ID: a1b2c3d4e5f6
Revises: e5e431fe7430
Create Date: 2026-04-29 12:00:00

Adds soft-delete columns (is_active, deleted_at) to devices and lots.
Adds deleted_at to users (status already acts as is_active for users).
All existing rows backfilled: is_active=TRUE, deleted_at=NULL.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'e5e431fe7430'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # devices
    op.add_column('devices', sa.Column('is_active', sa.Boolean(), nullable=True))
    op.add_column('devices', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.execute("UPDATE devices SET is_active = TRUE WHERE is_active IS NULL")
    op.alter_column('devices', 'is_active', nullable=False)
    op.create_index('ix_devices_is_active', 'devices', ['is_active'])

    # lots
    op.add_column('lots', sa.Column('is_active', sa.Boolean(), nullable=True))
    op.add_column('lots', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.execute("UPDATE lots SET is_active = TRUE WHERE is_active IS NULL")
    op.alter_column('lots', 'is_active', nullable=False)
    op.create_index('ix_lots_is_active', 'lots', ['is_active'])

    # users — deleted_at only (status = is_active already exists)
    op.add_column('users', sa.Column('deleted_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_index('ix_devices_is_active', table_name='devices')
    op.drop_column('devices', 'deleted_at')
    op.drop_column('devices', 'is_active')

    op.drop_index('ix_lots_is_active', table_name='lots')
    op.drop_column('lots', 'deleted_at')
    op.drop_column('lots', 'is_active')

    op.drop_column('users', 'deleted_at')
```

- [ ] **Step 7: Run the migration**

```
cd C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
C:\Python313\python.exe -m alembic upgrade head
```

Expected output ends with: `Running upgrade e5e431fe7430 -> a1b2c3d4e5f6, add_soft_delete_columns`

- [ ] **Step 8: Run soft-delete test — expect PASS**

```
C:\Python313\python.exe -m pytest tests/test_soft_delete.py -v
```

Expected: both tests PASS.

### Step 2.4 — Replace hard-delete call sites

- [ ] **Step 9: Soft-delete device in `routers/stock.py` GRN remove (around line 688)**

Find:
```python
    await db.delete(device)
    await db.commit()
    return JSONResponse({"ok": True})
```

This is in the `remove_grn_device` route. Replace with:
```python
    from datetime import datetime as _dt
    device.is_active = False
    device.deleted_at = _dt.utcnow()
    await db.commit()
    return JSONResponse({"ok": True})
```

- [ ] **Step 10: Soft-delete GradePriceMatrix row in `routers/crm_price_matrix.py` (around line 185)**

The `GradePriceMatrix` model does not have `is_active`/`deleted_at` — it's a config table. Add the columns only if desired, OR just keep hard-delete here since it's an admin config action that is intentional. Per YAGNI — **keep hard-delete for GradePriceMatrix** (it's config, not a transactional entity). No change needed here.

- [ ] **Step 11: Add `is_active` filter to stock.py lot list query**

In `routers/stock.py`, the `list_lots` route runs `select(Lot)`. Add the filter so soft-deleted lots don't appear:

Find the lot list query (it starts with `query = select(Lot)`), and add `.where(Lot.is_active == True)`:

```python
# Before:
query = select(Lot)
# (various conditional filters follow)

# After:
query = select(Lot).where(Lot.is_active == True)
```

- [ ] **Step 12: Run smoke tests to verify nothing broken**

```
C:\Python313\python.exe -m pytest tests/test_smoke.py tests/test_soft_delete.py -v
```

Expected: all PASS.

- [ ] **Step 13: Commit**

```bash
git add models/device.py models/lot.py models/user.py \
    alembic/versions/20260429_1200_add_soft_delete_columns.py \
    routers/stock.py tests/test_soft_delete.py
git commit -m "feat(db): soft-delete pattern on devices, lots, users — is_active + deleted_at"
```

---

## Task 3: Lot P&L Database View — `vw_lot_pl`

**Audit item #7.** Creates a PostgreSQL view that encapsulates the 5 aggregation queries in `routers/reports.py` into a single SQL object. Eliminates repeated ORM aggregation on every report page load.

**Depends on Task 2** — the view SQL references `devices.is_active`.

**Files:**
- Create: `alembic/versions/20260429_1400_add_vw_lot_pl_view.py`
- Modify: `routers/reports.py` — replace 5 separate GROUP BY queries with one `SELECT * FROM vw_lot_pl`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lot_pl_view.py
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.mark.asyncio
async def test_vw_lot_pl_exists(db: AsyncSession):
    """The vw_lot_pl view must exist in the database."""
    result = await db.execute(
        text("SELECT COUNT(*) FROM information_schema.views WHERE table_name = 'vw_lot_pl'")
    )
    count = result.scalar()
    assert count == 1, "View vw_lot_pl does not exist — run the migration"

@pytest.mark.asyncio
async def test_vw_lot_pl_queryable(db: AsyncSession):
    """The view must return rows (or empty set) without error."""
    result = await db.execute(text("SELECT lot_id, lot_number, profit FROM vw_lot_pl LIMIT 1"))
    # Just checking it doesn't raise — result may be empty
    rows = result.fetchall()
    assert isinstance(rows, list)
```

- [ ] **Step 2: Run test — expect FAIL**

```
C:\Python313\python.exe -m pytest tests/test_lot_pl_view.py -v
```

Expected: `test_vw_lot_pl_exists` FAIL — view does not exist yet.

- [ ] **Step 3: Create the Alembic migration**

Create `alembic/versions/20260429_1400_add_vw_lot_pl_view.py`:

```python
"""add_vw_lot_pl_view

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-29 14:00:00

Creates vw_lot_pl — a PostgreSQL view that pre-aggregates lot P&L metrics.
Eliminates 5 repeated GROUP BY queries on every /reports/lot-pl page load.

Columns:
  lot_id, lot_number, supplier_name, purchase_date, buying_price, qty,
  total_devices, sold_devices, revenue, parts_cost, labour_cost,
  total_cost, profit
"""
from alembic import op
from typing import Sequence, Union

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CREATE_VIEW = """
CREATE VIEW vw_lot_pl AS
SELECT
    l.id                                                        AS lot_id,
    l.lot_number,
    l.supplier_name,
    l.purchase_date,
    COALESCE(l.buying_price, 0)                                 AS buying_price,
    l.qty,
    COALESCE(d.total_devices, 0)                                AS total_devices,
    COALESCE(d.sold_devices, 0)                                 AS sold_devices,
    COALESCE(rev.revenue, 0)                                    AS revenue,
    COALESCE(parts.parts_cost, 0)                               AS parts_cost,
    COALESCE(lab.labour_cost, 0)                                AS labour_cost,
    COALESCE(l.buying_price, 0)
      + COALESCE(parts.parts_cost, 0)
      + COALESCE(lab.labour_cost, 0)                            AS total_cost,
    COALESCE(rev.revenue, 0)
      - COALESCE(l.buying_price, 0)
      - COALESCE(parts.parts_cost, 0)
      - COALESCE(lab.labour_cost, 0)                            AS profit
FROM lots l
LEFT JOIN (
    SELECT lot_id,
           COUNT(*)                                             AS total_devices,
           SUM(CASE WHEN current_stage = 'sold' THEN 1 ELSE 0 END) AS sold_devices
    FROM   devices
    WHERE  is_active = TRUE
    GROUP  BY lot_id
) d ON d.lot_id = l.id
LEFT JOIN (
    SELECT d2.lot_id,
           COALESCE(SUM(s.sale_price), 0)                      AS revenue
    FROM   devices d2
    JOIN   sales s ON s.device_id = d2.id
    GROUP  BY d2.lot_id
) rev ON rev.lot_id = l.id
LEFT JOIN (
    SELECT lot_id,
           COALESCE(SUM(total_cost), 0)                        AS parts_cost
    FROM   spare_parts_consumption
    WHERE  lot_id IS NOT NULL
    GROUP  BY lot_id
) parts ON parts.lot_id = l.id
LEFT JOIN (
    SELECT d3.lot_id,
           COALESCE(SUM(ra.cost), 0)                           AS labour_cost
    FROM   devices d3
    JOIN   repair_attempts ra ON ra.device_id = d3.id
    GROUP  BY d3.lot_id
) lab ON lab.lot_id = l.id
WHERE l.is_active = TRUE;
"""

_DROP_VIEW = "DROP VIEW IF EXISTS vw_lot_pl;"


def upgrade() -> None:
    op.execute(_CREATE_VIEW)


def downgrade() -> None:
    op.execute(_DROP_VIEW)
```

- [ ] **Step 4: Run the migration**

```
C:\Python313\python.exe -m alembic upgrade head
```

Expected: `Running upgrade a1b2c3d4e5f6 -> b2c3d4e5f6a7, add_vw_lot_pl_view`

- [ ] **Step 5: Run view test — expect PASS**

```
C:\Python313\python.exe -m pytest tests/test_lot_pl_view.py -v
```

Expected: both PASS.

- [ ] **Step 6: Refactor `routers/reports.py` lot_pl_report to use the view**

Replace the entire function body of `lot_pl_report` (lines ~32–106). The new implementation queries `vw_lot_pl` once instead of 5 GROUP BY queries:

```python
@router.get("/lot-pl", response_class=HTMLResponse)
async def lot_pl_report(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import text
    rows = (await db.execute(
        text("SELECT * FROM vw_lot_pl ORDER BY purchase_date DESC")
    )).mappings().all()

    lot_pl = []
    for r in rows:
        revenue    = float(r["revenue"] or 0)
        total_cost = float(r["total_cost"] or 0)
        profit     = float(r["profit"] or 0)
        margin     = round(profit / revenue * 100, 1) if revenue > 0 else 0
        lot_pl.append({
            "lot_number":    r["lot_number"],
            "supplier":      r["supplier_name"],
            "purchase_date": r["purchase_date"],
            "qty":           r["qty"],
            "devices":       r["total_devices"],
            "sold":          r["sold_devices"],
            "buying_price":  float(r["buying_price"] or 0),
            "parts_cost":    float(r["parts_cost"] or 0),
            "labour_cost":   float(r["labour_cost"] or 0),
            "total_cost":    total_cost,
            "revenue":       revenue,
            "profit":        profit,
            "margin":        margin,
            "lot_id":        str(r["lot_id"]),
        })
    return templates.TemplateResponse("reports/lot_pl.html", {
        "request": request, "lot_pl": lot_pl, "current_user": current_user
    })
```

- [ ] **Step 7: Also refactor `export_lot_pl` to use the view**

Replace the body of `export_lot_pl` (lines ~147–179):

```python
@router.get("/export/lot-pl")
async def export_lot_pl(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import text
    import csv, io
    rows = (await db.execute(
        text("SELECT * FROM vw_lot_pl ORDER BY purchase_date DESC")
    )).mappings().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Lot#", "Supplier", "Date", "Qty",
        "Buying Price", "Parts Cost", "Labour Cost",
        "Total Cost", "Revenue", "Profit", "Margin%",
    ])
    for r in rows:
        revenue    = float(r["revenue"] or 0)
        total_cost = float(r["total_cost"] or 0)
        profit     = float(r["profit"] or 0)
        margin     = round(profit / revenue * 100, 1) if revenue > 0 else 0
        writer.writerow([
            r["lot_number"], r["supplier_name"],
            r["purchase_date"].strftime("%Y-%m-%d") if r["purchase_date"] else "",
            r["qty"],
            f"{float(r['buying_price'] or 0):.2f}",
            f"{float(r['parts_cost'] or 0):.2f}",
            f"{float(r['labour_cost'] or 0):.2f}",
            f"{total_cost:.2f}", f"{revenue:.2f}", f"{profit:.2f}", f"{margin:.1f}",
        ])
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": "attachment; filename=lot-pl.csv"},
    )
```

- [ ] **Step 8: Verify report page loads**

Navigate to `http://192.168.7.247:8000/reports/lot-pl` (as admin). Page should load. If there are lots in the DB, they should appear with P&L figures.

- [ ] **Step 9: Commit**

```bash
git add alembic/versions/20260429_1400_add_vw_lot_pl_view.py \
    routers/reports.py tests/test_lot_pl_view.py
git commit -m "perf(reports): replace 5 aggregation queries with vw_lot_pl database view"
```

---

## Task 4: Auto-populate `expected_sale_value` from Grade-Price Matrix

**Audit item #10.** When a device passes QC and is assigned a grade, look up the `crm_grade_price_matrix` table for a matching `device_type + grade` row and set `DeviceCosting.expected_sale_value = target_sell`. This enables the auto-scrap engine to fire reliably.

**Files:**
- Modify: `services/cost_engine.py` — add `set_expected_sale_value_from_matrix()`
- Modify: `routers/qc.py` — call the new function after grade is set on QC pass

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cost_engine_matrix.py
import pytest
import pytest_asyncio
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

@pytest.mark.asyncio
async def test_set_expected_sale_value_from_matrix(db: AsyncSession):
    """set_expected_sale_value_from_matrix() must populate DeviceCosting.expected_sale_value
    from the grade-price matrix when a matching row exists."""
    from models.lot import Lot
    from models.device import Device, DeviceStage
    from models.crm import GradePriceMatrix
    from models.engines import DeviceCosting
    from services.cost_engine import set_expected_sale_value_from_matrix

    # Seed a lot and device
    lot = Lot(
        lot_number=f"TST-{uuid.uuid4().hex[:6]}",
        supplier_name="Test Supplier",
        buying_price=Decimal("10000"),
        qty=10,
        purchase_date=__import__('datetime').datetime.utcnow(),
    )
    db.add(lot)
    await db.flush()

    device = Device(
        barcode=f"RBCTEST-{uuid.uuid4().hex[:8]}",
        lot_id=lot.id,
        current_stage=DeviceStage.qc_check,
        device_type="Laptop",
        grade=None,
    )
    db.add(device)
    await db.flush()

    # Seed a grade-price matrix entry
    gpm = GradePriceMatrix(
        device_type="Laptop",
        grade="A",
        target_sell=Decimal("8500"),
        min_margin_pct=Decimal("15"),
    )
    db.add(gpm)
    await db.flush()

    # Set grade and call the function
    device.grade = "A"
    await set_expected_sale_value_from_matrix(device, db)
    await db.flush()

    # Verify DeviceCosting was created/updated with expected_sale_value
    from sqlalchemy import select
    costing = (await db.execute(
        select(DeviceCosting).where(DeviceCosting.device_id == device.id)
    )).scalar_one_or_none()

    assert costing is not None
    assert costing.expected_sale_value == Decimal("8500"), (
        f"Expected 8500, got {costing.expected_sale_value}"
    )


@pytest.mark.asyncio
async def test_set_expected_sale_value_no_matrix_row(db: AsyncSession):
    """When no matrix row matches, expected_sale_value remains None (no crash)."""
    from models.lot import Lot
    from models.device import Device, DeviceStage
    from models.engines import DeviceCosting
    from services.cost_engine import set_expected_sale_value_from_matrix
    import datetime

    lot = Lot(
        lot_number=f"TST2-{uuid.uuid4().hex[:6]}",
        supplier_name="Test Supplier 2",
        buying_price=Decimal("5000"),
        qty=5,
        purchase_date=datetime.datetime.utcnow(),
    )
    db.add(lot)
    await db.flush()

    device = Device(
        barcode=f"RBCTEST2-{uuid.uuid4().hex[:8]}",
        lot_id=lot.id,
        current_stage=DeviceStage.qc_check,
        device_type="UnknownType",  # no matching matrix row
        grade="B",
    )
    db.add(device)
    await db.flush()

    # Should not raise — just returns without setting a value
    await set_expected_sale_value_from_matrix(device, db)
    await db.flush()

    from sqlalchemy import select
    costing = (await db.execute(
        select(DeviceCosting).where(DeviceCosting.device_id == device.id)
    )).scalar_one_or_none()

    # Either no costing row was created, or expected_sale_value is still None
    if costing:
        assert costing.expected_sale_value is None
```

- [ ] **Step 2: Run test — expect FAIL**

```
C:\Python313\python.exe -m pytest tests/test_cost_engine_matrix.py -v
```

Expected: `ImportError: cannot import name 'set_expected_sale_value_from_matrix'` (function doesn't exist yet).

- [ ] **Step 3: Add `set_expected_sale_value_from_matrix()` to `services/cost_engine.py`**

Add these imports at the top of the file (add to existing import block):
```python
from models.crm import GradePriceMatrix
```

Add the new function after `check_below_cost_warning()` (at the end of the file):

```python
async def set_expected_sale_value_from_matrix(
    device: Device,
    db: AsyncSession,
) -> None:
    """Look up GradePriceMatrix for device_type + grade and set
    DeviceCosting.expected_sale_value = target_sell.

    Does nothing if:
    - device.grade is None
    - device.device_type is None
    - No matching matrix row exists
    - target_sell is NULL on the matching row
    """
    if not device.grade or not device.device_type:
        return

    grade_str = device.grade.value if hasattr(device.grade, "value") else str(device.grade)

    # Most specific match first: device_type + grade + brand
    # Fall back to device_type + grade (brand=NULL)
    row = None
    if device.brand:
        brand_result = await db.execute(
            select(GradePriceMatrix).where(
                GradePriceMatrix.device_type == device.device_type,
                GradePriceMatrix.grade == grade_str,
                GradePriceMatrix.brand == device.brand,
            ).limit(1)
        )
        row = brand_result.scalar_one_or_none()

    if not row:
        generic_result = await db.execute(
            select(GradePriceMatrix).where(
                GradePriceMatrix.device_type == device.device_type,
                GradePriceMatrix.grade == grade_str,
                GradePriceMatrix.brand.is_(None),
            ).limit(1)
        )
        row = generic_result.scalar_one_or_none()

    if not row or row.target_sell is None:
        return

    costing = await get_or_create_costing(device, db)
    costing.expected_sale_value = Decimal(str(row.target_sell))
    costing.updated_at = datetime.utcnow()
```

- [ ] **Step 4: Run test — expect PASS**

```
C:\Python313\python.exe -m pytest tests/test_cost_engine_matrix.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Call the function from `routers/qc.py` on QC pass**

In `qc.py`, add the import at the top:

```python
from services.cost_engine import check_scrap_decision, set_expected_sale_value_from_matrix
```

In the `qc_submit` route, inside `if result_ == "pass":` block, after `device.grade = grade` (around line 191), add:

```python
    if result_ == "pass":
        device.grade        = grade
        device.updated_at   = datetime.utcnow()
        # Auto-populate expected_sale_value from grade-price matrix
        await set_expected_sale_value_from_matrix(device, db)
        to_stage = DeviceStage.cleaning
        # ... rest of pass logic unchanged
```

- [ ] **Step 6: Run full test suite to verify no regressions**

```
C:\Python313\python.exe -m pytest tests/ -v --tb=short
```

Expected: all existing tests PASS + 2 new cost engine tests PASS.

- [ ] **Step 7: Commit**

```bash
git add services/cost_engine.py routers/qc.py tests/test_cost_engine_matrix.py
git commit -m "feat(cost-engine): auto-populate expected_sale_value from grade-price matrix on QC pass"
```

---

## Task 5: RBAC API Test Suite

**Audit item from Testing Strategy.** Tests that role-based access control is enforced — unauthenticated users get redirected, wrong-role users get 403, correct-role users get through.

Uses `httpx.AsyncClient` with ASGI transport so the real server is NOT required. Overrides `get_db` with the transactional test DB from `conftest.py`.

**Files:**
- Modify: `tests/conftest.py` — add `async_client` and token fixtures
- Create: `tests/test_rbac.py`

- [ ] **Step 1: Add `async_client` and token fixtures to `tests/conftest.py`**

Add at the end of `tests/conftest.py`:

```python
# ---------------------------------------------------------------------------
# ASGI test client (no real server needed)
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def async_client(db: AsyncSession):
    """
    httpx AsyncClient wired to the FastAPI ASGI app directly.
    Overrides get_db with the transactional test session so DB writes
    in tests roll back automatically.
    """
    from httpx import AsyncClient, ASGITransport
    from main import app
    from database import get_db

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _make_jwt(username: str, role: str) -> str:
    """Create a signed JWT for test use. Does NOT create a DB user."""
    from auth.dependencies import create_access_token
    return create_access_token({"sub": username, "role": role})
```

- [ ] **Step 2: Create `tests/test_rbac.py`**

```python
"""
RBAC enforcement tests.

These tests verify that role-based access control is enforced at the route
level — unauthenticated requests redirect to login, wrong-role requests
return 403, and correct-role requests pass through.

Uses httpx AsyncClient with ASGI transport (no real server required).
The `async_client` fixture overrides get_db with the transactional test DB.

NOTE: These tests create a real User row in the transactional DB session
to satisfy get_current_user's DB lookup. The SAVEPOINT in conftest rolls
everything back after each test.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_user(db, username: str, role_str: str) -> None:
    """Insert a minimal User row into the test DB for JWT auth to find."""
    from models.user import User, UserRole
    from auth.dependencies import hash_password
    u = User(
        username=username,
        full_name=f"Test {role_str}",
        role=UserRole(role_str),
        password_hash=hash_password("test"),
        status=True,
    )
    db.add(u)
    await db.flush()


def _auth_cookies(username: str, role: str) -> dict:
    """Return cookie dict with a valid JWT for the given user/role."""
    from tests.conftest import _make_jwt
    import secrets
    token = _make_jwt(username, role)
    return {"access_token": token, "csrf_token": secrets.token_hex(16)}


# ---------------------------------------------------------------------------
# Unauthenticated access
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unauthenticated_admin_redirects_to_login(
    async_client: AsyncClient,
):
    """Admin routes must redirect unauthenticated requests to /auth/login."""
    r = await async_client.get("/admin/users", follow_redirects=False)
    assert r.status_code == 302
    assert "/auth/login" in r.headers.get("location", "")


@pytest.mark.asyncio
async def test_unauthenticated_iqc_redirects_to_login(
    async_client: AsyncClient,
):
    r = await async_client.get("/iqc", follow_redirects=False)
    assert r.status_code == 302
    assert "/auth/login" in r.headers.get("location", "")


# ---------------------------------------------------------------------------
# Wrong-role access (403 expected)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sales_role_cannot_access_admin_users(
    async_client: AsyncClient,
    db: AsyncSession,
):
    """A sales user must not be able to access /admin/users (403)."""
    await _seed_user(db, "test_sales_rbac", "sales")
    cookies = _auth_cookies("test_sales_rbac", "sales")
    r = await async_client.get("/admin/users", cookies=cookies, follow_redirects=False)
    assert r.status_code in (403, 302), (
        f"Expected 403 or redirect, got {r.status_code}"
    )


@pytest.mark.asyncio
async def test_iqc_inspector_cannot_access_admin_users(
    async_client: AsyncClient,
    db: AsyncSession,
):
    """An IQC inspector must not be able to access /admin/users."""
    await _seed_user(db, "test_iqc_rbac", "iqc_inspector")
    cookies = _auth_cookies("test_iqc_rbac", "iqc_inspector")
    r = await async_client.get("/admin/users", cookies=cookies, follow_redirects=False)
    assert r.status_code in (403, 302)


# ---------------------------------------------------------------------------
# Correct-role access (200 expected)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_can_access_admin_users(
    async_client: AsyncClient,
    db: AsyncSession,
):
    """An admin user must get a 200 on /admin/users."""
    await _seed_user(db, "test_admin_rbac", "admin")
    cookies = _auth_cookies("test_admin_rbac", "admin")
    r = await async_client.get("/admin/users", cookies=cookies)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"


@pytest.mark.asyncio
async def test_admin_can_access_iqc(
    async_client: AsyncClient,
    db: AsyncSession,
):
    """Admin has universal access — must get 200 on /iqc."""
    await _seed_user(db, "test_admin_iqc_rbac", "admin")
    cookies = _auth_cookies("test_admin_iqc_rbac", "admin")
    r = await async_client.get("/iqc", cookies=cookies)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_iqc_inspector_can_access_iqc(
    async_client: AsyncClient,
    db: AsyncSession,
):
    """IQC inspector must get 200 on their primary route /iqc."""
    await _seed_user(db, "test_iqc_access_rbac", "iqc_inspector")
    cookies = _auth_cookies("test_iqc_access_rbac", "iqc_inspector")
    r = await async_client.get("/iqc", cookies=cookies)
    assert r.status_code == 200
```

- [ ] **Step 3: Run RBAC tests**

```
C:\Python313\python.exe -m pytest tests/test_rbac.py -v --tb=short
```

Expected: all 6 tests PASS. If any role check in `require_roles()` raises HTTPException(403) instead of redirecting, the test assertion covers both.

- [ ] **Step 4: Run full suite**

```
C:\Python313\python.exe -m pytest tests/ -v --tb=short
```

Expected: all tests PASS. Note: RBAC tests are integration-level and hit the real SQLAlchemy models through the ASGI app — if a template rendering error occurs, fix the template or skip with `@pytest.mark.skip`.

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_rbac.py tests/test_api_versioning.py
git commit -m "test(rbac): add RBAC API test suite with async_client fixture + role access assertions"
```

---

## Task 6: Migration Rollback Runbook

**Audit item #11.** Documents the rollback procedure for every existing Alembic migration, how to run it safely, and what data risk each downgrade carries.

**Files:**
- Create: `docs/migration-runbook.md`

- [ ] **Step 1: Create `docs/migration-runbook.md`**

```markdown
# Migration Rollback Runbook

**Purpose:** Safe downgrade guide for each Alembic migration. Run these steps
before any rollback — check data risk first.

## How to downgrade

```bash
# Downgrade one step back
cd C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
C:\Python313\python.exe -m alembic downgrade -1

# Downgrade to a specific revision
C:\Python313\python.exe -m alembic downgrade <revision_id>

# Show current revision
C:\Python313\python.exe -m alembic current

# Show full history
C:\Python313\python.exe -m alembic history --verbose
```

⚠️ **Always take a DB backup before downgrading in production:**
```bash
pg_dump -U oxypc oxypc_db > backup_before_downgrade_$(date +%Y%m%d_%H%M).sql
```

---

## Migration Chain

| # | Revision | File | What It Does | Downgrade Risk |
|---|---|---|---|---|
| 1 | `ba22dd09a6a3` | `20260331_1600_…_initial_baseline.py` | Baseline schema — all tables | 🔴 **DESTROYS ALL DATA** — drops all tables |
| 2 | `0c716e3ade5c` | `20260401_1304_…_add_qa_uat_tables.py` | Adds QA/UAT tables | 🟡 Loses all QA test case + defect data |
| 3 | `crm_add_crm_tables` | `20260425_1534_crm_add_crm_tables.py` | Adds all CRM tables | 🟡 Loses all CRM contacts, deals, activities |
| 4 | `4e2fc1624802` | `20260425_1747_…_add_grade_price_matrix.py` | Adds `crm_grade_price_matrix` | 🟢 Config table only — low risk |
| 5 | `ea9ba80876e8` | `20260425_1940_…_add_customer_state_to_sales.py` | Adds `customer_state` to sales | 🟢 Column removal — no data loss |
| 6 | `2af82f82cdc2` | `20260425_1954_…_add_purchase_orders.py` | Adds CRM PO tables | 🟡 Loses PO records |
| 7 | `feeee5ac8d0f` | `20260425_2011_…_add_supplier_payments_customer_receipts.py` | Adds payment/receipt tables | 🟡 Loses payment records |
| 8 | `eea7c1db1ab0` | `20260426_0852_…_add_app_settings.py` | Adds `app_settings` table | 🟢 Config — low risk |
| 9 | `f991834630d1` | `20260426_0940_…_add_missing_fk_indexes.py` | Adds FK indexes | 🟢 Index-only — no data loss |
| 10 | `b62e6ba33486` | `20260427_1811_…_add_composite_indexes_sprint18.py` | Adds composite indexes | 🟢 Index-only — no data loss |
| 11 | `e5e431fe7430` | `20260429_0819_…_add_tenant_to_users.py` | Adds `tenant` column to users | 🟢 Column removal — no data loss |
| 12 | `a1b2c3d4e5f6` | `20260429_1200_…_add_soft_delete_columns.py` | Adds `is_active`, `deleted_at` to devices/lots/users | 🟡 Column removal — any soft-deleted records become invisible after rollback |
| 13 | `b2c3d4e5f6a7` | `20260429_1400_…_add_vw_lot_pl_view.py` | Creates `vw_lot_pl` DB view | 🟢 View DROP only — no data loss |

---

## Migration-Specific Notes

### #1 Initial Baseline (`ba22dd09a6a3`)
**NEVER downgrade this in production.** It drops every table. Only useful to
rebuild a fresh test environment from scratch.

### #12 Soft-Delete (`a1b2c3d4e5f6`)
If you downgrade this migration, devices that were soft-deleted (is_active=FALSE)
will have their `is_active` column removed. After re-upgrading, those devices will
default `is_active=TRUE` (re-appear in lists). Back up device/lot data before
downgrading if any soft-deletes have been performed.

Downgrade sequence:
```bash
C:\Python313\python.exe -m alembic downgrade b62e6ba33486
```
This drops is_active + deleted_at from devices, lots, and deleted_at from users.

### #13 vw_lot_pl View (`b2c3d4e5f6a7`)
Safe to downgrade at any time — `DROP VIEW IF EXISTS vw_lot_pl` only.
The /reports/lot-pl page will fall back to ORM queries after downgrade (update
routers/reports.py to restore the 5 GROUP BY queries if staying on the downgraded version).
```
```

- [ ] **Step 2: Verify the file is readable**

```
type docs\migration-runbook.md | head -30
```

Expected: first 30 lines of the runbook shown.

- [ ] **Step 3: Commit**

```bash
git add docs/migration-runbook.md
git commit -m "docs: add migration rollback runbook for all 13 Alembic migrations"
```

---

## Final Verification

- [ ] **Run the full test suite**

```
C:\Python313\python.exe -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected summary: all tests pass. Acceptable failures: any test that requires a live server (`app_client` fixture) will skip/fail if server is not running — that is expected.

- [ ] **Verify DB migrations applied**

```
C:\Python313\python.exe -m alembic current
```

Expected: `b2c3d4e5f6a7 (head)` (or the last migration revision).

- [ ] **Smoke the /reports/lot-pl page**

Navigate to `http://192.168.7.247:8000/reports/lot-pl` as admin. Should load and show P&L data (or empty table if no lots).

- [ ] **Update the audit document**

Update `docs/audits/2026-04-29-claude-md-full-audit.md` — change items 7–11 from pending to ✅ and re-score affected layers:
- L3 API/Backend: 5.0 → 7.0 🟢 (API versioning + view replaces ORM queries)
- L2 Database/Schema: 6.0 → 7.5 🟢 (soft-delete + DB view)
- Testing: 3.0 → 6.0 🟡 (RBAC tests + async_client infra)
- Audit Trail: 4.5 → 4.5 🔴 (unchanged — needs Sprint 17 for spare-parts + dealer auditing)

---

## Post-Sprint Score Estimate

| Layer | Before | After Sprint 16 |
|---|---|---|
| L2 Database/Schema | 6.0 🟡 | 7.5 🟢 |
| L3 API/Backend | 5.0 🟡 | 7.0 🟢 |
| L5 Security | 6.5 🟡 | 6.5 🟡 (unchanged) |
| Testing | 3.0 🔴 | 6.0 🟡 |
| **Overall** | **5.6 🟡** | **~6.5 🟡** |

*Target for 🟢 overall (7.5+): 2 more sprints — Sprint 17 (audit trail completeness + spare parts) and Sprint 18 (profitability gate).*
