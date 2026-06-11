# OxyPC Week 2 Recovery Sprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Risk 5 (dealer outstanding drift), wire missing audit calls, add `/health` endpoint, and create the systemd service unit for production process supervision.

**Architecture:** All four tasks are independent surgical changes — no cross-task dependencies. Task 1 is a pure Python refactor (no migration): stop writing to `Dealer.outstanding_amount` and replace every read with a live `SUM(DealerOrder.due_amount)` query. Task 2 wires `audit_engine.audit()` (which already exists in `services/audit_engine.py`) into two routers that currently skip it. Task 3 adds a single `GET /health` JSON route. Task 4 creates static service files with no Python changes.

**Tech Stack:** FastAPI 0.115, async SQLAlchemy 2.0 (asyncpg), PostgreSQL 15, Jinja2, Bootstrap 5, systemd (Linux target for Task 4).

---

## File Map

| File | Action | Task |
|---|---|---|
| `routers/dealers.py` | Modify | 1, 2 |
| `templates/dealers/list.html` | Modify | 1 |
| `templates/dealers/profile.html` | Modify | 1 |
| `routers/accounts.py` | Modify | 2 |
| `routers/health.py` | Create | 3 |
| `main.py` | Modify | 3 |
| `services/oxypc-inventory.service` | Create | 4 |
| `services/install-service.sh` | Create | 4 |

---

## Context for All Tasks

**Project root:** `C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory\`

**Key models:**
- `models/dealers.py` → `Dealer` (has `.outstanding_amount` Numeric column — keep in DB, stop writing it), `DealerOrder` (has `.due_amount`, `.status`)
- `models/crm.py` → `CustomerReceipt` (used in accounts router)
- `models/engines.py` → `AuditLog` (already exists — do NOT recreate)

**Audit engine** (`services/audit_engine.py`) already fully implemented. Usage pattern:
```python
await audit(db, user=current_user, action="SOME_ACTION",
            table_name="some_table", record_id=str(record.id),
            new_value={"key": "value"},
            request=request)
# Do NOT call db.commit() inside audit() — caller commits
```

**Running tests:**
- Functional tests require a live server: `python functional_test.py` (hit localhost:8000)
- Pure Python unit tests: `python tests/test_week2_unit.py`
- Verify server starts clean: `python -c "import main; print('OK')"`

---

## Task 1: Dealer Outstanding — Compute on Read

**Problem:** `Dealer.outstanding_amount` is a denormalized field mutated in two places in `routers/dealers.py`. It can silently drift from the real balance. The fix: stop writing to it; compute live from `SUM(DealerOrder.due_amount WHERE status != 'cancelled')` on every read.

**Files:**
- Modify: `routers/dealers.py`
- Modify: `templates/dealers/list.html`
- Modify: `templates/dealers/profile.html`
- Create: `tests/test_week2_unit.py`

---

- [ ] **Step 1: Write the failing unit test**

Create `tests/test_week2_unit.py`:

```python
"""
Week 2 Recovery — unit tests for pure-Python functions.
Run: python tests/test_week2_unit.py
All tests use assert statements; no DB or server required.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Test: _upsell_suggestions accepts outstanding_live parameter ──────────────

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
    # Should NOT raise TypeError
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
    result = _upsell_suggestions(dealer)  # no outstanding_live arg
    assert isinstance(result, list)


if __name__ == "__main__":
    test_upsell_suggestions_with_outstanding_live()
    test_upsell_suggestions_zero_outstanding()
    test_upsell_suggestions_default_zero()
    print("All unit tests passed.")
```

- [ ] **Step 2: Run the test — confirm it fails**

```
python tests/test_week2_unit.py
```

Expected output: `TypeError: _upsell_suggestions() got an unexpected keyword argument 'outstanding_live'`

If it passes already, stop — the function was already updated. If it fails with a different error (import error on DB), check that the `tests/` directory exists and that you're running from project root.

- [ ] **Step 3: Update `_upsell_suggestions()` in `routers/dealers.py`**

The current function at the top of the file is (lines 18–30):

```python
def _upsell_suggestions(dealer: Dealer) -> list:
    suggestions = []
    days_since_sale = None
    if dealer.last_sale_date:
        days_since_sale = (datetime.utcnow() - dealer.last_sale_date).days
    if days_since_sale and days_since_sale > 30:
        suggestions.append(f"No purchase in {days_since_sale} days — good time to reconnect with new stock offers")
    if dealer.outstanding_amount and dealer.outstanding_amount > 0:
        suggestions.append(f"Outstanding ₹{int(dealer.outstanding_amount):,} — can offer credit extension for new order")
    if dealer.preferred_categories:
        suggestions.append(f"Prefers: {dealer.preferred_categories} — share availability updates")
    if not dealer.last_sale_date:
        suggestions.append("New dealer — introduce full product catalog")
    return suggestions
```

Replace it entirely with:

```python
def _upsell_suggestions(dealer: Dealer, outstanding_live: float = 0.0) -> list:
    suggestions = []
    days_since_sale = None
    if dealer.last_sale_date:
        days_since_sale = (datetime.utcnow() - dealer.last_sale_date).days
    if days_since_sale and days_since_sale > 30:
        suggestions.append(f"No purchase in {days_since_sale} days — good time to reconnect with new stock offers")
    if outstanding_live > 0:
        suggestions.append(f"Outstanding ₹{int(outstanding_live):,} — can offer credit extension for new order")
    if dealer.preferred_categories:
        suggestions.append(f"Prefers: {dealer.preferred_categories} — share availability updates")
    if not dealer.last_sale_date:
        suggestions.append("New dealer — introduce full product catalog")
    return suggestions
```

- [ ] **Step 4: Run the unit test — confirm it passes**

```
python tests/test_week2_unit.py
```

Expected: `All unit tests passed.`

- [ ] **Step 5: Update `dealer_list()` route — replace SUM(outstanding_amount) with live query**

In `routers/dealers.py`, the `dealer_list()` route currently has (around lines 77–92):

```python
    # Outstanding
    outstanding_result = await db.execute(select(func.coalesce(func.sum(Dealer.outstanding_amount), 0)))
    outstanding = int(outstanding_result.scalar() or 0)

    return templates.TemplateResponse("dealers/list.html", {
        "request": request,
        "current_user": current_user,
        "dealers": dealers,
        "q": q,
        "status": status,
        "assigned": assigned,
        "total_count": total_count,
        "active_count": active_count,
        "followup_count": followup_count,
        "outstanding": f"{outstanding:,}",
    })
```

Replace with:

```python
    # Outstanding — computed live from dealer_orders.due_amount (not cached field)
    out_rows = await db.execute(
        select(DealerOrder.dealer_id, func.coalesce(func.sum(DealerOrder.due_amount), 0).label("out"))
        .where(DealerOrder.status != "cancelled")
        .group_by(DealerOrder.dealer_id)
    )
    outstanding_map = {str(r.dealer_id): float(r.out) for r in out_rows}
    outstanding = int(sum(outstanding_map.values()))

    return templates.TemplateResponse("dealers/list.html", {
        "request": request,
        "current_user": current_user,
        "dealers": dealers,
        "q": q,
        "status": status,
        "assigned": assigned,
        "total_count": total_count,
        "active_count": active_count,
        "followup_count": followup_count,
        "outstanding": f"{outstanding:,}",
        "outstanding_map": outstanding_map,
    })
```

- [ ] **Step 6: Update `dealer_profile()` route — add live outstanding query**

In `routers/dealers.py`, the `dealer_profile()` route currently has (around lines 205–220):

```python
    orders_result = await db.execute(
        select(DealerOrder).where(DealerOrder.dealer_id == dealer.id)
        .order_by(DealerOrder.order_date.desc())
    )
    orders = orders_result.scalars().all()

    today = datetime.utcnow().date()
    return templates.TemplateResponse("dealers/profile.html", {
        "request": request,
        "current_user": current_user,
        "dealer": dealer,
        "calls": calls,
        "orders": orders,
        "today": today,
        "upsell_suggestions": _upsell_suggestions(dealer),
    })
```

Replace with:

```python
    orders_result = await db.execute(
        select(DealerOrder).where(DealerOrder.dealer_id == dealer.id)
        .order_by(DealerOrder.order_date.desc())
    )
    orders = orders_result.scalars().all()

    # Live outstanding: SUM of due_amount on non-cancelled orders
    outstanding_live = float((await db.execute(
        select(func.coalesce(func.sum(DealerOrder.due_amount), 0))
        .where(DealerOrder.dealer_id == dealer.id, DealerOrder.status != "cancelled")
    )).scalar() or 0)

    today = datetime.utcnow().date()
    return templates.TemplateResponse("dealers/profile.html", {
        "request": request,
        "current_user": current_user,
        "dealer": dealer,
        "calls": calls,
        "orders": orders,
        "today": today,
        "outstanding_live": outstanding_live,
        "upsell_suggestions": _upsell_suggestions(dealer, outstanding_live),
    })
```

- [ ] **Step 7: Remove the two `outstanding_amount` write mutations**

In `routers/dealers.py`, find `create_order()` (around line 434). Remove this line:

```python
        dealer.outstanding_amount = float(dealer.outstanding_amount or 0) + due
```

Keep the lines before and after it intact:
```python
    if dealer:
        # KEEP: dealer.outstanding_amount = ...  ← DELETE THIS ONE LINE
        dealer.total_purchases    = float(dealer.total_purchases    or 0) + total
        dealer.last_sale_date     = datetime.utcnow()
        dealer.last_sale_amount   = total
```

Then find `record_order_payment()` (around line 472). Remove this line:

```python
        dealer.outstanding_amount = max(0.0, float(dealer.outstanding_amount or 0) - amt)
```

- [ ] **Step 8: Update `templates/dealers/list.html` — use outstanding_map**

In `templates/dealers/list.html`, find line 60:

```html
            <td class="small {% if d.outstanding_amount > 0 %}text-danger fw-semibold{% endif %}">₹{{ "{:,.0f}".format(d.outstanding_amount or 0) }}</td>
```

Replace with:

```html
            {% set d_out = outstanding_map.get(d.id|string, 0) %}
            <td class="small {% if d_out > 0 %}text-danger fw-semibold{% endif %}">₹{{ "{:,.0f}".format(d_out) }}</td>
```

- [ ] **Step 9: Update `templates/dealers/profile.html` — use outstanding_live**

In `templates/dealers/profile.html`, find line 33:

```html
          <div class="col-6"><div class="small text-muted">Outstanding</div><div class="fw-semibold small {% if dealer.outstanding_amount > 0 %}text-danger{% endif %}">₹{{ "{:,.0f}".format(dealer.outstanding_amount or 0) }}</div></div>
```

Replace with:

```html
          <div class="col-6"><div class="small text-muted">Outstanding</div><div class="fw-semibold small {% if outstanding_live > 0 %}text-danger{% endif %}">₹{{ "{:,.0f}".format(outstanding_live) }}</div></div>
```

- [ ] **Step 10: Verify import check still passes**

```
python -c "import main; print('Import OK')"
```

Expected: `Import OK`

- [ ] **Step 11: Commit**

```bash
git add routers/dealers.py templates/dealers/list.html templates/dealers/profile.html tests/test_week2_unit.py
git commit -m "fix(dealers): outstanding_amount compute on read — stop writing denormalized field, compute live from dealer_orders.due_amount"
```

---

## Task 2: Wire Missing Audit Calls

**Problem:** `routers/dealers.py` and `routers/accounts.py` never call `audit()`, so dealer order creation, payments, and customer receipt creation leave no audit trail — even though the `AuditLog` table and `audit_engine` already exist.

**Files:**
- Modify: `routers/dealers.py`
- Modify: `routers/accounts.py`

---

- [ ] **Step 1: Add audit import to `routers/dealers.py`**

The current imports block in `routers/dealers.py` ends around line 15. Add one import:

```python
from services.audit_engine import audit
```

Add it after the existing imports, before the `router = APIRouter(...)` line.

- [ ] **Step 2: Add audit call in `create_order()` in `routers/dealers.py`**

Find the `create_order()` POST handler. It currently ends with:

```python
    db.add(order)
    dr = await db.execute(select(Dealer).where(Dealer.id == dealer_id))
    dealer = dr.scalar_one_or_none()
    if dealer:
        dealer.total_purchases    = float(dealer.total_purchases    or 0) + total
        dealer.last_sale_date     = datetime.utcnow()
        dealer.last_sale_amount   = total
    await db.commit()
    return RedirectResponse(url=f"/dealers/{dealer_id}?success=Order+created", status_code=302)
```

Replace with:

```python
    db.add(order)
    dr = await db.execute(select(Dealer).where(Dealer.id == dealer_id))
    dealer = dr.scalar_one_or_none()
    if dealer:
        dealer.total_purchases    = float(dealer.total_purchases    or 0) + total
        dealer.last_sale_date     = datetime.utcnow()
        dealer.last_sale_amount   = total
    await audit(db, user=current_user, action="ORDER_CREATED",
                table_name="dealer_orders", record_id=str(order.id),
                new_value={"order_number": order_number, "dealer_id": dealer_id,
                           "total_amount": total, "paid_amount": paid, "due_amount": due},
                request=request)
    await db.commit()
    return RedirectResponse(url=f"/dealers/{dealer_id}?success=Order+created", status_code=302)
```

- [ ] **Step 3: Add audit call in `record_order_payment()` in `routers/dealers.py`**

Find `record_order_payment()`. It currently ends with:

```python
    dr = await db.execute(select(Dealer).where(Dealer.id == dealer_id))
    dealer = dr.scalar_one_or_none()
    if dealer:
        pass  # outstanding_amount write was removed in Task 1
    await db.commit()
    return RedirectResponse(url=f"/dealers/{dealer_id}?success=Payment+recorded", status_code=302)
```

(Note: after Task 1, the `dealer.outstanding_amount` line is gone; the `if dealer:` block may be empty or removed. Either way, add the audit call before `db.commit()`.)

The full end of the function should be:

```python
    dr = await db.execute(select(Dealer).where(Dealer.id == dealer_id))
    dealer = dr.scalar_one_or_none()
    await audit(db, user=current_user, action="PAYMENT_RECORDED",
                table_name="dealer_orders", record_id=str(order.id),
                new_value={"amount": amt, "payment_mode": payment_mode or None,
                           "order_id": str(order.id), "dealer_id": dealer_id},
                request=request)
    await db.commit()
    return RedirectResponse(url=f"/dealers/{dealer_id}?success=Payment+recorded", status_code=302)
```

- [ ] **Step 4: Add audit import + `request` param + audit call in `routers/accounts.py`**

`routers/accounts.py` currently imports:

```python
from auth.dependencies import get_current_user, verify_csrf
```

Add to the imports block:

```python
from fastapi import APIRouter, Depends, Form, Query, Request
from services.audit_engine import audit
```

(Note: `Request` may already be imported — check the existing import line and add only what's missing.)

Then find `create_customer_receipt()`. Its signature currently is:

```python
@router.post("/customer-receipts/new")
async def create_customer_receipt(
    _csrf: None = Depends(verify_csrf),
    contact_id: str = Form(default=""),
    dealer_id: str = Form(default=""),
    sale_id: str = Form(default=""),
    receipt_date: str = Form(...),
    amount: str = Form(...),
    payment_mode: str = Form(default=""),
    reference_no: str = Form(default=""),
    notes: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
```

Add `request: Request` as the first parameter (FastAPI will inject it automatically):

```python
@router.post("/customer-receipts/new")
async def create_customer_receipt(
    request: Request,
    _csrf: None = Depends(verify_csrf),
    contact_id: str = Form(default=""),
    dealer_id: str = Form(default=""),
    sale_id: str = Form(default=""),
    receipt_date: str = Form(...),
    amount: str = Form(...),
    payment_mode: str = Form(default=""),
    reference_no: str = Form(default=""),
    notes: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
```

Then find the end of the function:

```python
    db.add(rec)
    await db.commit()
    return RedirectResponse(url="/accounts/customer-receipts?success=Receipt+recorded", status_code=302)
```

Replace with:

```python
    db.add(rec)
    await audit(db, user=current_user, action="RECEIPT_RECORDED",
                table_name="customer_receipts", record_id=str(rec.id),
                new_value={"amount": amt, "payment_mode": payment_mode or None,
                           "dealer_id": dealer_id or None,
                           "reference_no": reference_no or None},
                request=request)
    await db.commit()
    return RedirectResponse(url="/accounts/customer-receipts?success=Receipt+recorded", status_code=302)
```

- [ ] **Step 5: Add audit unit tests for pure-function import check**

Add to `tests/test_week2_unit.py`:

```python
def test_audit_engine_importable():
    """audit_engine must be importable (smoke check)."""
    from services.audit_engine import audit
    import inspect
    sig = inspect.signature(audit)
    assert "action" in sig.parameters, "audit() must accept 'action' parameter"
    assert "db" in sig.parameters, "audit() must accept 'db' parameter"


if __name__ == "__main__":
    # run all tests when file is executed directly
    test_upsell_suggestions_with_outstanding_live()
    test_upsell_suggestions_zero_outstanding()
    test_upsell_suggestions_default_zero()
    test_audit_engine_importable()
    print("All unit tests passed.")
```

(Replace the existing `if __name__ == "__main__":` block.)

- [ ] **Step 6: Run unit tests**

```
python tests/test_week2_unit.py
```

Expected: `All unit tests passed.`

- [ ] **Step 7: Verify import**

```
python -c "import main; print('Import OK')"
```

Expected: `Import OK`

- [ ] **Step 8: Commit**

```bash
git add routers/dealers.py routers/accounts.py tests/test_week2_unit.py
git commit -m "feat(audit): wire ORDER_CREATED, PAYMENT_RECORDED, RECEIPT_RECORDED audit log entries in dealers + accounts routers"
```

---

## Task 3: `/health` Endpoint

**Problem:** No health check endpoint exists. There is no way for a load balancer, uptime monitor (Uptime Robot / Grafana), or deployment script to verify the server is alive and can reach the DB.

**Files:**
- Create: `routers/health.py`
- Modify: `main.py`

---

- [ ] **Step 1: Write the failing test**

Add to `tests/test_week2_unit.py` (before the `if __name__ == "__main__":` block):

```python
def test_health_router_importable():
    """health router must exist and expose a FastAPI APIRouter."""
    from routers.health import router
    from fastapi import APIRouter
    assert isinstance(router, APIRouter), "health.router must be an APIRouter"

    # Verify /health route is registered
    routes = [r.path for r in router.routes]
    assert "/health" in routes, f"/health not in routes: {routes}"
```

And add `test_health_router_importable()` to the `if __name__ == "__main__":` block.

Run:
```
python tests/test_week2_unit.py
```

Expected: `ModuleNotFoundError: No module named 'routers.health'`

- [ ] **Step 2: Create `routers/health.py`**

```python
"""
Health Check Endpoint
---------------------
GET /health → JSON
  {
    "status": "ok" | "degraded",
    "db": "ok" | "error: <message>",
    "version": "1.0.0",
    "uptime_seconds": <int>
  }

Used by uptime monitors (Uptime Robot, Grafana, load balancers).
Returns HTTP 200 when healthy, HTTP 503 when DB unreachable.
"""
import time
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from database import AsyncSessionLocal

router = APIRouter(tags=["health"])

_start_time = time.time()


@router.get("/health")
async def health_check():
    """
    Lightweight liveness + readiness check.
    Executes SELECT 1 against the DB to confirm connectivity.
    """
    db_status = "ok"
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = f"error: {str(exc)[:120]}"

    healthy = db_status == "ok"
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "db": db_status,
            "version": "1.0.0",
            "uptime_seconds": int(time.time() - _start_time),
        },
    )
```

- [ ] **Step 3: Run unit test — confirm import test passes**

```
python tests/test_week2_unit.py
```

Expected: `All unit tests passed.`

- [ ] **Step 4: Register the health router in `main.py`**

In `main.py`, find the existing router imports block. Add after the last import line (around line 65):

```python
from routers.health import router as health_router
```

Then find the `app.include_router(...)` block. Add at the top (before other routers, so /health is first):

```python
app.include_router(health_router)
```

- [ ] **Step 5: Verify import**

```
python -c "import main; print('Import OK')"
```

Expected: `Import OK`

- [ ] **Step 6: Add functional test case (requires running server)**

Add this test tuple to `functional_test.py`'s `TESTS` list (find the list and add):

```python
("HLTH-01 Health check", "GET", "http://localhost:8000/health", None, '"status"'),
```

If the server is running, run `python functional_test.py` and verify `HLTH-01` passes.

- [ ] **Step 7: Commit**

```bash
git add routers/health.py main.py tests/test_week2_unit.py functional_test.py
git commit -m "feat: add GET /health endpoint — DB ping + uptime + version for monitoring integration"
```

---

## Task 4: Systemd Service Unit

**Problem:** OxyPC runs as a bare `uvicorn` process. If the server crashes or the host reboots, the process does not restart automatically. This is a single point of failure for a production ERP.

**Files:**
- Create: `services/oxypc-inventory.service`
- Create: `services/install-service.sh`

No Python changes required.

---

- [ ] **Step 1: Verify `services/` directory exists**

```
python -c "import os; print(os.path.isdir('services'))"
```

Expected: `True` (the directory exists and contains `aging_tracker.py`, `audit_engine.py`, etc.)

If `False`: `mkdir services`

- [ ] **Step 2: Create `services/oxypc-inventory.service`**

```ini
[Unit]
Description=OxyPC Inventory Server
Documentation=https://github.com/your-org/oxypc-inventory
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
# Change 'oxypc' to the Linux user that owns the app directory
User=oxypc
Group=oxypc
WorkingDirectory=/opt/oxypc-inventory
# All secrets via environment file — never hardcode here
EnvironmentFile=/opt/oxypc-inventory/.env
ExecStart=/opt/oxypc-inventory/venv/bin/python -m uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 2 \
    --log-level info
# Restart policy: restart within 5 s on any non-zero exit
Restart=on-failure
RestartSec=5
# Cap restart attempts: stop trying after 3 failures in 60 s
StartLimitInterval=60
StartLimitBurst=3
# Logs go to journald — view with: journalctl -u oxypc-inventory -f
StandardOutput=journal
StandardError=journal
SyslogIdentifier=oxypc-inventory
# Security hardening
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Create `services/install-service.sh`**

```bash
#!/usr/bin/env bash
# install-service.sh — Install OxyPC Inventory as a systemd service
# Usage: sudo ./services/install-service.sh
# Requires: systemd, running on Linux, must be run as root

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="${SCRIPT_DIR}/oxypc-inventory.service"
DEST="/etc/systemd/system/oxypc-inventory.service"
SERVICE_NAME="oxypc-inventory"

echo "=== OxyPC Inventory — Service Installer ==="

# Guard: must be root
if [[ "$EUID" -ne 0 ]]; then
    echo "ERROR: Run as root:  sudo $0"
    exit 1
fi

# Guard: service file must exist
if [[ ! -f "$SERVICE_FILE" ]]; then
    echo "ERROR: Service file not found: $SERVICE_FILE"
    exit 1
fi

# Install
echo "Installing ${SERVICE_FILE} → ${DEST}"
cp "$SERVICE_FILE" "$DEST"
chmod 644 "$DEST"

# Reload and enable
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo ""
echo "Service installed and enabled for auto-start on boot."
echo ""
echo "Commands:"
echo "  Start:   sudo systemctl start  $SERVICE_NAME"
echo "  Stop:    sudo systemctl stop   $SERVICE_NAME"
echo "  Restart: sudo systemctl restart $SERVICE_NAME"
echo "  Status:  sudo systemctl status $SERVICE_NAME"
echo "  Logs:    sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo "IMPORTANT: Edit $DEST to set the correct User/Group and WorkingDirectory"
echo "           before starting the service for the first time."
```

- [ ] **Step 4: Make install script executable**

```bash
git update-index --chmod=+x services/install-service.sh
```

(Or on Linux: `chmod +x services/install-service.sh`)

- [ ] **Step 5: Validate the service file structure**

Run on Linux (skip this step on Windows — the file will be deployed to Linux):
```bash
systemd-analyze verify services/oxypc-inventory.service 2>&1 || true
```

On Windows, verify the file exists and contains all required sections:
```
python -c "
content = open('services/oxypc-inventory.service').read()
for section in ['[Unit]', '[Service]', '[Install]', 'ExecStart', 'Restart=on-failure', 'EnvironmentFile']:
    assert section in content, f'Missing: {section}'
print('Service file structure OK')
"
```

Expected: `Service file structure OK`

- [ ] **Step 6: Commit**

```bash
git add services/oxypc-inventory.service services/install-service.sh
git commit -m "ops: add systemd service unit for Uvicorn — auto-restart on failure, journald logging, EnvironmentFile secret injection"
```

---

## Task 5: Smoke Test — Full Week 2 Verification

**Files:** No changes — verification only.

---

- [ ] **Step 1: Import check**

```
python -c "import main; print('Import OK')"
```

Expected: `Import OK`

- [ ] **Step 2: Confirm all routes registered**

```python
python -c "
import main
paths = [r.path for r in main.app.routes]
for expected in ['/health', '/dealers/{dealer_id}/ledger', '/reports/stock-aging']:
    assert expected in paths, f'Missing route: {expected}'
print('All expected routes present:', [p for p in paths if p in ['/health', '/dealers/{dealer_id}/ledger', '/reports/stock-aging']])
"
```

Expected: `All expected routes present: ['/health', '/dealers/{dealer_id}/ledger', '/reports/stock-aging']`

- [ ] **Step 3: Unit tests**

```
python tests/test_week2_unit.py
```

Expected: `All unit tests passed.`

- [ ] **Step 4: Confirm outstanding_amount writes removed**

```python
python -c "
import ast, sys
with open('routers/dealers.py') as f:
    src = f.read()
# These exact write lines must no longer exist
bad1 = 'dealer.outstanding_amount = float(dealer.outstanding_amount or 0) + due'
bad2 = 'dealer.outstanding_amount = max(0.0, float(dealer.outstanding_amount or 0) - amt)'
if bad1 in src:
    print('FAIL: outstanding_amount write (create_order) still present')
    sys.exit(1)
if bad2 in src:
    print('FAIL: outstanding_amount write (record_payment) still present')
    sys.exit(1)
print('OK: outstanding_amount writes removed')
"
```

Expected: `OK: outstanding_amount writes removed`

- [ ] **Step 5: Confirm audit calls present**

```python
python -c "
with open('routers/dealers.py') as f:
    src = f.read()
with open('routers/accounts.py') as f:
    src2 = f.read()
assert 'ORDER_CREATED' in src, 'Missing ORDER_CREATED audit in dealers.py'
assert 'PAYMENT_RECORDED' in src, 'Missing PAYMENT_RECORDED audit in dealers.py'
assert 'RECEIPT_RECORDED' in src2, 'Missing RECEIPT_RECORDED audit in accounts.py'
print('OK: all audit actions present')
"
```

Expected: `OK: all audit actions present`

- [ ] **Step 6: Confirm health router and service files exist**

```python
python -c "
import os
files = [
    'routers/health.py',
    'services/oxypc-inventory.service',
    'services/install-service.sh',
    'tests/test_week2_unit.py',
]
for f in files:
    assert os.path.exists(f), f'Missing: {f}'
    print(f'  OK: {f}')
print('All files present')
"
```

Expected: 4 `OK:` lines then `All files present`

- [ ] **Step 7: Git log — confirm 4 new commits**

```
git log --oneline -6
```

Expected: 4 new commits since `5eff5f8` (stock aging fix):
```
<sha> ops: add systemd service unit...
<sha> feat: add GET /health endpoint...
<sha> feat(audit): wire ORDER_CREATED, PAYMENT_RECORDED, RECEIPT_RECORDED...
<sha> fix(dealers): outstanding_amount compute on read...
5eff5f8 fix: stock aging — explicit dict bracket access...
```

---

## Self-Review

### Spec Coverage
| Requirement (audit_findings.md Week 2) | Task |
|---|---|
| Dealer outstanding_amount: compute on read | Task 1 ✅ |
| Add audit_logs writes for dealers/accounts | Task 2 ✅ |
| Process supervisor (systemd service) | Task 4 ✅ |
| /health endpoint + monitoring | Task 3 ✅ |

### Placeholder Scan
- All code blocks are complete and copy-pasteable.
- No "TBD", "TODO", or "similar to above" patterns.
- Exact git commands provided.

### Type Consistency
- `outstanding_live: float` — consistent across `_upsell_suggestions()` parameter, `dealer_profile()` computation, and template binding.
- `outstanding_map: dict[str, float]` — consistent across `dealer_list()` computation and `list.html` template `outstanding_map.get(d.id|string, 0)`.
- `AuditLog` record_id is always `str(record.id)` — consistent with existing patterns in `sales.py`.
