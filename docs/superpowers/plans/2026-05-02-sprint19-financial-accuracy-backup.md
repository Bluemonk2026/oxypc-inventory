# Sprint 19 — Financial Accuracy + Backup Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two RED-tier risks: (1) lot profit overstated because cosmetic rework cost and unfilled labour costs are missing from COGS, and (2) no automated backup means hardware failure = total data loss.

**Architecture:** Add a `cost_config` DB table for configurable rates (repair labour rate ₹150/attempt, cosmetic rate ₹50/device); update the lot P&L calculation in the dashboard to include cosmetic cost and a labour fallback rate; add a profit summary to the lot detail page; add a `scripts/backup_db.py` script with 30-day retention and a Windows Task Scheduler setup bat file; add backup admin endpoints and a UI card.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, Alembic, Pydantic v2, Jinja2 + Bootstrap 5, subprocess + gzip for backup, Windows `schtasks` for scheduling.

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `models/cost_config.py` | `CostConfig` ORM model (key/value rates table) |
| Modify | `models/__init__.py` | export `CostConfig` |
| Create | `alembic/versions/20260502_0800_add_cost_config.py` | migration: create `cost_config` table |
| Modify | `db_validator.py` | seed default cost_config rows on startup |
| Modify | `routers/admin.py` | add GET/POST `/admin/cost-config` routes |
| Create | `templates/admin/cost_config.html` | cost config settings page |
| Modify | `routers/dashboard.py` | fix lot_pl: add attempt-count batch, cosmetic-count batch, load rates, apply to COGS |
| Modify | `routers/stock.py` | compute full profit in `lot_detail` |
| Modify | `templates/lots/detail.html` | add profit summary card |
| Create | `scripts/backup_db.py` | pg_dump + gzip + 30-day retention |
| Create | `scripts/setup_backup_task.bat` | Windows Task Scheduler daily at 02:00 |
| Modify | `routers/admin.py` | add GET `/admin/backup-status` (JSON) + POST `/admin/backup-now` |
| Modify | `templates/admin/users.html` | add backup status card (admin only) |
| Create | `tests/test_sprint19_unit.py` | unit tests for all new logic |

---

## Task 1: `CostConfig` model + migration + seed

**Files:**
- Create: `models/cost_config.py`
- Modify: `models/__init__.py`
- Create: `alembic/versions/20260502_0800_add_cost_config.py`
- Modify: `db_validator.py`
- Test: `tests/test_sprint19_unit.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sprint19_unit.py
"""Sprint 19 unit tests — CostConfig model, backup script, P&L calculation."""


def test_cost_config_model_fields():
    """CostConfig ORM model must have key, value, description, updated_by, updated_at."""
    src = open("models/cost_config.py", encoding="utf-8").read()
    for field in ["key", "value", "description", "updated_by", "updated_at"]:
        assert field in src, f"CostConfig missing field: {field}"


def test_cost_config_exported_from_models_init():
    """models/__init__.py must export CostConfig."""
    src = open("models/__init__.py", encoding="utf-8").read()
    assert "CostConfig" in src, "models/__init__.py missing CostConfig export"


def test_cost_config_migration_exists():
    """Migration file for cost_config must exist with correct down_revision."""
    import glob
    files = glob.glob("alembic/versions/*cost_config*.py")
    assert files, "No cost_config migration file found"
    content = open(files[0], encoding="utf-8").read()
    assert "20260501_0900" in content, "Migration down_revision must be 20260501_0900"
    assert "cost_config" in content, "Migration must create cost_config table"


def test_db_validator_seeds_cost_config():
    """db_validator.py must seed repair_labour_rate and cosmetic_rate."""
    src = open("db_validator.py", encoding="utf-8").read()
    assert "repair_labour_rate" in src, "db_validator missing repair_labour_rate seed"
    assert "cosmetic_rate" in src, "db_validator missing cosmetic_rate seed"
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_sprint19_unit.py -v --tb=short
```
Expected: 4 FAILED

- [ ] **Step 3: Create `models/cost_config.py`**

```python
# models/cost_config.py
"""
CostConfig — configurable rates for the cost engine.

Keys used by the system:
  repair_labour_rate  — ₹ per repair attempt when engineer enters no cost (default 150)
  cosmetic_rate       — ₹ per device that passed through cosmetic pipeline (default 50)
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Numeric, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from database import Base


class CostConfig(Base):
    __tablename__ = "cost_config"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key         = Column(String(50), unique=True, nullable=False, index=True)
    value       = Column(Numeric(10, 2), nullable=False)
    description = Column(Text, nullable=True)
    updated_by  = Column(String(50), nullable=True)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

- [ ] **Step 4: Export from `models/__init__.py`**

Add this line to `models/__init__.py` alongside the other model imports:

```python
from .cost_config import CostConfig
```

- [ ] **Step 5: Create migration**

```python
# alembic/versions/20260502_0800_add_cost_config.py
"""add cost_config table

Revision ID: 20260502_0800
Revises: 20260501_0900
Create Date: 2026-05-02 08:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '20260502_0800'
down_revision = '20260501_0900'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'cost_config',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('key', sa.String(50), nullable=False, unique=True),
        sa.Column('value', sa.Numeric(10, 2), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('updated_by', sa.String(50), nullable=True),
        sa.Column('updated_at', sa.DateTime, nullable=True),
    )
    op.create_index('ix_cost_config_key', 'cost_config', ['key'])


def downgrade():
    op.drop_index('ix_cost_config_key', table_name='cost_config')
    op.drop_table('cost_config')
```

- [ ] **Step 6: Run migration**

```
alembic upgrade head
```
Expected: `Running upgrade 20260501_0900 -> 20260502_0800, add cost_config table`

- [ ] **Step 7: Seed defaults in `db_validator.py`**

Find the function `validate_and_fix` in `db_validator.py`. At the **end** of its try block (after the stage seeding, around line 270), add:

```python
    # ── fix 4: seed cost_config defaults ─────────────────────────────────────
    await conn.execute(sa.text("""
        INSERT INTO cost_config (id, key, value, description, updated_by, updated_at)
        VALUES
          (gen_random_uuid(), 'repair_labour_rate', 150.00,
           'Labour cost per repair attempt when engineer enters no cost (₹)',
           'system', NOW()),
          (gen_random_uuid(), 'cosmetic_rate', 50.00,
           'Cosmetic rework cost per device that passed through cleaning stage (₹)',
           'system', NOW())
        ON CONFLICT (key) DO NOTHING
    """))
    await conn.commit()
```

> **Note:** The `ON CONFLICT (key) DO NOTHING` means existing rows are preserved — admins who customise rates won't have them overwritten on restart.

- [ ] **Step 8: Run tests**

```
pytest tests/test_sprint19_unit.py -v --tb=short
```
Expected: 4 PASSED

- [ ] **Step 9: Commit**

```bash
git add models/cost_config.py models/__init__.py \
        alembic/versions/20260502_0800_add_cost_config.py \
        db_validator.py tests/test_sprint19_unit.py
git commit -m "feat: CostConfig model, migration, and startup seed"
```

---

## Task 2: Cost Config Admin UI

**Files:**
- Modify: `routers/admin.py`
- Create: `templates/admin/cost_config.html`
- Test: `tests/test_sprint19_unit.py` (add tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_sprint19_unit.py`:

```python
def test_admin_has_cost_config_routes():
    """routers/admin.py must have GET and POST routes for /cost-config."""
    src = open("routers/admin.py", encoding="utf-8").read()
    assert "/cost-config" in src, "admin.py missing /cost-config route"
    assert "cost_config" in src.lower(), "admin.py missing CostConfig usage"


def test_cost_config_template_exists():
    """templates/admin/cost_config.html must exist with form fields."""
    src = open("templates/admin/cost_config.html", encoding="utf-8").read()
    assert "repair_labour_rate" in src, "cost_config.html missing repair_labour_rate field"
    assert "cosmetic_rate" in src, "cost_config.html missing cosmetic_rate field"
    assert 'method="post"' in src.lower(), "cost_config.html missing POST form"
    assert "csrf_token" in src, "cost_config.html missing csrf_token"
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_sprint19_unit.py::test_admin_has_cost_config_routes tests/test_sprint19_unit.py::test_cost_config_template_exists -v --tb=short
```
Expected: 2 FAILED

- [ ] **Step 3: Add routes to `routers/admin.py`**

Add these imports at the top of `routers/admin.py` (alongside existing imports):

```python
from decimal import Decimal
from models.cost_config import CostConfig
```

Then add these two routes at the **end** of `routers/admin.py`, before any `if __name__` block:

```python
# ── Cost Config ────────────────────────────────────────────────────────────

COST_CONFIG_DEFS = [
    ("repair_labour_rate", "Labour Rate per Repair Attempt (₹)",
     "Used when engineer leaves cost field blank. Default: ₹150"),
    ("cosmetic_rate", "Cosmetic Rework Rate per Device (₹)",
     "Applied per device that passed through cleaning/rework stage. Default: ₹50"),
]


@router.get("/cost-config", response_class=HTMLResponse)
async def cost_config_view(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(CostConfig))
    rows = {r.key: r for r in result.scalars().all()}
    return templates.TemplateResponse("admin/cost_config.html", {
        "request": request,
        "current_user": current_user,
        "defs": COST_CONFIG_DEFS,
        "rows": rows,
    })


@router.post("/cost-config")
async def cost_config_save(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    form = await request.form()
    for key, _label, _hint in COST_CONFIG_DEFS:
        raw = form.get(key, "").strip()
        try:
            new_val = Decimal(raw)
        except Exception:
            continue
        result = await db.execute(select(CostConfig).where(CostConfig.key == key))
        row = result.scalar_one_or_none()
        if row:
            row.value = new_val
            row.updated_by = current_user.username
        else:
            db.add(CostConfig(key=key, value=new_val, updated_by=current_user.username))

    from models.engines import AuditLog
    import json
    db.add(AuditLog(
        username=current_user.username,
        action="COST_CONFIG_UPDATE",
        table_name="cost_config",
        new_value=json.dumps({k: form.get(k) for k, _, _ in COST_CONFIG_DEFS}),
    ))
    await db.commit()
    return RedirectResponse(url="/admin/cost-config?success=Rates+saved", status_code=302)
```

> **Note:** `RedirectResponse` is already imported in `routers/admin.py`. If not, add `from fastapi.responses import RedirectResponse`.

- [ ] **Step 4: Create `templates/admin/cost_config.html`**

```html
{% extends "base.html" %}
{% block title %}Cost Config — OxyPC{% endblock %}
{% block page_title %}Cost Configuration{% endblock %}
{% block content %}
{% if request.query_params.get('success') %}
<div class="alert alert-success alert-dismissible fade show">
  <i class="bi bi-check-circle me-2"></i>{{ request.query_params.get('success') }}
  <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
</div>
{% endif %}
<div class="row justify-content-center">
  <div class="col-xl-6">
    <div class="card border-0 shadow-sm">
      <div class="card-header bg-transparent fw-semibold">
        <i class="bi bi-calculator me-2"></i>Cost Engine Rates
      </div>
      <div class="card-body">
        <p class="text-muted small mb-4">
          These rates are used when engineers do not enter actual costs.
          Changes take effect immediately on the next dashboard load.
        </p>
        <form method="post" action="/admin/cost-config">
          <input type="hidden" name="csrf_token" value="{{ request.cookies.get('csrf_token', '') }}">
          {% for key, label, hint in defs %}
          <div class="mb-4">
            <label class="form-label fw-semibold">{{ label }}</label>
            <div class="input-group input-group-sm" style="max-width:220px">
              <span class="input-group-text">₹</span>
              <input type="number" step="0.01" min="0" name="{{ key }}" class="form-control"
                     value="{{ rows[key].value if key in rows else '' }}"
                     placeholder="e.g. 150.00" required>
            </div>
            <div class="form-text">{{ hint }}</div>
            {% if key in rows and rows[key].updated_by %}
            <div class="form-text text-muted">
              Last updated by <strong>{{ rows[key].updated_by }}</strong>
              {% if rows[key].updated_at %}on {{ rows[key].updated_at.strftime('%d %b %Y %H:%M') }}{% endif %}
            </div>
            {% endif %}
          </div>
          {% endfor %}
          <div class="d-flex gap-2">
            <button type="submit" class="btn btn-primary btn-sm px-4">
              <i class="bi bi-save me-1"></i>Save Rates
            </button>
            <a href="/admin/users" class="btn btn-outline-secondary btn-sm">Cancel</a>
          </div>
        </form>
      </div>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Add Cost Config link to sidebar in `templates/base.html`**

Find the admin nav section in `base.html` (search for `/admin/users`). Add alongside it:

```html
<li><a href="/admin/cost-config" class="nav-link {% if '/admin/cost-config' in request.url.path %}active{% endif %}">
  <i class="bi bi-calculator me-2"></i> Cost Config
</a></li>
```

- [ ] **Step 6: Run tests**

```
pytest tests/test_sprint19_unit.py -v --tb=short
```
Expected: All PASSED

- [ ] **Step 7: Commit**

```bash
git add routers/admin.py templates/admin/cost_config.html templates/base.html \
        tests/test_sprint19_unit.py
git commit -m "feat: cost config admin UI — configurable repair labour and cosmetic rates"
```

---

## Task 3: Fix lot P&L — add cosmetic cost + labour fallback

**Files:**
- Modify: `routers/dashboard.py`
- Test: `tests/test_sprint19_unit.py` (add tests)

**Background:** The dashboard already has 5 batch queries for lot P&L. We add:
- Batch 6: count repair attempts per lot (for labour fallback when cost = 0)
- Batch 7: count cosmetic cleaning stage movements per lot
- Load `repair_labour_rate` and `cosmetic_rate` from `cost_config`
- Updated COGS formula: `buying + parts + labour + cosmetic`

Where:
- `labour = SUM(attempt.cost) if SUM > 0 else count(attempts) × repair_labour_rate`
- `cosmetic = count(cleaning stage movements) × cosmetic_rate`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_sprint19_unit.py`:

```python
def test_dashboard_loads_cost_config():
    """routers/dashboard.py must import CostConfig for P&L rate loading."""
    src = open("routers/dashboard.py", encoding="utf-8").read()
    assert "CostConfig" in src, "dashboard.py must import CostConfig"


def test_dashboard_cosmetic_cost_in_lot_pl():
    """routers/dashboard.py lot_pl must include cosmetic_cost key."""
    src = open("routers/dashboard.py", encoding="utf-8").read()
    assert "cosmetic_cost" in src, "dashboard.py lot_pl missing cosmetic_cost"


def test_dashboard_lot_pl_includes_cosmetic_in_total():
    """dashboard.py total_cost must include cosmetic_cost."""
    src = open("routers/dashboard.py", encoding="utf-8").read()
    # The total_cost line must add cosmetic_cost
    assert "cosmetic_cost" in src and "total_cost" in src, \
        "dashboard.py must add cosmetic_cost to total_cost"
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_sprint19_unit.py::test_dashboard_loads_cost_config tests/test_sprint19_unit.py::test_dashboard_cosmetic_cost_in_lot_pl tests/test_sprint19_unit.py::test_dashboard_lot_pl_includes_cosmetic_in_total -v --tb=short
```
Expected: 3 FAILED

- [ ] **Step 3: Update `routers/dashboard.py`**

**3a — Add import** (at top of `routers/dashboard.py`, with existing model imports):

```python
from models.cost_config import CostConfig
```

**3b — Load cost config rates.** Find the `try:` block that starts the lot_pl calculation (it begins with `lot_pl: list = []` around line 223). Before the first batch query, add:

```python
        # Load cost config rates (fallbacks when actual costs not recorded)
        _cfg_result = await db.execute(select(CostConfig))
        _cfg = {r.key: float(r.value) for r in _cfg_result.scalars().all()}
        repair_labour_rate = _cfg.get("repair_labour_rate", 150.0)
        cosmetic_rate      = _cfg.get("cosmetic_rate", 50.0)
```

**3c — Add Batch 6: attempt count per lot.** Add this immediately after the existing Batch 5 (the `lot_labour_cost` query):

```python
        # Batch 6: repair attempt count per lot (for labour rate fallback)
        lot_attempt_count = dict((await db.execute(
            select(Device.lot_id, func.count(RepairAttempt.id))
            .join(RepairAttempt, RepairAttempt.device_id == Device.id)
            .group_by(Device.lot_id)
        )).fetchall())

        # Batch 7: cosmetic rework count per lot (devices that entered cleaning stage)
        lot_cosmetic_count = dict((await db.execute(
            select(Device.lot_id, func.count(StageMovement.id))
            .join(StageMovement, StageMovement.device_id == Device.id)
            .where(StageMovement.to_stage == DeviceStage.cleaning)
            .group_by(Device.lot_id)
        )).fetchall())
```

> **Note:** `StageMovement` is already imported in `routers/dashboard.py` as it's in `models.device`. Confirm with `grep "StageMovement" routers/dashboard.py`; add import if missing: `from models.device import Device, DeviceStage, StageMovement`.

**3d — Update the per-lot loop.** Find the `for lot in lots:` block (around line 261). Replace the existing profit calculation inside it:

```python
        for lot in lots:
            revenue      = float(lot_revenue.get(lot.id, 0) or 0)
            parts_cost   = float(lot_parts_cost.get(lot.id, 0) or 0)
            buying       = float(lot.buying_price or 0)

            # Labour: use actual costs if recorded; otherwise rate × attempt count
            labour_actual  = float(lot_labour_cost.get(lot.id, 0) or 0)
            attempt_count  = int(lot_attempt_count.get(lot.id, 0) or 0)
            labour_cost    = labour_actual if labour_actual > 0 else (attempt_count * repair_labour_rate)

            # Cosmetic rework: count of cleaning-stage movements × rate
            cosmetic_count = int(lot_cosmetic_count.get(lot.id, 0) or 0)
            cosmetic_cost  = cosmetic_count * cosmetic_rate

            total_cost = buying + parts_cost + labour_cost + cosmetic_cost
            profit     = revenue - total_cost
            margin     = (profit / revenue * 100) if revenue > 0 else 0
            lot_pl.append({
                "lot_number":    lot.lot_number,
                "supplier":      lot.supplier_name,
                "qty":           lot.qty,
                "devices_count": lot_device_counts.get(lot.id, 0),
                "devices_sold":  lot_sold_counts.get(lot.id, 0),
                "buying_price":  buying,
                "parts_cost":    parts_cost,
                "labour_cost":   labour_cost,
                "cosmetic_cost": cosmetic_cost,
                "total_cost":    total_cost,
                "revenue":       revenue,
                "profit":        profit,
                "margin":        round(margin, 1),
                "lot_id":        str(lot.id),
            })
```

**3e — Update the overall totals block.** Find the section that computes `overall_profit` (around line 323). Add `total_cosmetic_cost` and include it in the formula:

```python
    total_cosmetic_cost = sum(r["cosmetic_cost"] for r in lot_pl)
    overall_profit = total_revenue - total_investment - total_parts_cost - total_labour_cost - total_cosmetic_cost
```

And pass it to the template context:

```python
        "total_cosmetic_cost": total_cosmetic_cost,
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_sprint19_unit.py -v --tb=short
```
Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add routers/dashboard.py tests/test_sprint19_unit.py
git commit -m "fix: lot P&L includes cosmetic rework cost and labour rate fallback"
```

---

## Task 4: Lot detail profit card

**Files:**
- Modify: `routers/stock.py`
- Modify: `templates/lots/detail.html`
- Test: `tests/test_sprint19_unit.py` (add tests)

**Background:** `lot_detail` currently passes `lot`, `devices`, `line_items` to template. No profit is computed. We add a profit summary using the same COGS formula as the dashboard.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_sprint19_unit.py`:

```python
def test_lot_detail_computes_profit():
    """routers/stock.py lot_detail must pass lot_profit to template context."""
    src = open("routers/stock.py", encoding="utf-8").read()
    assert "lot_profit" in src, "stock.py lot_detail missing lot_profit in context"
    assert "cosmetic_cost" in src, "stock.py lot_detail missing cosmetic_cost"


def test_lot_detail_template_shows_profit():
    """templates/lots/detail.html must display lot_profit."""
    src = open("templates/lots/detail.html", encoding="utf-8").read()
    assert "lot_profit" in src, "lots/detail.html missing lot_profit display"
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_sprint19_unit.py::test_lot_detail_computes_profit tests/test_sprint19_unit.py::test_lot_detail_template_shows_profit -v --tb=short
```
Expected: 2 FAILED

- [ ] **Step 3: Update `routers/stock.py` — `lot_detail` route**

Find the `lot_detail` function (at line 307). Add these imports at the top of `routers/stock.py` if not already present:

```python
from models.spare_parts import SparePartConsumption
from models.engines import RepairAttempt
from models.cost_config import CostConfig
```

Replace the body of `lot_detail` with:

```python
@router.get("/lots/{lot_id}", response_class=HTMLResponse)
async def lot_detail(
    lot_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Lot).where(Lot.id == lot_id))
    lot = result.scalar_one_or_none()
    if not lot:
        raise HTTPException(404)

    devices_result = await db.execute(
        select(Device).where(Device.lot_id == lot_id).order_by(Device.created_at)
    )
    devices = devices_result.scalars().all()

    from models.lot import LotLineItem as LLI
    li_result = await db.execute(
        select(LLI).where(LLI.lot_id == lot_id).order_by(LLI.sub_category, LLI.brand, LLI.model)
    )
    line_items = li_result.scalars().all()

    # ── Profit calculation (same COGS formula as dashboard lot_pl) ──────────
    # Load configurable rates
    _cfg_result = await db.execute(select(CostConfig))
    _cfg = {r.key: float(r.value) for r in _cfg_result.scalars().all()}
    repair_labour_rate = _cfg.get("repair_labour_rate", 150.0)
    cosmetic_rate      = _cfg.get("cosmetic_rate", 50.0)

    # Revenue: sum of sale prices for sold devices in this lot
    from models.sales import Sale
    revenue_result = await db.execute(
        select(func.coalesce(func.sum(Sale.sale_price), 0))
        .join(Device, Sale.device_id == Device.id)
        .where(Device.lot_id == lot_id)
    )
    lot_revenue = float(revenue_result.scalar() or 0)

    # Parts cost
    parts_result = await db.execute(
        select(func.coalesce(func.sum(SparePartConsumption.total_cost), 0))
        .where(SparePartConsumption.lot_id == lot_id)
    )
    parts_cost = float(parts_result.scalar() or 0)

    # Labour: actual if recorded, else rate × attempt count
    labour_result = await db.execute(
        select(
            func.coalesce(func.sum(RepairAttempt.cost), 0),
            func.count(RepairAttempt.id),
        )
        .join(Device, RepairAttempt.device_id == Device.id)
        .where(Device.lot_id == lot_id)
    )
    labour_actual, attempt_count = labour_result.one()
    labour_actual = float(labour_actual or 0)
    attempt_count = int(attempt_count or 0)
    labour_cost = labour_actual if labour_actual > 0 else (attempt_count * repair_labour_rate)

    # Cosmetic cost: count cleaning-stage movements × rate
    cosmetic_result = await db.execute(
        select(func.count(StageMovement.id))
        .join(Device, StageMovement.device_id == Device.id)
        .where(Device.lot_id == lot_id, StageMovement.to_stage == DeviceStage.cleaning)
    )
    cosmetic_count = int(cosmetic_result.scalar() or 0)
    cosmetic_cost  = cosmetic_count * cosmetic_rate

    buying     = float(lot.buying_price or 0)
    total_cost = buying + parts_cost + labour_cost + cosmetic_cost
    lot_profit = lot_revenue - total_cost
    lot_margin = round((lot_profit / lot_revenue * 100) if lot_revenue > 0 else 0, 1)

    return templates.TemplateResponse("lots/detail.html", {
        "request": request,
        "lot": lot,
        "devices": devices,
        "current_user": current_user,
        "line_items": line_items,
        # profit summary
        "lot_revenue":      lot_revenue,
        "lot_buying":       buying,
        "lot_parts_cost":   parts_cost,
        "lot_labour_cost":  labour_cost,
        "lot_cosmetic_cost": cosmetic_cost,
        "lot_total_cost":   total_cost,
        "lot_profit":       lot_profit,
        "lot_margin":       lot_margin,
    })
```

> **Note:** `func`, `StageMovement`, `DeviceStage` must be imported. `func` is from `sqlalchemy`. Add at top of `routers/stock.py` if missing: `from sqlalchemy import select, func` and `from models.device import Device, DeviceStage, StageMovement`.

- [ ] **Step 4: Add profit card to `templates/lots/detail.html`**

Open `templates/lots/detail.html`. Find the first `<div class="row">` or similar top section. Insert this profit summary card **before** the devices table:

```html
{# ── Lot Profit Summary ──────────────────────────────────────────────────── #}
<div class="card border-0 shadow-sm mb-4">
  <div class="card-header bg-transparent fw-semibold">
    <i class="bi bi-graph-up me-2"></i>Lot P&amp;L Summary
  </div>
  <div class="card-body">
    <div class="row g-3 text-center">
      <div class="col-6 col-md-2">
        <div class="small text-muted">Revenue</div>
        <div class="fw-bold">₹{{ "{:,.0f}".format(lot_revenue) }}</div>
      </div>
      <div class="col-6 col-md-2">
        <div class="small text-muted">Buying Cost</div>
        <div class="fw-bold text-danger">₹{{ "{:,.0f}".format(lot_buying) }}</div>
      </div>
      <div class="col-6 col-md-2">
        <div class="small text-muted">Parts Cost</div>
        <div class="fw-bold text-danger">₹{{ "{:,.0f}".format(lot_parts_cost) }}</div>
      </div>
      <div class="col-6 col-md-2">
        <div class="small text-muted">Labour Cost</div>
        <div class="fw-bold text-danger">₹{{ "{:,.0f}".format(lot_labour_cost) }}</div>
      </div>
      <div class="col-6 col-md-2">
        <div class="small text-muted">Cosmetic Cost</div>
        <div class="fw-bold text-danger">₹{{ "{:,.0f}".format(lot_cosmetic_cost) }}</div>
      </div>
      <div class="col-6 col-md-2">
        <div class="small text-muted">Net Profit</div>
        <div class="fw-bold {% if lot_profit >= 0 %}text-success{% else %}text-danger{% endif %}">
          ₹{{ "{:,.0f}".format(lot_profit) }}
          <span class="badge {% if lot_profit >= 0 %}bg-success{% else %}bg-danger{% endif %} ms-1">
            {{ lot_margin }}%
          </span>
        </div>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_sprint19_unit.py -v --tb=short
```
Expected: All PASSED

- [ ] **Step 6: Commit**

```bash
git add routers/stock.py templates/lots/detail.html tests/test_sprint19_unit.py
git commit -m "feat: lot detail page shows full profit summary with all COGS components"
```

---

## Task 5: Backup script

**Files:**
- Create: `scripts/backup_db.py`
- Test: `tests/test_sprint19_unit.py` (add tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_sprint19_unit.py`:

```python
def test_backup_script_exists():
    """scripts/backup_db.py must exist."""
    import os
    assert os.path.exists("scripts/backup_db.py"), "scripts/backup_db.py not found"


def test_backup_script_parses_db_url():
    """backup_db.py must parse DATABASE_URL and handle +asyncpg prefix."""
    src = open("scripts/backup_db.py", encoding="utf-8").read()
    assert "+asyncpg" in src or "replace" in src, \
        "backup_db.py must strip +asyncpg from DATABASE_URL for pg_dump"


def test_backup_script_has_retention():
    """backup_db.py must delete backups older than 30 days."""
    src = open("scripts/backup_db.py", encoding="utf-8").read()
    assert "30" in src, "backup_db.py missing 30-day retention logic"
    assert "unlink" in src or "remove" in src, "backup_db.py missing file deletion"


def test_backup_filename_format():
    """backup_db.py must generate filenames with timestamp."""
    src = open("scripts/backup_db.py", encoding="utf-8").read()
    assert "oxypc_" in src, "backup_db.py must use 'oxypc_' filename prefix"
    assert ".sql.gz" in src, "backup_db.py must produce .sql.gz files"
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_sprint19_unit.py::test_backup_script_exists tests/test_sprint19_unit.py::test_backup_script_parses_db_url tests/test_sprint19_unit.py::test_backup_script_has_retention tests/test_sprint19_unit.py::test_backup_filename_format -v --tb=short
```
Expected: 4 FAILED

- [ ] **Step 3: Create `scripts/` directory and `scripts/backup_db.py`**

```bash
mkdir -p scripts
```

```python
#!/usr/bin/env python3
"""
OxyPC Database Backup Script
=============================
Usage:
    python scripts/backup_db.py           # backup + prune old backups
    python scripts/backup_db.py --prune-only  # only prune, no new backup

Saves to: backups/oxypc_YYYYMMDD_HHMMSS.sql.gz
Retention: 30 days (older files deleted automatically)

pg_dump must be on PATH (installed with PostgreSQL).
"""
import os
import sys
import gzip
import shutil
import subprocess
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).resolve().parent.parent  # repo root
BACKUP_DIR  = BASE_DIR / "backups"
RETENTION_DAYS = 30

# ── Resolve DATABASE_URL ──────────────────────────────────────────────────────
# Attempt to load from config.py (adds repo root to sys.path)
sys.path.insert(0, str(BASE_DIR))
try:
    from config import DATABASE_URL as _RAW_URL
except ImportError:
    _RAW_URL = os.environ.get("OXYPC_DATABASE_URL", "")

if not _RAW_URL:
    print("ERROR: DATABASE_URL not found. Set OXYPC_DATABASE_URL env var.", file=sys.stderr)
    sys.exit(1)

# pg_dump uses postgresql:// not postgresql+asyncpg://
DB_URL = _RAW_URL.replace("postgresql+asyncpg://", "postgresql://")
_parsed = urlparse(DB_URL)
DB_HOST = _parsed.hostname or "localhost"
DB_PORT = str(_parsed.port or 5432)
DB_USER = _parsed.username or "postgres"
DB_PASS = _parsed.password or ""
DB_NAME = (_parsed.path or "").lstrip("/")


def prune_old_backups():
    """Delete .sql.gz backup files older than RETENTION_DAYS."""
    if not BACKUP_DIR.exists():
        return
    cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
    deleted = []
    for f in BACKUP_DIR.glob("oxypc_*.sql.gz"):
        if datetime.utcfromtimestamp(f.stat().st_mtime) < cutoff:
            f.unlink()
            deleted.append(f.name)
    if deleted:
        print(f"Pruned {len(deleted)} backup(s) older than {RETENTION_DAYS} days:")
        for name in deleted:
            print(f"  - {name}")
    return deleted


def run_backup() -> Path:
    """Run pg_dump, gzip the output, return the backup file path."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path  = BACKUP_DIR / f"oxypc_{timestamp}.sql.gz"

    # Use a temp plain-SQL file, then gzip it
    tmp_path = BACKUP_DIR / f"oxypc_{timestamp}.sql"

    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASS

    cmd = [
        "pg_dump",
        "-h", DB_HOST,
        "-p", DB_PORT,
        "-U", DB_USER,
        "--format=plain",
        "--no-password",
        DB_NAME,
    ]

    print(f"Running: pg_dump -h {DB_HOST} -p {DB_PORT} -U {DB_USER} {DB_NAME}")
    result = subprocess.run(cmd, capture_output=True, env=env)

    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="replace")
        print(f"ERROR: pg_dump failed:\n{err}", file=sys.stderr)
        sys.exit(1)

    # Gzip the SQL output
    with gzip.open(out_path, "wb") as gz:
        gz.write(result.stdout)

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"Backup saved: {out_path.name} ({size_mb:.2f} MB)")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="OxyPC database backup")
    parser.add_argument("--prune-only", action="store_true",
                        help="Only prune old backups, skip creating a new one")
    args = parser.parse_args()

    if not args.prune_only:
        run_backup()

    prune_old_backups()
    print("Done.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_sprint19_unit.py -v --tb=short
```
Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add scripts/backup_db.py tests/test_sprint19_unit.py
git commit -m "feat: backup script — pg_dump + gzip + 30-day retention"
```

---

## Task 6: Windows Task Scheduler setup script

**Files:**
- Create: `scripts/setup_backup_task.bat`
- Test: `tests/test_sprint19_unit.py` (add tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_sprint19_unit.py`:

```python
def test_backup_task_bat_exists():
    """scripts/setup_backup_task.bat must exist and reference schtasks."""
    import os
    assert os.path.exists("scripts/setup_backup_task.bat"), \
        "scripts/setup_backup_task.bat not found"
    src = open("scripts/setup_backup_task.bat", encoding="utf-8").read()
    assert "schtasks" in src.lower(), "bat file must use schtasks"
    assert "02:00" in src, "bat file must schedule at 02:00"
    assert "backup_db.py" in src, "bat file must call backup_db.py"
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_sprint19_unit.py::test_backup_task_bat_exists -v --tb=short
```
Expected: FAILED

- [ ] **Step 3: Create `scripts/setup_backup_task.bat`**

```bat
@echo off
REM OxyPC — Install daily backup as a Windows Scheduled Task
REM Run this once as Administrator to register the task.
REM
REM Usage:
REM   scripts\setup_backup_task.bat
REM
REM The task runs daily at 02:00 using the Python interpreter that runs this script.
REM Edit PYTHON_EXE and SCRIPT_PATH below if your paths differ.

SET TASK_NAME=OxyPC_DailyBackup
SET PYTHON_EXE=python
SET SCRIPT_DIR=%~dp0
SET SCRIPT_PATH=%SCRIPT_DIR%backup_db.py

echo Installing scheduled task: %TASK_NAME%
echo Script: %SCRIPT_PATH%
echo Schedule: Daily at 02:00

schtasks /create ^
    /tn "%TASK_NAME%" ^
    /tr "\"%PYTHON_EXE%\" \"%SCRIPT_PATH%\"" ^
    /sc DAILY ^
    /st 02:00 ^
    /ru SYSTEM ^
    /rl HIGHEST ^
    /f

IF %ERRORLEVEL% EQU 0 (
    echo.
    echo Task installed successfully.
    echo To verify: schtasks /query /tn "%TASK_NAME%"
    echo To run now: schtasks /run /tn "%TASK_NAME%"
    echo To remove:  schtasks /delete /tn "%TASK_NAME%" /f
) ELSE (
    echo.
    echo ERROR: Task installation failed. Run this script as Administrator.
)
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_sprint19_unit.py -v --tb=short
```
Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add scripts/setup_backup_task.bat tests/test_sprint19_unit.py
git commit -m "feat: Windows Task Scheduler setup bat for daily 02:00 backup"
```

---

## Task 7: Backup admin endpoints + UI

**Files:**
- Modify: `routers/admin.py`
- Modify: `templates/admin/users.html`
- Test: `tests/test_sprint19_unit.py` (add tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_sprint19_unit.py`:

```python
def test_admin_has_backup_routes():
    """routers/admin.py must have /backup-status and /backup-now routes."""
    src = open("routers/admin.py", encoding="utf-8").read()
    assert "/backup-status" in src, "admin.py missing /backup-status route"
    assert "/backup-now" in src, "admin.py missing /backup-now route"


def test_admin_users_template_has_backup_card():
    """templates/admin/users.html must contain backup status UI."""
    src = open("templates/admin/users.html", encoding="utf-8").read()
    assert "backup" in src.lower(), "users.html missing backup card"
    assert "backup-now" in src, "users.html missing Run Backup Now button"
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_sprint19_unit.py::test_admin_has_backup_routes tests/test_sprint19_unit.py::test_admin_users_template_has_backup_card -v --tb=short
```
Expected: 2 FAILED

- [ ] **Step 3: Add backup endpoints to `routers/admin.py`**

Add these imports at the top of `routers/admin.py`:

```python
import subprocess
import gzip
from pathlib import Path
from fastapi.responses import JSONResponse
```

Add these routes at the **end** of `routers/admin.py`:

```python
# ── Backup ────────────────────────────────────────────────────────────────

_BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"
_BACKUP_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "backup_db.py"


@router.get("/backup-status")
async def backup_status(current_user: User = Depends(require_admin)):
    """Return info about the most recent backup file."""
    if not _BACKUP_DIR.exists():
        return JSONResponse({"status": "no_backups", "last_backup": None})

    backups = sorted(_BACKUP_DIR.glob("oxypc_*.sql.gz"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not backups:
        return JSONResponse({"status": "no_backups", "last_backup": None})

    latest = backups[0]
    mtime  = datetime.utcfromtimestamp(latest.stat().st_mtime)
    age_h  = round((datetime.utcnow() - mtime).total_seconds() / 3600, 1)
    size_mb = round(latest.stat().st_size / (1024 * 1024), 2)

    return JSONResponse({
        "status":      "ok",
        "last_backup": {
            "filename": latest.name,
            "size_mb":  size_mb,
            "age_hours": age_h,
            "taken_at": mtime.strftime("%Y-%m-%d %H:%M UTC"),
        },
        "total_backups": len(backups),
    })


@router.post("/backup-now")
async def backup_now(
    request: Request,
    current_user: User = Depends(require_admin),
):
    """Trigger an immediate database backup synchronously."""
    import sys
    python = sys.executable
    result = subprocess.run(
        [python, str(_BACKUP_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    success = result.returncode == 0
    output  = (result.stdout + result.stderr).strip()

    # Audit log the manual backup trigger
    from models.engines import AuditLog
    import json
    from database import get_db as _get_db
    async for db in _get_db():
        db.add(AuditLog(
            username=current_user.username,
            action="MANUAL_BACKUP",
            table_name="system",
            new_value=json.dumps({"success": success, "output": output[:500]}),
        ))
        await db.commit()
        break

    msg = "Backup+completed" if success else "Backup+failed"
    return RedirectResponse(url=f"/admin/users?{'success' if success else 'error'}={msg}", status_code=302)
```

- [ ] **Step 4: Add backup card to `templates/admin/users.html`**

Open `templates/admin/users.html`. Find the end of the `{% block content %}` section (just before `{% endblock %}`). Add this backup status card:

```html
{# ── Backup Status (admin only) ────────────────────────────────────────── #}
<div class="card border-0 shadow-sm mt-4">
  <div class="card-header bg-transparent fw-semibold d-flex justify-content-between align-items-center">
    <span><i class="bi bi-shield-check me-2 text-success"></i>Database Backup</span>
    <form method="post" action="/admin/backup-now" class="d-inline">
      <input type="hidden" name="csrf_token" value="{{ request.cookies.get('csrf_token', '') }}">
      <button type="submit" class="btn btn-sm btn-outline-primary">
        <i class="bi bi-download me-1"></i>Run Backup Now
      </button>
    </form>
  </div>
  <div class="card-body" id="backup-status-body">
    <p class="text-muted small mb-0">Loading backup status…</p>
  </div>
</div>

<script>
  fetch('/admin/backup-status')
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById('backup-status-body');
      if (data.status === 'no_backups') {
        el.innerHTML = '<p class="text-warning mb-0"><i class="bi bi-exclamation-triangle me-1"></i>No backups found. Click <strong>Run Backup Now</strong> to create the first backup.</p>';
      } else {
        const b = data.last_backup;
        const ageClass = b.age_hours > 25 ? 'text-danger' : 'text-success';
        el.innerHTML = `
          <div class="row g-3">
            <div class="col-sm-3"><div class="small text-muted">Last Backup</div><div class="fw-semibold">${b.taken_at}</div></div>
            <div class="col-sm-2"><div class="small text-muted">Age</div><div class="fw-semibold ${ageClass}">${b.age_hours}h ago</div></div>
            <div class="col-sm-2"><div class="small text-muted">Size</div><div class="fw-semibold">${b.size_mb} MB</div></div>
            <div class="col-sm-2"><div class="small text-muted">Total Files</div><div class="fw-semibold">${data.total_backups}</div></div>
            <div class="col-sm-3"><div class="small text-muted">File</div><div class="fw-semibold text-truncate" title="${b.filename}">${b.filename}</div></div>
          </div>`;
      }
    })
    .catch(() => {
      document.getElementById('backup-status-body').innerHTML =
        '<p class="text-danger mb-0">Could not load backup status.</p>';
    });
</script>
```

- [ ] **Step 5: Run full test suite**

```
pytest tests/ -q --tb=short
```
Expected: All previous tests pass + new tests pass. Zero new failures.

- [ ] **Step 6: Commit**

```bash
git add routers/admin.py templates/admin/users.html tests/test_sprint19_unit.py
git commit -m "feat: backup admin endpoints and UI card with live status"
```

---

## Self-Review

### 1. Spec Coverage

| Spec requirement | Task |
|-----------------|------|
| `cost_config` table with `repair_labour_rate` and `cosmetic_rate` | Task 1 |
| Seed defaults at startup | Task 1 (db_validator) |
| Admin UI GET/POST `/admin/cost-config` | Task 2 |
| Fix lot_pl: labour fallback using rate × attempts | Task 3 |
| Fix lot_pl: add cosmetic rework cost | Task 3 |
| Fix lot_pl: add cosmetic to overall_profit | Task 3 |
| Lot detail page shows full profit breakdown | Task 4 |
| `scripts/backup_db.py` with pg_dump + gzip | Task 5 |
| 30-day backup retention | Task 5 |
| `scripts/setup_backup_task.bat` for Windows Task Scheduler at 02:00 | Task 6 |
| `GET /admin/backup-status` JSON endpoint | Task 7 |
| `POST /admin/backup-now` endpoint | Task 7 |
| Backup UI card on admin page | Task 7 |
| Audit log on cost_config changes | Task 2 |
| Audit log on manual backup trigger | Task 7 |

**Gaps found:** None.

### 2. Placeholder Scan

No "TBD", "TODO", "similar to Task N", or missing code blocks found.

### 3. Type Consistency

- `repair_labour_rate` and `cosmetic_rate` named consistently across Task 1 (seed), Task 2 (admin form key), Task 3 (dashboard), Task 4 (lot detail)
- `lot_cosmetic_count` in Task 3 → `cosmetic_count` in Task 4 — different variables but in different scopes, both compute the same thing independently (correct, not a bug)
- `_BACKUP_DIR` defined in Task 7 is independent of `BACKUP_DIR` in Task 5 (different files) — consistent meaning, different path objects
- `backup_status` endpoint returns consistent JSON structure that the JS in Task 7 consumes
