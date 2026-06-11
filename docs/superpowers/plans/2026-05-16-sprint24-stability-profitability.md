# Sprint 24 — Operational Stability + Commercial Accuracy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate server-death risk (Windows Service + nightly backup), add a Lot Profitability Calculator with ACCEPT / RENEGOTIATE / DECLINE verdicts, and complete audit trail coverage on the 3 CRM write operations that have no audit logging.

**Architecture:** Four independent workstreams. (1) NSSM wraps uvicorn as a Windows Service so it auto-restarts on crash and survives reboots without a terminal window. (2) pg_dump PowerShell script registered in Task Scheduler runs nightly at 02:00 AM with 30-day file rotation. (3) `LotProfitabilityEstimate` model + pure-Python `profitability_engine` service (Python Decimal) compute 5-category cost totals, grade-yield revenue mix, GM%, profit/unit, ROI%, and a 3-band verdict vs a `CostConfig` margin floor — all estimates are versioned and immutable (new row per recalculation). (4) `audit()` calls added to CRM contact bulk-import, CRM single-contact create, and CRM activity log — the 3 remaining high-volume write paths with no audit trail.

**Tech Stack:** FastAPI async, SQLAlchemy 2.x asyncio, asyncpg, Alembic, Jinja2, Bootstrap 5, Python `decimal.Decimal` for financial math, NSSM 2.24 (downloaded as part of task), PowerShell + Windows Task Scheduler, `pg_dump` (PostgreSQL 14+), existing `CostConfig` model (`models/cost_config.py`), existing `audit()` function (`services/audit_engine.py`).

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `scripts/install_service.ps1` | Downloads NSSM 2.24, installs OxyPCInventory Windows Service |
| Create | `scripts/start_server.bat` | Wrapper invoked by NSSM — activates venv + starts uvicorn |
| Create | `scripts/backup_db.ps1` | Nightly pg_dump with 30-day file rotation |
| Create | `tests/conftest.py` | Minimal pytest fixtures (event loop) — enables all TDD |
| Create | `tests/test_sprint24_unit.py` | TDD tests for `compute_profitability()` |
| Create | `models/lot_profitability.py` | `LotProfitabilityEstimate` SQLAlchemy model |
| Create | `services/profitability_engine.py` | Pure `compute_profitability()` function (no DB) |
| Create | `routers/lot_profitability.py` | `GET /lots/{id}/profitability` + `POST /lots/{id}/profitability` |
| Create | `templates/lots/profitability.html` | Calculator form + results card + version history table |
| Create | `alembic/versions/20260516_1000_lot_profitability.py` | Migration: `lot_profitability_estimates` table |
| Modify | `models/__init__.py` | Add `LotProfitabilityEstimate` import |
| Modify | `main.py` | Include `lot_profitability` router |
| Modify | `routers/admin.py` | Add `lot_gm_floor_pct` to `COST_CONFIG_DEFS` |
| Modify | `templates/lots/detail.html` | Add "Profitability Check" button |
| Modify | `routers/crm_contacts.py` | Add `audit()` to bulk-upload POST and single-create POST |
| Modify | `routers/crm_activities.py` | Add `audit()` to activity log POST |

---

## Task 1: Test Infrastructure (conftest.py)

**Files:**
- Create: `tests/conftest.py`

- [ ] **Step 1: Create conftest.py**

```python
# tests/conftest.py
import asyncio
import pytest


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop so async tests share one loop."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()
```

- [ ] **Step 2: Verify pytest collects with no errors**

Run from `C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory`:
```
.\venv\Scripts\python.exe -m pytest tests/ -v --collect-only
```
Expected: collection succeeds (existing test files listed, no import errors).

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add conftest.py with session-scoped event loop"
```

---

## Task 2: Profitability Engine — TDD

**Files:**
- Create: `services/profitability_engine.py`
- Create: `tests/test_sprint24_unit.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sprint24_unit.py
"""
Unit tests for services/profitability_engine.py
All tests are synchronous — no DB, no FastAPI.
"""
from decimal import Decimal
import pytest


def test_import():
    """Engine module must be importable before implementation."""
    from services import profitability_engine  # noqa


def test_accept_verdict():
    """Buying ₹100k lot, 50 units all grade-B @₹4000, plus ₹22k non-buying costs.
    total_cost=₹122k, revenue=₹200k, GM=39% > 25% floor → ACCEPT."""
    from services.profitability_engine import compute_profitability
    result = compute_profitability(
        buying_price=100_000,
        transport_cost=5_000,
        labour_per_device=100,
        parts_per_device=200,
        overhead_cost=2_000,
        qty=50,
        grade_yield={"a": 0, "b": 100, "c": 0, "d": 0, "scrap": 0},
        grade_price={"a": 0, "b": 4_000, "c": 0, "d": 0, "scrap": 0},
        gm_floor_pct=25.0,
    )
    assert result["verdict"] == "ACCEPT"
    assert result["total_cost"] == Decimal("122000.00")
    assert result["expected_revenue"] == Decimal("200000.00")
    assert result["gross_margin_pct"] > Decimal("25")
    assert result["max_bid_price"] is None


def test_decline_verdict():
    """Costs exceed revenue → DECLINE."""
    from services.profitability_engine import compute_profitability
    result = compute_profitability(
        buying_price=200_000,
        transport_cost=10_000,
        labour_per_device=500,
        parts_per_device=500,
        overhead_cost=5_000,
        qty=50,
        grade_yield={"a": 0, "b": 100, "c": 0, "d": 0, "scrap": 0},
        grade_price={"a": 0, "b": 3_000, "c": 0, "d": 0, "scrap": 0},
        gm_floor_pct=25.0,
    )
    assert result["verdict"] == "DECLINE"
    assert result["gross_margin_pct"] < Decimal("0")
    assert result["max_bid_price"] is None


def test_renegotiate_verdict_and_max_bid():
    """Profitable but below 25% floor → RENEGOTIATE with max_bid_price.
    total_cost=₹172k, revenue=₹200k, GM=14% → RENEGOTIATE.
    max_bid = 200000 * 0.75 - 22000 = ₹128000."""
    from services.profitability_engine import compute_profitability
    result = compute_profitability(
        buying_price=150_000,
        transport_cost=5_000,
        labour_per_device=100,
        parts_per_device=200,
        overhead_cost=2_000,
        qty=50,
        grade_yield={"a": 0, "b": 100, "c": 0, "d": 0, "scrap": 0},
        grade_price={"a": 0, "b": 4_000, "c": 0, "d": 0, "scrap": 0},
        gm_floor_pct=25.0,
    )
    assert result["verdict"] == "RENEGOTIATE"
    assert result["gross_margin_pct"] >= Decimal("0")
    assert result["max_bid_price"] == Decimal("128000.00")


def test_max_bid_achieves_floor():
    """Buying at max_bid_price should yield a verdict of ACCEPT at exactly the floor."""
    from services.profitability_engine import compute_profitability
    r1 = compute_profitability(
        buying_price=150_000, transport_cost=5_000,
        labour_per_device=100, parts_per_device=200, overhead_cost=2_000,
        qty=50,
        grade_yield={"a": 0, "b": 100, "c": 0, "d": 0, "scrap": 0},
        grade_price={"a": 0, "b": 4_000, "c": 0, "d": 0, "scrap": 0},
        gm_floor_pct=25.0,
    )
    max_bid = float(r1["max_bid_price"])
    r2 = compute_profitability(
        buying_price=max_bid, transport_cost=5_000,
        labour_per_device=100, parts_per_device=200, overhead_cost=2_000,
        qty=50,
        grade_yield={"a": 0, "b": 100, "c": 0, "d": 0, "scrap": 0},
        grade_price={"a": 0, "b": 4_000, "c": 0, "d": 0, "scrap": 0},
        gm_floor_pct=25.0,
    )
    assert r2["verdict"] == "ACCEPT"
    assert abs(r2["gross_margin_pct"] - Decimal("25")) < Decimal("0.02")


def test_mixed_grade_yield():
    """Multi-grade mix: 30%A @5000, 40%B @3500, 20%C @2000, 5%D @1000, 5%scrap @200
    qty=100. Expected revenue=₹336k, total_cost=₹256k, GM=23.8% → RENEGOTIATE."""
    from services.profitability_engine import compute_profitability
    result = compute_profitability(
        buying_price=200_000,
        transport_cost=8_000,
        labour_per_device=150,
        parts_per_device=300,
        overhead_cost=3_000,
        qty=100,
        grade_yield={"a": 30, "b": 40, "c": 20, "d": 5, "scrap": 5},
        grade_price={"a": 5_000, "b": 3_500, "c": 2_000, "d": 1_000, "scrap": 200},
        gm_floor_pct=25.0,
    )
    # revenue = 30*5000 + 40*3500 + 20*2000 + 5*1000 + 5*200 = 336000
    assert result["expected_revenue"] == Decimal("336000.00")
    # cost = 200000 + 8000 + 15000 + 30000 + 3000 = 256000
    assert result["total_cost"] == Decimal("256000.00")
    assert result["verdict"] == "RENEGOTIATE"


def test_zero_revenue_is_decline():
    """All grade prices = 0 → revenue = 0 → DECLINE regardless of costs."""
    from services.profitability_engine import compute_profitability
    result = compute_profitability(
        buying_price=50_000, transport_cost=0,
        labour_per_device=0, parts_per_device=0, overhead_cost=0,
        qty=10,
        grade_yield={"a": 100, "b": 0, "c": 0, "d": 0, "scrap": 0},
        grade_price={"a": 0, "b": 0, "c": 0, "d": 0, "scrap": 0},
        gm_floor_pct=25.0,
    )
    assert result["verdict"] == "DECLINE"
```

- [ ] **Step 2: Run tests — verify they all FAIL with ImportError**

```
.\venv\Scripts\python.exe -m pytest tests/test_sprint24_unit.py -v
```
Expected: `ImportError: cannot import name 'compute_profitability' from 'services.profitability_engine'`

- [ ] **Step 3: Implement profitability_engine.py**

```python
# services/profitability_engine.py
"""
Profitability Engine
--------------------
Pure function — no database, no FastAPI.
Uses Decimal for exact financial arithmetic.

Usage:
    from services.profitability_engine import compute_profitability
    result = compute_profitability(
        buying_price=100000, transport_cost=5000,
        labour_per_device=100, parts_per_device=200, overhead_cost=2000,
        qty=50,
        grade_yield={"a": 0, "b": 100, "c": 0, "d": 0, "scrap": 0},
        grade_price={"a": 0, "b": 4000, "c": 0, "d": 0, "scrap": 0},
        gm_floor_pct=25.0,
    )
    # result["verdict"]  →  "ACCEPT" | "RENEGOTIATE" | "DECLINE"
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import TypedDict


GRADES = ("a", "b", "c", "d", "scrap")
_CENT = Decimal("0.01")
_FOUR = Decimal("0.0001")


class ProfitabilityResult(TypedDict):
    total_cost: Decimal
    expected_revenue: Decimal
    gross_margin_pct: Decimal   # e.g. Decimal("25.3456")
    profit_per_unit: Decimal
    roi_pct: Decimal
    verdict: str                # ACCEPT / RENEGOTIATE / DECLINE
    max_bid_price: Decimal | None  # only set for RENEGOTIATE


def compute_profitability(
    buying_price: float,
    transport_cost: float,
    labour_per_device: float,
    parts_per_device: float,
    overhead_cost: float,
    qty: int,
    grade_yield: dict,   # keys: a/b/c/d/scrap, values: % (0–100), must sum to 100
    grade_price: dict,   # keys: a/b/c/d/scrap, values: price per unit in Rs
    gm_floor_pct: float,
) -> ProfitabilityResult:
    """
    Compute lot profitability from 5 cost categories + grade yield mix.

    Five cost categories (per CLAUDE.md Pre-Commitment Profitability Gate):
      1. Acquisition     — buying_price
      2. Transport       — transport_cost
      3. Processing      — labour_per_device × qty
      4. Processing      — parts_per_device × qty
      5. Loss/Risk adj.  — overhead_cost

    Returns a ProfitabilityResult dict with verdict and all computed metrics.
    """
    qty_d = Decimal(str(qty))

    # ── 5 cost categories ─────────────────────────────────────────────────
    labour_total = Decimal(str(labour_per_device)) * qty_d
    parts_total  = Decimal(str(parts_per_device))  * qty_d
    total_cost = (
        Decimal(str(buying_price))
        + Decimal(str(transport_cost))
        + labour_total
        + parts_total
        + Decimal(str(overhead_cost))
    ).quantize(_CENT, ROUND_HALF_UP)

    # ── Grade-yield revenue ────────────────────────────────────────────────
    expected_revenue = Decimal("0")
    for grade in GRADES:
        yld   = Decimal(str(grade_yield.get(grade, 0)))
        price = Decimal(str(grade_price.get(grade, 0)))
        units = (yld / Decimal("100")) * qty_d
        expected_revenue += units * price
    expected_revenue = expected_revenue.quantize(_CENT, ROUND_HALF_UP)

    # ── Handle zero-revenue edge case ─────────────────────────────────────
    if expected_revenue == Decimal("0"):
        profit_per_unit = (-total_cost / qty_d).quantize(_CENT, ROUND_HALF_UP)
        return ProfitabilityResult(
            total_cost=total_cost,
            expected_revenue=expected_revenue,
            gross_margin_pct=Decimal("-100.0000"),
            profit_per_unit=profit_per_unit,
            roi_pct=Decimal("-100.0000"),
            verdict="DECLINE",
            max_bid_price=None,
        )

    # ── Core metrics ──────────────────────────────────────────────────────
    gross_profit    = expected_revenue - total_cost
    gm_pct          = (gross_profit / expected_revenue * Decimal("100")).quantize(_FOUR, ROUND_HALF_UP)
    profit_per_unit = (gross_profit / qty_d).quantize(_CENT, ROUND_HALF_UP)
    roi_pct         = (
        (gross_profit / total_cost * Decimal("100")).quantize(_FOUR, ROUND_HALF_UP)
        if total_cost > 0 else Decimal("0.0000")
    )

    # ── 3-band verdict ────────────────────────────────────────────────────
    floor = Decimal(str(gm_floor_pct))
    non_buying = (
        Decimal(str(transport_cost))
        + labour_total
        + parts_total
        + Decimal(str(overhead_cost))
    )

    if gm_pct >= floor:
        verdict       = "ACCEPT"
        max_bid_price = None
    elif gm_pct >= Decimal("0"):
        verdict = "RENEGOTIATE"
        # max_bid: buying price at which GM% == floor exactly
        # floor/100 = (revenue - (max_bid + non_buying)) / revenue
        # max_bid = revenue * (1 - floor/100) - non_buying
        max_bid_price = (
            expected_revenue * (Decimal("1") - floor / Decimal("100")) - non_buying
        ).quantize(_CENT, ROUND_HALF_UP)
        max_bid_price = max(Decimal("0"), max_bid_price)
    else:
        verdict       = "DECLINE"
        max_bid_price = None

    return ProfitabilityResult(
        total_cost=total_cost,
        expected_revenue=expected_revenue,
        gross_margin_pct=gm_pct,
        profit_per_unit=profit_per_unit,
        roi_pct=roi_pct,
        verdict=verdict,
        max_bid_price=max_bid_price,
    )
```

- [ ] **Step 4: Run tests — all must pass**

```
.\venv\Scripts\python.exe -m pytest tests/test_sprint24_unit.py -v
```
Expected:
```
test_import                    PASSED
test_accept_verdict            PASSED
test_decline_verdict           PASSED
test_renegotiate_verdict_and_max_bid  PASSED
test_max_bid_achieves_floor    PASSED
test_mixed_grade_yield         PASSED
test_zero_revenue_is_decline   PASSED
7 passed in 0.XXs
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_sprint24_unit.py services/profitability_engine.py
git commit -m "feat: add profitability_engine with TDD — ACCEPT/RENEGOTIATE/DECLINE logic"
```

---

## Task 3: Profitability Model + Migration

**Files:**
- Create: `models/lot_profitability.py`
- Create: `alembic/versions/20260516_1000_lot_profitability.py`
- Modify: `models/__init__.py` (add 1 import line)

- [ ] **Step 1: Create the model**

```python
# models/lot_profitability.py
"""
LotProfitabilityEstimate — immutable snapshot of a profitability calculation.
Every recalculation creates a new row (version increments).
Never update or delete rows in this table.
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Numeric, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class LotProfitabilityEstimate(Base):
    __tablename__ = "lot_profitability_estimates"

    id      = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lot_id  = Column(UUID(as_uuid=True), ForeignKey("lots.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)  # increments per lot

    # ── 5 cost inputs ─────────────────────────────────────────────────────
    buying_price      = Column(Numeric(14, 2), nullable=False)   # Acquisition
    transport_cost    = Column(Numeric(12, 2), nullable=False, default=0)  # Transport
    labour_per_device = Column(Numeric(10, 2), nullable=False, default=0)  # Processing
    parts_per_device  = Column(Numeric(10, 2), nullable=False, default=0)  # Processing (parts)
    overhead_cost     = Column(Numeric(12, 2), nullable=False, default=0)  # Loss/risk
    qty               = Column(Integer, nullable=False)

    # ── Grade yield inputs (percentage, 0-100, all grades must sum to 100) ─
    yield_grade_a  = Column(Numeric(6, 2), nullable=False, default=0)
    yield_grade_b  = Column(Numeric(6, 2), nullable=False, default=0)
    yield_grade_c  = Column(Numeric(6, 2), nullable=False, default=0)
    yield_grade_d  = Column(Numeric(6, 2), nullable=False, default=0)
    yield_scrap    = Column(Numeric(6, 2), nullable=False, default=0)

    # ── Grade price inputs (Rs per unit) ──────────────────────────────────
    price_grade_a  = Column(Numeric(10, 2), nullable=False, default=0)
    price_grade_b  = Column(Numeric(10, 2), nullable=False, default=0)
    price_grade_c  = Column(Numeric(10, 2), nullable=False, default=0)
    price_grade_d  = Column(Numeric(10, 2), nullable=False, default=0)
    price_scrap    = Column(Numeric(10, 2), nullable=False, default=0)

    # ── Computed outputs (stored at calculation time — never recomputed) ──
    total_cost       = Column(Numeric(14, 2), nullable=False)
    expected_revenue = Column(Numeric(14, 2), nullable=False)
    gross_margin_pct = Column(Numeric(8, 4), nullable=False)   # e.g. 25.3456
    profit_per_unit  = Column(Numeric(12, 2), nullable=False)
    roi_pct          = Column(Numeric(8, 4), nullable=False)
    max_bid_price    = Column(Numeric(14, 2), nullable=True)   # only RENEGOTIATE

    # ── Verdict ───────────────────────────────────────────────────────────
    verdict           = Column(String(15), nullable=False)  # ACCEPT / RENEGOTIATE / DECLINE
    gm_floor_applied  = Column(Numeric(6, 2), nullable=False)  # floor % in effect at calc time

    # ── Metadata ──────────────────────────────────────────────────────────
    notes      = Column(Text, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    lot = relationship("Lot", foreign_keys=[lot_id], lazy="select")
```

- [ ] **Step 2: Add to models/__init__.py**

In `models/__init__.py`, add this line after the `from .cost_config import CostConfig` line at the bottom:

```python
from .lot_profitability import LotProfitabilityEstimate
```

- [ ] **Step 3: Create Alembic migration**

```python
# alembic/versions/20260516_1000_lot_profitability.py
"""Add lot_profitability_estimates table and seed lot_gm_floor_pct CostConfig

Revision ID: 20260516_1000
Revises: 20260515_1000
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid
from datetime import datetime

revision = '20260516_1000'
down_revision = '20260515_1000'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'lot_profitability_estimates',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('lot_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('lots.id'), nullable=False, index=True),
        sa.Column('version', sa.Integer, nullable=False, default=1),
        sa.Column('buying_price',      sa.Numeric(14, 2), nullable=False),
        sa.Column('transport_cost',    sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('labour_per_device', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('parts_per_device',  sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('overhead_cost',     sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('qty',               sa.Integer, nullable=False),
        sa.Column('yield_grade_a',  sa.Numeric(6, 2), nullable=False, server_default='0'),
        sa.Column('yield_grade_b',  sa.Numeric(6, 2), nullable=False, server_default='0'),
        sa.Column('yield_grade_c',  sa.Numeric(6, 2), nullable=False, server_default='0'),
        sa.Column('yield_grade_d',  sa.Numeric(6, 2), nullable=False, server_default='0'),
        sa.Column('yield_scrap',    sa.Numeric(6, 2), nullable=False, server_default='0'),
        sa.Column('price_grade_a',  sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('price_grade_b',  sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('price_grade_c',  sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('price_grade_d',  sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('price_scrap',    sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('total_cost',       sa.Numeric(14, 2), nullable=False),
        sa.Column('expected_revenue', sa.Numeric(14, 2), nullable=False),
        sa.Column('gross_margin_pct', sa.Numeric(8, 4),  nullable=False),
        sa.Column('profit_per_unit',  sa.Numeric(12, 2), nullable=False),
        sa.Column('roi_pct',          sa.Numeric(8, 4),  nullable=False),
        sa.Column('max_bid_price',    sa.Numeric(14, 2), nullable=True),
        sa.Column('verdict',          sa.String(15), nullable=False),
        sa.Column('gm_floor_applied', sa.Numeric(6, 2),  nullable=False),
        sa.Column('notes',      sa.Text, nullable=True),
        sa.Column('created_by', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_lot_profitability_lot_id', 'lot_profitability_estimates', ['lot_id'])

    # Seed default GM floor: 25%
    op.execute("""
        INSERT INTO cost_config (id, key, value, description, updated_at)
        VALUES (gen_random_uuid(), 'lot_gm_floor_pct', 25.00,
                'Minimum gross margin % required to ACCEPT a lot purchase. Below this = RENEGOTIATE.',
                NOW())
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade():
    op.drop_index('ix_lot_profitability_lot_id', 'lot_profitability_estimates')
    op.drop_table('lot_profitability_estimates')
    op.execute("DELETE FROM cost_config WHERE key = 'lot_gm_floor_pct'")
```

- [ ] **Step 4: Run migration**

```
.\venv\Scripts\python.exe -m alembic upgrade head
```
Expected:
```
INFO  Running upgrade 20260515_1000 -> 20260516_1000, Add lot_profitability_estimates table
```

- [ ] **Step 5: Verify table exists**

```
.\venv\Scripts\python.exe -c "
import asyncio
from database import AsyncSessionLocal
from sqlalchemy import text
async def check():
    async with AsyncSessionLocal() as db:
        r = await db.execute(text(\"SELECT COUNT(*) FROM lot_profitability_estimates\"))
        print('Table OK, rows:', r.scalar())
asyncio.run(check())
"
```
Expected: `Table OK, rows: 0`

- [ ] **Step 6: Commit**

```bash
git add models/lot_profitability.py models/__init__.py alembic/versions/20260516_1000_lot_profitability.py
git commit -m "feat: add LotProfitabilityEstimate model + migration + lot_gm_floor_pct CostConfig seed"
```

---

## Task 4: Profitability Router + Template

**Files:**
- Create: `routers/lot_profitability.py`
- Create: `templates/lots/profitability.html`
- Modify: `main.py` (1 import + 1 include_router line)
- Modify: `templates/lots/detail.html` (add 1 button)

- [ ] **Step 1: Create the router**

```python
# routers/lot_profitability.py
"""
Lot Profitability Calculator
Routes:
  GET  /lots/{lot_id}/profitability  — show calculator form + version history
  POST /lots/{lot_id}/profitability  — run calculation, save, redirect back
"""
from templates_config import templates
from decimal import Decimal
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from models.user import User, UserRole
from models.lot import Lot
from models.cost_config import CostConfig
from models.lot_profitability import LotProfitabilityEstimate
from auth.dependencies import get_current_user, require_roles, verify_csrf
from services.audit_engine import audit
from services.profitability_engine import compute_profitability

router = APIRouter(tags=["lot_profitability"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.inventory_manager)


async def _get_gm_floor(db: AsyncSession) -> float:
    """Fetch lot_gm_floor_pct from CostConfig; default 25.0."""
    r = await db.execute(select(CostConfig).where(CostConfig.key == "lot_gm_floor_pct"))
    cfg = r.scalar_one_or_none()
    return float(cfg.value) if cfg else 25.0


@router.get("/lots/{lot_id}/profitability", response_class=HTMLResponse)
async def profitability_form(
    lot_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    lot_r = await db.execute(select(Lot).where(Lot.id == lot_id))
    lot = lot_r.scalar_one_or_none()
    if not lot:
        raise HTTPException(404, "Lot not found")

    est_r = await db.execute(
        select(LotProfitabilityEstimate)
        .where(LotProfitabilityEstimate.lot_id == lot.id)
        .order_by(LotProfitabilityEstimate.version.desc())
    )
    estimates = est_r.scalars().all()
    gm_floor = await _get_gm_floor(db)

    return templates.TemplateResponse("lots/profitability.html", {
        "request": request,
        "lot": lot,
        "estimates": estimates,
        "gm_floor": gm_floor,
        "latest": estimates[0] if estimates else None,
        "current_user": current_user,
        "error": request.query_params.get("error"),
        "success": request.query_params.get("success"),
    })


@router.post("/lots/{lot_id}/profitability")
async def compute_and_save(
    lot_id: str,
    request: Request,
    transport_cost: str    = Form("0"),
    labour_per_device: str = Form("0"),
    parts_per_device: str  = Form("0"),
    overhead_cost: str     = Form("0"),
    yield_a: str   = Form("0"),
    yield_b: str   = Form("0"),
    yield_c: str   = Form("0"),
    yield_d: str   = Form("0"),
    yield_scrap: str = Form("0"),
    price_a: str   = Form("0"),
    price_b: str   = Form("0"),
    price_c: str   = Form("0"),
    price_d: str   = Form("0"),
    price_scrap: str = Form("0"),
    notes: str     = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    lot_r = await db.execute(select(Lot).where(Lot.id == lot_id))
    lot = lot_r.scalar_one_or_none()
    if not lot:
        raise HTTPException(404, "Lot not found")

    # Validate yield sum = 100
    total_yield = sum(float(v) for v in [yield_a, yield_b, yield_c, yield_d, yield_scrap])
    if abs(total_yield - 100.0) > 0.5:
        return RedirectResponse(
            url=f"/lots/{lot_id}/profitability?error=Grade+yield+percentages+must+sum+to+100+(got+{total_yield:.1f}%25)",
            status_code=302,
        )

    gm_floor = await _get_gm_floor(db)

    calc = compute_profitability(
        buying_price=float(lot.buying_price),
        transport_cost=float(transport_cost),
        labour_per_device=float(labour_per_device),
        parts_per_device=float(parts_per_device),
        overhead_cost=float(overhead_cost),
        qty=lot.qty,
        grade_yield={"a": float(yield_a), "b": float(yield_b), "c": float(yield_c),
                     "d": float(yield_d), "scrap": float(yield_scrap)},
        grade_price={"a": float(price_a), "b": float(price_b), "c": float(price_c),
                     "d": float(price_d), "scrap": float(price_scrap)},
        gm_floor_pct=gm_floor,
    )

    # Get next version number
    ver_r = await db.execute(
        select(func.count(LotProfitabilityEstimate.id))
        .where(LotProfitabilityEstimate.lot_id == lot.id)
    )
    version = (ver_r.scalar() or 0) + 1

    estimate = LotProfitabilityEstimate(
        lot_id=lot.id,
        version=version,
        buying_price=lot.buying_price,
        transport_cost=float(transport_cost),
        labour_per_device=float(labour_per_device),
        parts_per_device=float(parts_per_device),
        overhead_cost=float(overhead_cost),
        qty=lot.qty,
        yield_grade_a=float(yield_a),
        yield_grade_b=float(yield_b),
        yield_grade_c=float(yield_c),
        yield_grade_d=float(yield_d),
        yield_scrap=float(yield_scrap),
        price_grade_a=float(price_a),
        price_grade_b=float(price_b),
        price_grade_c=float(price_c),
        price_grade_d=float(price_d),
        price_scrap=float(price_scrap),
        total_cost=calc["total_cost"],
        expected_revenue=calc["expected_revenue"],
        gross_margin_pct=calc["gross_margin_pct"],
        profit_per_unit=calc["profit_per_unit"],
        roi_pct=calc["roi_pct"],
        max_bid_price=calc["max_bid_price"],
        verdict=calc["verdict"],
        gm_floor_applied=Decimal(str(gm_floor)),
        notes=notes or None,
        created_by=current_user.username,
    )
    db.add(estimate)

    log = await audit(
        db, action="LOT_PROFITABILITY_COMPUTED",
        user=current_user,
        table_name="lot_profitability_estimates",
        record_id=str(lot.id),
        new_value={
            "lot_number": lot.lot_number,
            "version": version,
            "verdict": calc["verdict"],
            "gm_pct": str(calc["gross_margin_pct"]),
        },
        request=request,
    )
    db.add(log)

    await db.commit()
    return RedirectResponse(
        url=f"/lots/{lot_id}/profitability?success=v{version}+saved+%E2%80%94+{calc['verdict']}",
        status_code=302,
    )
```

- [ ] **Step 2: Create the template**

```html
{# templates/lots/profitability.html #}
{% extends "base.html" %}
{% block title %}Profitability — {{ lot.lot_number }}{% endblock %}
{% block page_title %}Lot Profitability Calculator — {{ lot.lot_number }}{% endblock %}

{% block content %}
{% if success %}
<div class="alert alert-success alert-dismissible fade show">{{ success }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>
{% endif %}
{% if error %}
<div class="alert alert-danger alert-dismissible fade show">{{ error }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>
{% endif %}

{# ── Lot Summary Strip ─────────────────────────────────────────────────── #}
<div class="card border-0 shadow-sm mb-3">
  <div class="card-body py-2 d-flex gap-4 flex-wrap align-items-center">
    <div><span class="text-muted small">Lot</span><br><strong>{{ lot.lot_number }}</strong></div>
    <div><span class="text-muted small">Supplier</span><br><strong>{{ lot.supplier_name }}</strong></div>
    <div><span class="text-muted small">Buying Price</span><br><strong class="text-danger">₹{{ "{:,.0f}".format(lot.buying_price) }}</strong></div>
    <div><span class="text-muted small">Qty</span><br><strong>{{ lot.qty }}</strong></div>
    <div><span class="text-muted small">Cost/Unit</span><br><strong>₹{{ "{:,.0f}".format(lot.buying_price / lot.qty) }}</strong></div>
    <div class="ms-auto">
      <a href="/lots/{{ lot.id }}" class="btn btn-sm btn-outline-secondary">← Back to Lot</a>
    </div>
  </div>
</div>

<div class="row g-3">
  {# ── Calculator Form ───────────────────────────────────────────────── #}
  <div class="col-lg-7">
    <div class="card border-0 shadow-sm">
      <div class="card-header bg-white fw-semibold"><i class="bi bi-calculator me-2 text-primary"></i>Run Profitability Estimate</div>
      <div class="card-body">
        <form method="post" action="/lots/{{ lot.id }}/profitability">
          <input type="hidden" name="csrf_token" value="{{ request.session.get('csrf_token', '') }}">

          {# 5 Cost Categories #}
          <h6 class="text-muted text-uppercase small mb-2">Cost Inputs (₹)</h6>
          <div class="row g-2 mb-3">
            <div class="col-6">
              <label class="form-label small mb-1">Buying Price <span class="text-muted">(auto)</span></label>
              <input type="text" class="form-control form-control-sm bg-light" value="₹{{ '{:,.0f}'.format(lot.buying_price) }}" disabled>
            </div>
            <div class="col-6">
              <label class="form-label small mb-1">Transport Cost</label>
              <input type="number" name="transport_cost" class="form-control form-control-sm" min="0" step="100" value="{{ latest.transport_cost if latest else 0 }}">
            </div>
            <div class="col-6">
              <label class="form-label small mb-1">Labour / Device (₹)</label>
              <input type="number" name="labour_per_device" class="form-control form-control-sm" min="0" step="10" value="{{ latest.labour_per_device if latest else 100 }}">
            </div>
            <div class="col-6">
              <label class="form-label small mb-1">Spare Parts / Device (₹)</label>
              <input type="number" name="parts_per_device" class="form-control form-control-sm" min="0" step="10" value="{{ latest.parts_per_device if latest else 200 }}">
            </div>
            <div class="col-6">
              <label class="form-label small mb-1">Overhead / Misc (₹)</label>
              <input type="number" name="overhead_cost" class="form-control form-control-sm" min="0" step="100" value="{{ latest.overhead_cost if latest else 0 }}">
            </div>
          </div>

          {# Grade Yield Mix #}
          <h6 class="text-muted text-uppercase small mb-2">Grade Yield Mix (must sum to 100%)</h6>
          <div class="row g-2 mb-3">
            {% for grade, label, color in [('a','Grade A','success'),('b','Grade B','primary'),('c','Grade C','warning'),('d','Grade D','orange'),('scrap','Scrap','danger')] %}
            <div class="col">
              <label class="form-label small mb-1 text-{{ color }}">{{ label }} %</label>
              <input type="number" name="yield_{{ grade }}" class="form-control form-control-sm yield-input"
                     min="0" max="100" step="1"
                     value="{{ latest['yield_grade_' ~ grade] | default(0) if latest else 0 }}">
            </div>
            {% endfor %}
            <div class="col-12">
              <div class="d-flex align-items-center gap-2">
                <small class="text-muted">Yield total:</small>
                <span id="yieldTotal" class="fw-bold">0%</span>
                <span id="yieldStatus" class="badge bg-danger">Incomplete</span>
              </div>
            </div>
          </div>

          {# Grade Prices #}
          <h6 class="text-muted text-uppercase small mb-2">Selling Price by Grade (₹/unit)</h6>
          <div class="row g-2 mb-3">
            {% for grade, label in [('a','Grade A'),('b','Grade B'),('c','Grade C'),('d','Grade D'),('scrap','Scrap')] %}
            <div class="col">
              <label class="form-label small mb-1">{{ label }}</label>
              <input type="number" name="price_{{ grade }}" class="form-control form-control-sm"
                     min="0" step="100"
                     value="{{ latest['price_grade_' ~ grade] | default(0) if latest else 0 }}">
            </div>
            {% endfor %}
          </div>

          <div class="mb-3">
            <label class="form-label small mb-1">Notes (optional)</label>
            <input type="text" name="notes" class="form-control form-control-sm" placeholder="e.g. Based on last 3 lots from this supplier">
          </div>

          <div class="d-flex gap-2">
            <button type="submit" class="btn btn-primary"><i class="bi bi-play-fill me-1"></i>Run Calculation</button>
            <span class="text-muted small align-self-center">Floor: {{ gm_floor }}% GM</span>
          </div>
        </form>
      </div>
    </div>
  </div>

  {# ── Latest Result Card ────────────────────────────────────────────── #}
  <div class="col-lg-5">
    {% if latest %}
    {% set v_color = 'success' if latest.verdict == 'ACCEPT' else ('warning' if latest.verdict == 'RENEGOTIATE' else 'danger') %}
    {% set v_icon  = 'check-circle-fill' if latest.verdict == 'ACCEPT' else ('exclamation-triangle-fill' if latest.verdict == 'RENEGOTIATE' else 'x-circle-fill') %}
    <div class="card border-0 shadow-sm border-{{ v_color }} border-2">
      <div class="card-header bg-{{ v_color }} text-white fw-bold">
        <i class="bi bi-{{ v_icon }} me-2"></i>{{ latest.verdict }} &nbsp;<small class="opacity-75">v{{ latest.version }}</small>
      </div>
      <div class="card-body">
        <div class="row g-2 text-center mb-3">
          <div class="col-6">
            <div class="text-muted small">Total Cost</div>
            <div class="fw-bold text-danger fs-5">₹{{ "{:,.0f}".format(latest.total_cost) }}</div>
          </div>
          <div class="col-6">
            <div class="text-muted small">Expected Revenue</div>
            <div class="fw-bold text-success fs-5">₹{{ "{:,.0f}".format(latest.expected_revenue) }}</div>
          </div>
          <div class="col-4">
            <div class="text-muted small">GM %</div>
            <div class="fw-bold fs-5 text-{{ v_color }}">{{ "{:.1f}".format(latest.gross_margin_pct) }}%</div>
          </div>
          <div class="col-4">
            <div class="text-muted small">Profit/Unit</div>
            <div class="fw-bold">₹{{ "{:,.0f}".format(latest.profit_per_unit) }}</div>
          </div>
          <div class="col-4">
            <div class="text-muted small">ROI %</div>
            <div class="fw-bold">{{ "{:.1f}".format(latest.roi_pct) }}%</div>
          </div>
        </div>
        {% if latest.verdict == 'RENEGOTIATE' and latest.max_bid_price %}
        <div class="alert alert-warning py-2 mb-0">
          <i class="bi bi-arrow-down-circle me-1"></i>
          <strong>Max Bid Price:</strong> ₹{{ "{:,.0f}".format(latest.max_bid_price) }}
          <div class="small text-muted">Buying at this price achieves exactly {{ latest.gm_floor_applied }}% GM floor</div>
        </div>
        {% endif %}
        {% if latest.verdict == 'DECLINE' %}
        <div class="alert alert-danger py-2 mb-0">
          <i class="bi bi-x-octagon me-1"></i>
          <strong>Do not purchase at current price.</strong>
          <div class="small">Costs exceed expected revenue at current grade mix.</div>
        </div>
        {% endif %}
      </div>
      {% if latest.notes %}
      <div class="card-footer text-muted small">{{ latest.notes }}</div>
      {% endif %}
    </div>
    {% else %}
    <div class="card border-0 shadow-sm border-dashed">
      <div class="card-body text-center text-muted py-5">
        <i class="bi bi-calculator display-4 opacity-25"></i>
        <p class="mt-2">No estimate yet. Fill the form and run calculation.</p>
      </div>
    </div>
    {% endif %}
  </div>
</div>

{# ── Version History ────────────────────────────────────────────────────── #}
{% if estimates | length > 1 %}
<div class="card border-0 shadow-sm mt-3">
  <div class="card-header bg-white small fw-semibold">Estimate History ({{ estimates | length }} versions)</div>
  <div class="card-body p-0">
    <table class="table table-sm mb-0 small">
      <thead class="table-light"><tr><th>v#</th><th>Verdict</th><th>GM%</th><th>Revenue</th><th>Cost</th><th>Max Bid</th><th>By</th><th>Date</th></tr></thead>
      <tbody>
        {% for e in estimates %}
        <tr>
          <td>v{{ e.version }}</td>
          <td><span class="badge bg-{{ 'success' if e.verdict == 'ACCEPT' else ('warning' if e.verdict == 'RENEGOTIATE' else 'danger') }}">{{ e.verdict }}</span></td>
          <td class="fw-semibold">{{ "{:.1f}".format(e.gross_margin_pct) }}%</td>
          <td>₹{{ "{:,.0f}".format(e.expected_revenue) }}</td>
          <td>₹{{ "{:,.0f}".format(e.total_cost) }}</td>
          <td>{{ "₹{:,.0f}".format(e.max_bid_price) if e.max_bid_price else '—' }}</td>
          <td class="text-muted">{{ e.created_by }}</td>
          <td class="text-muted">{{ e.created_at.strftime('%d-%m-%Y') }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endif %}
{% endblock %}

{% block scripts %}
<script>
document.addEventListener('DOMContentLoaded', function () {
  const inputs = document.querySelectorAll('.yield-input');
  const totalEl = document.getElementById('yieldTotal');
  const statusEl = document.getElementById('yieldStatus');
  function updateTotal() {
    let sum = 0;
    inputs.forEach(i => sum += parseFloat(i.value || 0));
    totalEl.textContent = sum.toFixed(1) + '%';
    if (Math.abs(sum - 100) < 0.5) {
      statusEl.textContent = '✓ OK';
      statusEl.className = 'badge bg-success';
    } else {
      statusEl.textContent = 'Incomplete';
      statusEl.className = 'badge bg-danger';
    }
  }
  inputs.forEach(i => i.addEventListener('input', updateTotal));
  updateTotal();
});
</script>
{% endblock %}
```

- [ ] **Step 3: Wire router into main.py**

Find the block of `from routers import ...` and `app.include_router(...)` calls in `main.py`. Add after the last router import:

```python
from routers.lot_profitability import router as lot_profitability_router
```

And add after the last `app.include_router(...)` call:
```python
app.include_router(lot_profitability_router)
```

- [ ] **Step 4: Add "Profitability Check" button to lot detail page**

In `templates/lots/detail.html`, find the button bar at the top (near the "Submit GRN" button or Edit button). Add:

```html
<a href="/lots/{{ lot.id }}/profitability" class="btn btn-sm btn-outline-warning">
  <i class="bi bi-calculator me-1"></i>Profitability Check
</a>
```

- [ ] **Step 5: Verify page loads**

Start server and navigate to any lot's detail page. Click "Profitability Check". Verify the calculator form loads without 500 errors.

- [ ] **Step 6: Commit**

```bash
git add routers/lot_profitability.py templates/lots/profitability.html main.py templates/lots/detail.html
git commit -m "feat: add Lot Profitability Calculator — ACCEPT/RENEGOTIATE/DECLINE verdicts"
```

---

## Task 5: Admin Config — GM Floor

**Files:**
- Modify: `routers/admin.py` (add 1 entry to `COST_CONFIG_DEFS`)
- Modify: `templates/admin/cost_config.html` (already handles all CostConfig keys generically — no change needed if it uses a for-loop)

- [ ] **Step 1: Add lot_gm_floor_pct to COST_CONFIG_DEFS**

In `routers/admin.py`, find the `COST_CONFIG_DEFS` list (or dict). Add this entry alongside the existing `repair_labour_rate`, `cosmetic_rate`, `gst_rate_intra`, `gst_rate_inter` entries:

```python
("lot_gm_floor_pct", "Lot GM Floor (%)", "Minimum gross margin % to ACCEPT a lot purchase. Below this = RENEGOTIATE verdict. Default: 25"),
```

- [ ] **Step 2: Verify admin cost config page shows the new field**

Navigate to `/admin/cost-config` (or equivalent). Confirm `Lot GM Floor (%)` appears and can be edited. Change to 20, save, then change back to 25.

- [ ] **Step 3: Commit**

```bash
git add routers/admin.py
git commit -m "feat: expose lot_gm_floor_pct in admin cost config UI"
```

---

## Task 6: Audit Trail — CRM Contact Create and Activity Log

**Files:**
- Modify: `routers/crm_contacts.py` (add `audit()` to bulk-upload POST)
- Modify: `routers/crm_activities.py` (add `audit()` to activity log POST)

### 6a: CRM Contact Bulk Upload

- [ ] **Step 1: Add audit call to POST /upload in crm_contacts.py**

In `routers/crm_contacts.py`, find the `upload_contacts_csv` POST handler. Locate the `await db.commit()` line near the end. Replace it with:

```python
    # Audit the bulk import
    if created > 0:
        await audit(
            db, action="CRM_CONTACTS_IMPORTED",
            user=current_user,
            table_name="crm_contacts",
            notes=f"Bulk import: {created} created, {skipped} skipped from '{file.filename}'",
            request=request,
        )
    await db.commit()
```

**Important:** The `audit` function must be imported. Check the top of `crm_contacts.py` for:
```python
from services.audit_engine import audit
```
If it's missing, add it.

- [ ] **Step 2: Also add audit to single-contact create POST (if one exists)**

Grep `crm_contacts.py` for `@router.post` routes that create individual contacts:
```
findstr /n "@router.post" routers\crm_contacts.py
```
For each POST that creates a single `CRMContact` record, add before `await db.commit()`:
```python
    await audit(db, action="CRM_CONTACT_CREATED", user=current_user,
                table_name="crm_contacts", record_id=str(contact.id),
                new_value={"company_name": contact.company_name, "contact_type": contact.contact_type,
                           "code": contact.contact_code},
                request=request)
```

### 6b: CRM Activity Log

- [ ] **Step 3: Add audit call to the activity log POST in crm_activities.py**

In `routers/crm_activities.py`, find the POST route that creates a `CRMActivity` and calls `await db.commit()`. Add before the commit:

```python
    await audit(
        db, action="CRM_ACTIVITY_LOGGED",
        user=current_user,
        table_name="crm_activities",
        record_id=str(activity.id),
        new_value={
            "activity_type": activity.activity_type,
            "deal_id": str(activity.deal_id) if activity.deal_id else None,
            "outcome": activity.outcome,
        },
        request=request,
    )
```

**Import check:** Ensure `crm_activities.py` has:
```python
from services.audit_engine import audit
```

- [ ] **Step 4: Verify audit logs are written**

Run the server, log in, and:
1. Navigate to CRM Contacts → Upload CSV → upload a test file with 2 rows
2. Navigate to `/admin/audit-logs` (or the audit logs view) — confirm rows appear with `action = CRM_CONTACTS_IMPORTED`
3. Log an activity on any CRM deal — confirm a row appears with `action = CRM_ACTIVITY_LOGGED`

- [ ] **Step 5: Commit**

```bash
git add routers/crm_contacts.py routers/crm_activities.py
git commit -m "feat: complete audit trail — wire CRM contact import + activity log to audit_engine"
```

---

## Task 7: Windows Service (NSSM)

**Files:**
- Create: `scripts/start_server.bat`
- Create: `scripts/install_service.ps1`

**Prerequisites:** Run PowerShell as Administrator for all steps in this task.

- [ ] **Step 1: Create the server wrapper batch file**

```bat
@echo off
REM scripts\start_server.bat
REM Wrapper invoked by NSSM. Activates venv and starts uvicorn.
REM NSSM will restart this if it exits.

cd /d C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
call venv\Scripts\activate.bat
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

- [ ] **Step 2: Create the install script**

```powershell
# scripts\install_service.ps1
# Run as Administrator.
# Downloads NSSM 2.24, installs OxyPCInventory as a Windows Service.

$NssmDir    = "C:\nssm"
$NssmExe    = "$NssmDir\nssm-2.24\win64\nssm.exe"
$ServiceName = "OxyPCInventory"
$AppDir      = "C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory"
$BatchFile   = "$AppDir\scripts\start_server.bat"
$LogDir      = "$AppDir\logs"

# ── 1. Download + extract NSSM ────────────────────────────────────────────
if (-not (Test-Path $NssmExe)) {
    Write-Host "Downloading NSSM 2.24..."
    New-Item -ItemType Directory -Force $NssmDir | Out-Null
    $ZipPath = "$NssmDir\nssm-2.24.zip"
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $ZipPath
    Expand-Archive -Path $ZipPath -DestinationPath $NssmDir -Force
    Write-Host "NSSM extracted to $NssmDir"
} else {
    Write-Host "NSSM already present at $NssmExe"
}

# ── 2. Ensure log directory exists ────────────────────────────────────────
New-Item -ItemType Directory -Force $LogDir | Out-Null

# ── 3. Remove old service if it exists ───────────────────────────────────
$existing = sc.exe query $ServiceName 2>&1
if ($existing -notlike "*does not exist*") {
    Write-Host "Removing existing service $ServiceName..."
    & $NssmExe stop  $ServiceName 2>&1 | Out-Null
    & $NssmExe remove $ServiceName confirm 2>&1 | Out-Null
}

# ── 4. Install service ────────────────────────────────────────────────────
Write-Host "Installing $ServiceName service..."
& $NssmExe install $ServiceName $BatchFile

# ── 5. Configure service settings ─────────────────────────────────────────
& $NssmExe set $ServiceName AppDirectory   $AppDir
& $NssmExe set $ServiceName Start          SERVICE_AUTO_START
& $NssmExe set $ServiceName AppStdout      "$LogDir\service.log"
& $NssmExe set $ServiceName AppStderr      "$LogDir\service_error.log"
& $NssmExe set $ServiceName AppRotateFiles 1
& $NssmExe set $ServiceName AppRotateBytes 10485760   # 10 MB
& $NssmExe set $ServiceName AppRestartDelay 5000       # 5 sec before auto-restart

# ── 6. Start the service ──────────────────────────────────────────────────
Write-Host "Starting $ServiceName..."
& $NssmExe start $ServiceName

Start-Sleep -Seconds 5
$status = (sc.exe query $ServiceName | Select-String "STATE").ToString().Trim()
Write-Host "Service status: $status"

if ($status -like "*RUNNING*") {
    Write-Host "`n✅ OxyPCInventory service is RUNNING."
    Write-Host "   URL: http://localhost:8000"
    Write-Host "   Logs: $LogDir\service.log"
    Write-Host "   Manage: services.msc → OxyPCInventory"
} else {
    Write-Host "`n❌ Service did not start. Check $LogDir\service_error.log"
}
```

- [ ] **Step 3: Run the install script as Administrator**

Open PowerShell **as Administrator**, then:
```powershell
cd C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
.\scripts\install_service.ps1
```
Expected final output: `✅ OxyPCInventory service is RUNNING.`

- [ ] **Step 4: Verify via Services panel**

Open `services.msc` → find `OxyPCInventory` → confirm Status = Running, Startup Type = Automatic.

- [ ] **Step 5: Test auto-restart**

```powershell
# Kill the server process — service should auto-restart within 5 seconds
$pid_before = (netstat -ano | findstr ":8000" | Select-String "LISTENING" | ForEach-Object { ($_ -split '\s+')[-1] } | Select-Object -First 1)
Stop-Process -Id $pid_before -Force
Start-Sleep -Seconds 8
netstat -ano | findstr ":8000"
```
Expected: Port 8000 is LISTENING again (new PID).

- [ ] **Step 6: Commit**

```bash
git add scripts/start_server.bat scripts/install_service.ps1
git commit -m "ops: add NSSM Windows Service install script — server survives terminal close + reboots"
```

---

## Task 8: Nightly Database Backup

**Files:**
- Create: `scripts/backup_db.ps1`

**Prerequisites:** `pg_dump` must be on PATH (installed with PostgreSQL). Run step 4 as Administrator.

- [ ] **Step 1: Locate pg_dump**

```powershell
where.exe pg_dump
```
Expected: `C:\Program Files\PostgreSQL\14\bin\pg_dump.exe` (or similar). If not found, add PostgreSQL bin to PATH:
```powershell
$env:PATH += ";C:\Program Files\PostgreSQL\14\bin"
```

- [ ] **Step 2: Create backup_db.ps1**

```powershell
# scripts\backup_db.ps1
# Nightly pg_dump backup with 30-day rotation.
# Registered in Task Scheduler to run at 02:00 AM daily.
# Backup files: C:\backups\oxypc\oxypc_YYYYMMDD_HHMMSS.dump

param(
    [string]$BackupDir = "C:\backups\oxypc",
    [int]$RetainDays   = 30
)

$ErrorActionPreference = "Stop"
$LogFile = "$BackupDir\backup.log"

function Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

# ── 1. Ensure backup directory exists ────────────────────────────────────
New-Item -ItemType Directory -Force $BackupDir | Out-Null

# ── 2. Read DB connection from .env ──────────────────────────────────────
$EnvPath = "C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory\.env"
if (-not (Test-Path $EnvPath)) {
    Log "ERROR: .env not found at $EnvPath"
    exit 1
}

$dbUrl = (Get-Content $EnvPath | Where-Object { $_ -match "^DATABASE_URL" } |
          Select-Object -First 1) -replace '^DATABASE_URL\s*=\s*','' -replace '"','' -replace "'",''

# Parse: postgresql+asyncpg://user:password@host:port/dbname
if ($dbUrl -match 'postgresql\+asyncpg://([^:]+):([^@]+)@([^:/]+):?(\d*)/(\S+)') {
    $dbUser = $Matches[1]
    $dbPass = $Matches[2]
    $dbHost = $Matches[3]
    $dbPort = if ($Matches[4]) { $Matches[4] } else { "5432" }
    $dbName = $Matches[5]
} else {
    Log "ERROR: Could not parse DATABASE_URL from .env"
    exit 1
}

# ── 3. Run pg_dump ────────────────────────────────────────────────────────
$Timestamp  = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupFile = "$BackupDir\oxypc_$Timestamp.dump"

Log "Starting backup: $BackupFile"
$env:PGPASSWORD = $dbPass
try {
    & pg_dump --host=$dbHost --port=$dbPort --username=$dbUser --format=custom --file=$BackupFile $dbName
    if ($LASTEXITCODE -ne 0) { throw "pg_dump exited with code $LASTEXITCODE" }
    $sizeMB = [math]::Round((Get-Item $BackupFile).Length / 1MB, 2)
    Log "SUCCESS: backup saved ($sizeMB MB)"
} catch {
    Log "ERROR: pg_dump failed — $_"
    exit 1
} finally {
    $env:PGPASSWORD = ""
}

# ── 4. Rotate: delete backups older than $RetainDays ─────────────────────
$cutoff = (Get-Date).AddDays(-$RetainDays)
$deleted = 0
Get-ChildItem $BackupDir -Filter "oxypc_*.dump" |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    ForEach-Object { Remove-Item $_.FullName -Force; $deleted++ }
if ($deleted -gt 0) { Log "Rotated $deleted old backup(s) older than $RetainDays days" }

Log "Backup complete."
```

- [ ] **Step 3: Test the backup script manually**

```powershell
cd C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
.\scripts\backup_db.ps1
```
Expected output:
```
2026-05-16 02:00:01 Starting backup: C:\backups\oxypc\oxypc_20260516_020001.dump
2026-05-16 02:00:04 SUCCESS: backup saved (X.XX MB)
2026-05-16 02:00:04 Backup complete.
```
Verify file exists: `Get-Item C:\backups\oxypc\oxypc_*.dump`

- [ ] **Step 4: Register in Windows Task Scheduler (run as Administrator)**

```powershell
$action  = New-ScheduledTaskAction -Execute "PowerShell.exe" `
             -Argument "-NonInteractive -ExecutionPolicy Bypass -File C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory\scripts\backup_db.ps1"
$trigger = New-ScheduledTaskTrigger -Daily -At "02:00AM"
$settings= New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1) -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName "OxyPC-NightlyBackup" `
    -Action $action -Trigger $trigger -Settings $settings `
    -RunLevel Highest -Force

Write-Host "Task registered. Verify:"
Get-ScheduledTask -TaskName "OxyPC-NightlyBackup" | Select-Object TaskName, State
```
Expected: `TaskName: OxyPC-NightlyBackup   State: Ready`

- [ ] **Step 5: Commit**

```bash
git add scripts/backup_db.ps1
git commit -m "ops: add nightly pg_dump backup script with 30-day rotation + Task Scheduler registration"
```

---

## Self-Review

**1. Spec coverage:**

| Requirement | Task |
|---|---|
| Windows Service — auto-restart on crash + reboot | Task 7 ✅ |
| Nightly pg_dump backup with rotation | Task 8 ✅ |
| 5-category cost breakdown | Task 2 (profitability_engine.py) ✅ |
| Grade yield mix → expected revenue | Task 2 ✅ |
| GM%, profit/unit, ROI% metrics | Task 2 ✅ |
| ACCEPT/RENEGOTIATE/DECLINE verdict | Task 2 ✅ |
| Max bid price on RENEGOTIATE | Task 2 ✅ |
| Margin floor in CostConfig | Task 3 (migration seeds it) + Task 5 ✅ |
| Immutable versioned estimates | Task 3 (new row per calc) ✅ |
| Calculator UI with form + results | Task 4 ✅ |
| CRM contact import audit | Task 6 ✅ |
| CRM activity log audit | Task 6 ✅ |

**2. Placeholder scan:** No TBD, no "add appropriate error handling" without code, no "similar to Task N" shortcuts. All steps have exact code.

**3. Type consistency:**
- `compute_profitability()` defined in Task 2 with keys `a/b/c/d/scrap` — used in Task 4 router with same keys ✅
- `LotProfitabilityEstimate.yield_grade_a` field defined in Task 3 — referenced in Task 4 template ✅
- `lot_gm_floor_pct` key seeded in Task 3 migration — referenced in Task 5 admin config ✅

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-16-sprint24-stability-profitability.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, two-stage review after each, fast iteration

**2. Inline Execution** — execute tasks in this session with checkpoints

**Which approach?**
