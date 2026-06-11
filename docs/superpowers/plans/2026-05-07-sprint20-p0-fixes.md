# Sprint 20 — P0 Bug Fixes: Stage Integrity + Session Expiry + QC Routing + Stock Transfer Audit + Parts Auto-Link

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five P0 blockers identified in the UAT Consolidated Register that prevent production launch.

**Architecture:** All fixes are pure code changes — no schema migrations required. The Sprint 19 migration (`20260501_0900`) already added `repair_job_id` to `spare_parts_consumption`. Stage lock adds one helper function to `services/control_engine.py` and calls it in three routers. Session expiry uses a non-httponly `session_expires` cookie set at login plus a Bootstrap JS modal in `base.html`. Warehouses are sourced dynamically from the existing `MasterData(category='warehouse')` table. Parts auto-link queries for the open `RepairJob` at the time of consumption recording.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, Jinja2, Bootstrap 5, pytest

---

## What Already Exists (do not rebuild)

- `services/control_engine.py` — `validate_transition()`, `invalidate_transitions_cache()`, `get_allowed_next_stages()` — do not touch these
- `models/master.py` — `MasterData` with `category='warehouse'` seed — already populated
- `models/spare_parts.py` — `SparePartConsumption.repair_job_id` FK column — already exists since Sprint 19
- `models/repair.py` — `RepairJob`, `RepairStatus` — complete
- `routers/auth.py` — `ACCESS_TOKEN_EXPIRE_MINUTES` read from config (default 1440 = 24 hrs) — correct
- `auth/dependencies.py` — `get_current_user`, `verify_csrf` — do not touch
- `routers/master.py` — `/admin/master/api/{category}` JSON endpoint — already built
- `tests/test_sprint20_unit.py` — already exists with 4 unrelated UX tests; do not modify it

## File Structure

| File | Change Type | Responsibility |
|------|-------------|----------------|
| `services/control_engine.py` | Modify | Add `assert_device_in_stage()` sync helper |
| `routers/auth.py` | Modify | Set `session_expires` cookie at login; add `/auth/extend-session` GET |
| `routers/repair.py` | Modify | Call `assert_device_in_stage` in `start_repair` and `complete_repair` |
| `routers/qc.py` | Modify | Call `assert_device_in_stage` in `qc_submit` |
| `routers/transfers.py` | Modify | Add `audit()` call; load warehouses from `MasterData` |
| `routers/spare_parts.py` | Modify | Auto-find open `RepairJob` and set `repair_job_id` in `record_consumption` |
| `templates/base.html` | Modify | Add session expiry JS modal before `</body>` |
| `tests/test_sprint20_p0_unit.py` | Create | Source-level unit tests for all five P0 fixes |

---

### Task 1: Write failing tests for all five P0 fixes

**Files:**
- Create: `tests/test_sprint20_p0_unit.py`

All tests in this sprint are source-inspection tests (read file text, assert the fix is present). Write them ALL now before touching any implementation file — they define the contract each task must satisfy.

- [ ] **Step 1: Create the test file**

```python
# tests/test_sprint20_p0_unit.py
"""Sprint 20 P0 unit tests — stage integrity, session expiry, QC routing,
stock transfer audit, parts auto-link."""
from pathlib import Path
_ROOT = Path(__file__).parent.parent


# ── TASK 2: Stage Ownership Check ─────────────────────────────────────────────

def test_assert_device_in_stage_defined_in_control_engine():
    """services/control_engine.py must define assert_device_in_stage."""
    src = (_ROOT / "services" / "control_engine.py").read_text(encoding="utf-8")
    assert "def assert_device_in_stage" in src, \
        "control_engine.py missing assert_device_in_stage function"


def test_assert_device_in_stage_raises_409():
    """assert_device_in_stage must raise HTTPException with status_code 409."""
    src = (_ROOT / "services" / "control_engine.py").read_text(encoding="utf-8")
    assert "409" in src, \
        "control_engine.py assert_device_in_stage must raise HTTPException(409)"


def test_repair_start_calls_assert_device_in_stage():
    """routers/repair.py start_repair must call assert_device_in_stage."""
    src = (_ROOT / "routers" / "repair.py").read_text(encoding="utf-8")
    assert "assert_device_in_stage" in src, \
        "repair.py missing assert_device_in_stage call"


def test_repair_complete_calls_assert_device_in_stage():
    """routers/repair.py complete_repair must also call assert_device_in_stage."""
    src = (_ROOT / "routers" / "repair.py").read_text(encoding="utf-8")
    # Must appear at least twice: once in start_repair, once in complete_repair
    assert src.count("assert_device_in_stage") >= 2, \
        "repair.py must call assert_device_in_stage in both start_repair and complete_repair"


def test_qc_submit_calls_assert_device_in_stage():
    """routers/qc.py qc_submit must call assert_device_in_stage."""
    src = (_ROOT / "routers" / "qc.py").read_text(encoding="utf-8")
    assert "assert_device_in_stage" in src, \
        "qc.py missing assert_device_in_stage call in qc_submit"


# ── TASK 1: Session Expiry ─────────────────────────────────────────────────────

def test_auth_sets_session_expires_cookie():
    """routers/auth.py login must set a session_expires cookie."""
    src = (_ROOT / "routers" / "auth.py").read_text(encoding="utf-8")
    assert "session_expires" in src, \
        "auth.py login must set session_expires cookie"


def test_extend_session_route_exists():
    """routers/auth.py must have /auth/extend-session GET route."""
    import importlib, sys
    sys.path.insert(0, str(_ROOT))
    mod = importlib.import_module("routers.auth")
    paths = [r.path for r in mod.router.routes]
    assert any("extend-session" in p for p in paths), \
        f"auth router missing /extend-session route. Routes: {paths}"


def test_base_html_has_session_warning_modal():
    """templates/base.html must contain session expiry warning JS."""
    src = (_ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "session_expires" in src, \
        "base.html missing session_expires JS logic"
    assert "sessionModal" in src or "session-modal" in src or "sessionWarning" in src, \
        "base.html missing session warning modal element"


# ── TASK 3: QC Pass Routing ───────────────────────────────────────────────────

def test_qc_pass_routes_to_cleaning():
    """routers/qc.py must route QC pass to DeviceStage.cleaning."""
    src = (_ROOT / "routers" / "qc.py").read_text(encoding="utf-8")
    assert "DeviceStage.cleaning" in src, \
        "qc.py missing DeviceStage.cleaning routing for QC pass"
    # Ensure cleaning assignment is inside the pass block (before the else)
    pass_idx = src.find('result_ == "pass"')
    else_idx = src.find("else:", pass_idx)
    cleaning_idx = src.find("DeviceStage.cleaning", pass_idx)
    assert pass_idx != -1, "qc.py missing result_ == 'pass' check"
    assert cleaning_idx != -1 and cleaning_idx < else_idx, \
        "qc.py DeviceStage.cleaning must be assigned inside the pass block, not else"


# ── TASK 4: Stock Transfer Audit ─────────────────────────────────────────────

def test_transfers_create_has_audit_call():
    """routers/transfers.py create_transfer must call audit()."""
    src = (_ROOT / "routers" / "transfers.py").read_text(encoding="utf-8")
    assert "await audit(" in src, \
        "transfers.py create_transfer missing audit() call"


def test_transfers_loads_warehouses_from_master_data():
    """routers/transfers.py must load warehouses from MasterData, not hardcoded list."""
    src = (_ROOT / "routers" / "transfers.py").read_text(encoding="utf-8")
    assert "MasterData" in src, \
        "transfers.py must import and use MasterData for warehouse list"
    assert 'category == "warehouse"' in src or "category='warehouse'" in src or \
           'category == \'warehouse\'' in src, \
        "transfers.py must query MasterData(category='warehouse')"


# ── TASK 5: Parts Auto-Link ───────────────────────────────────────────────────

def test_spare_parts_consume_links_repair_job():
    """routers/spare_parts.py record_consumption must auto-link to open RepairJob."""
    src = (_ROOT / "routers" / "spare_parts.py").read_text(encoding="utf-8")
    assert "RepairJob" in src, \
        "spare_parts.py record_consumption must import and query RepairJob"
    assert "repair_job_id" in src, \
        "spare_parts.py SparePartConsumption must receive repair_job_id"


def test_spare_parts_queries_in_progress_repair_job():
    """spare_parts.py must filter RepairJob by status == in_progress."""
    src = (_ROOT / "routers" / "spare_parts.py").read_text(encoding="utf-8")
    assert "in_progress" in src, \
        "spare_parts.py must filter open RepairJob by status == in_progress"
```

- [ ] **Step 2: Run the tests, confirm all 14 fail**

```bash
cd C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
python -m pytest tests/test_sprint20_p0_unit.py -v 2>&1 | head -50
```

Expected: 14 FAILures. If any unexpectedly pass, note it and skip that implementation step.

- [ ] **Step 3: Commit the test file**

```bash
git add tests/test_sprint20_p0_unit.py
git commit -m "test: add Sprint 20 P0 failing tests (stage lock, session, QC routing, transfer audit, parts link)"
```

---

### Task 2: Add `assert_device_in_stage` to Control Engine

**Files:**
- Modify: `services/control_engine.py`

The existing `validate_transition()` checks whether a given stage move is allowed in the `allowed_transitions` table. It does NOT check that the device is currently in the expected stage for the action being taken. This allows stale-tab submissions to act on devices that have already moved to a different stage.

`assert_device_in_stage` is a **synchronous** function (no DB query needed — stage is on the already-loaded device object) that raises `HTTPException(409)` if the device is in the wrong stage.

- [ ] **Step 1: Write the failing test check**

```bash
python -m pytest tests/test_sprint20_p0_unit.py::test_assert_device_in_stage_defined_in_control_engine tests/test_sprint20_p0_unit.py::test_assert_device_in_stage_raises_409 -v
```

Expected: FAIL — function does not exist yet.

- [ ] **Step 2: Add `assert_device_in_stage` to `services/control_engine.py`**

Open `services/control_engine.py`. After the `ControlEngineError` class definition (after line 21) and before the `_transitions_cache` line, insert:

```python
def assert_device_in_stage(device: Device, expected: DeviceStage) -> None:
    """
    Verify the device is currently in `expected` stage before performing any
    stage-scoped action (start repair, complete QC, etc.).

    Raises HTTPException(409) if the device has already moved to a different stage.
    Call this immediately after loading the device from the DB, before any writes.

    Usage:
        device = await db.execute(...).scalar_one_or_none()
        assert_device_in_stage(device, DeviceStage.l1)   # raises 409 if not in l1
    """
    current = device.current_stage.value if hasattr(device.current_stage, "value") else str(device.current_stage)
    target  = expected.value if hasattr(expected, "value") else str(expected)
    if current != target:
        raise HTTPException(
            status_code=409,
            detail=(
                f"STAGE CONFLICT: '{device.barcode}' is currently in stage '{current}', "
                f"not '{target}'. The device may have been moved. "
                f"Please refresh the page before retrying."
            ),
        )
```

The complete function goes at line 22 (between `class ControlEngineError` and `_transitions_cache`). The final top of the file should look like:

```python
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.device import Device, DeviceStage
from models.stage_control import AllowedTransition


class ControlEngineError(Exception):
    """Raised when a control rule is violated."""
    pass


def assert_device_in_stage(device: Device, expected: DeviceStage) -> None:
    """...(docstring above)..."""
    current = device.current_stage.value if hasattr(device.current_stage, "value") else str(device.current_stage)
    target  = expected.value if hasattr(expected, "value") else str(expected)
    if current != target:
        raise HTTPException(
            status_code=409,
            detail=(
                f"STAGE CONFLICT: '{device.barcode}' is currently in stage '{current}', "
                f"not '{target}'. The device may have been moved. "
                f"Please refresh the page before retrying."
            ),
        )


# ── AllowedTransitions in-memory cache ──────────────────────────────────────
_transitions_cache: dict | None = None
```

- [ ] **Step 3: Run the two tests, confirm they pass**

```bash
python -m pytest tests/test_sprint20_p0_unit.py::test_assert_device_in_stage_defined_in_control_engine tests/test_sprint20_p0_unit.py::test_assert_device_in_stage_raises_409 -v
```

Expected: PASS PASS

- [ ] **Step 4: Add `assert_device_in_stage` import and calls to `routers/repair.py`**

At the top of `routers/repair.py`, the current import line (line 21) reads:
```python
from services.control_engine import validate_transition, validate_repair_level, get_allowed_next_stages
```

Change it to:
```python
from services.control_engine import validate_transition, validate_repair_level, get_allowed_next_stages, assert_device_in_stage
```

In `start_repair` (around line 134–136): after loading the device and checking it exists, and after computing `device_stage`, add the stage assertion. The current code reads:

```python
    device_stage = STAGE_MAP.get(stage.lower())
    if not device_stage:
        raise HTTPException(400, "Invalid repair stage")
    level    = LEVEL_MAP.get(stage.lower(), 1)
```

Change it to:

```python
    device_stage = STAGE_MAP.get(stage.lower())
    if not device_stage:
        raise HTTPException(400, "Invalid repair stage")
    assert_device_in_stage(device, device_stage)
    level    = LEVEL_MAP.get(stage.lower(), 1)
```

In `complete_repair` (around line 218–219): after loading the device (`device = dev_result.scalar_one_or_none()`), add the stage assertion. The current code reads:

```python
    dev_result = await db.execute(select(Device).where(Device.id == job.device_id))
    device = dev_result.scalar_one_or_none()
```

Change it to:

```python
    dev_result = await db.execute(select(Device).where(Device.id == job.device_id))
    device = dev_result.scalar_one_or_none()
    if device:
        expected_stage = STAGE_MAP.get(stage)
        if expected_stage:
            assert_device_in_stage(device, expected_stage)
```

- [ ] **Step 5: Run the repair tests**

```bash
python -m pytest tests/test_sprint20_p0_unit.py::test_repair_start_calls_assert_device_in_stage tests/test_sprint20_p0_unit.py::test_repair_complete_calls_assert_device_in_stage -v
```

Expected: PASS PASS

- [ ] **Step 6: Add `assert_device_in_stage` import and call to `routers/qc.py`**

At the top of `routers/qc.py`, the current import line reads:
```python
from services.control_engine import validate_transition, get_allowed_next_stages
```

Change it to:
```python
from services.control_engine import validate_transition, get_allowed_next_stages, assert_device_in_stage
```

In `qc_submit` (after line 122, inside the `if device:` block but before the scoring logic), add:

```python
    if not device:
        return templates.TemplateResponse("qc/form.html", {
            "request": request, "device": None, "current_user": current_user,
            "qc_history": [], "fail_count": 0,
            "error": f"Device {barcode} not found",
        })

    assert_device_in_stage(device, DeviceStage.qc_check)
```

The `assert_device_in_stage` line goes immediately after the `if not device` block, before any scoring logic.

- [ ] **Step 7: Run the QC stage test**

```bash
python -m pytest tests/test_sprint20_p0_unit.py::test_qc_submit_calls_assert_device_in_stage -v
```

Expected: PASS

- [ ] **Step 8: Run the full test suite, confirm no regressions**

```bash
python -m pytest --tb=short -q 2>&1 | tail -10
```

Expected: all existing tests pass; new stage tests pass.

- [ ] **Step 9: Commit**

```bash
git add services/control_engine.py routers/repair.py routers/qc.py
git commit -m "feat: add stage ownership check (assert_device_in_stage) to repair and QC routers"
```

---

### Task 3: QC Pass Always Routes to Cleaning

**Files:**
- Modify: `routers/qc.py` (confirm and enforce)
- Test: `tests/test_sprint20_p0_unit.py::test_qc_pass_routes_to_cleaning`

The existing code already sends QC pass to `DeviceStage.cleaning` (correct). This task confirms the routing is correct and ensures the test passes. The real risk is that if `result` form field is empty (not submitted), the code falls to `result_ = "fail"` and uses the `send_to_stage` dropdown value. This task adds a guard.

- [ ] **Step 1: Run the test, confirm if it passes already**

```bash
python -m pytest tests/test_sprint20_p0_unit.py::test_qc_pass_routes_to_cleaning -v
```

If PASS: this test already passes, Task 3 implementation is done. Still commit the note and move on.

If FAIL: proceed to Step 2.

- [ ] **Step 2: Confirm QC pass routing in `routers/qc.py`**

In `qc_submit`, verify the pass block reads exactly:
```python
    if result_ == "pass":
        device.grade        = grade
        device.updated_at   = datetime.utcnow()
        to_stage = DeviceStage.cleaning
        # Skip cosmetic for A grade already clean? Admin can always override via move
        await validate_transition(device, to_stage, db, override_admin=is_admin)
        notes_text = f"QC Passed — Score {total_score}/100 Grade {grade}"
        device.current_stage = to_stage
```

This is the existing correct code. If it's present, the test should pass. If `DeviceStage.cleaning` is not there, add it.

- [ ] **Step 3: Add `send_to_stage` guard for QC pass**

Also add a guard so that even if a client submits `result=""` with valid scores, it doesn't silently default to fail. In `qc_submit`, the section that computes `result_` currently reads:

```python
    if result in ("pass", "fail"):
        result_ = result
    elif total_score is not None:
        result_ = "pass" if total_score >= 70 else "fail"
    else:
        result_ = "fail"
```

Change `result_ = "fail"` (the final else) to explicitly log that no result was provided:

```python
    if result in ("pass", "fail"):
        result_ = result
    elif total_score is not None:
        result_ = "pass" if total_score >= 70 else "fail"
    else:
        # No radio button submitted and no scores — treat as fail; inspector must
        # provide at least one component score or an explicit pass/fail radio selection
        result_ = "fail"
```

(This is unchanged — the existing comment makes intent clear. No code change needed unless the comment is missing.)

- [ ] **Step 4: Run the test**

```bash
python -m pytest tests/test_sprint20_p0_unit.py::test_qc_pass_routes_to_cleaning -v
```

Expected: PASS

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest --tb=short -q 2>&1 | tail -10
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add routers/qc.py
git commit -m "test: confirm QC pass routes to cleaning; stage guard added in Task 2"
```

---

### Task 4: Stock Transfer Audit + Dynamic Warehouses

**Files:**
- Modify: `routers/transfers.py`
- Test: `tests/test_sprint20_p0_unit.py::test_transfers_create_has_audit_call`, `test_transfers_loads_warehouses_from_master_data`

Two issues: (1) `create_transfer` has no audit trail — violates CLAUDE.md requirement for audit on all write operations; (2) the `WAREHOUSES` list is hardcoded, bypassing the Master Data module that already governs warehouse categories.

- [ ] **Step 1: Run the failing tests**

```bash
python -m pytest tests/test_sprint20_p0_unit.py::test_transfers_create_has_audit_call tests/test_sprint20_p0_unit.py::test_transfers_loads_warehouses_from_master_data -v
```

Expected: FAIL FAIL

- [ ] **Step 2: Update imports in `routers/transfers.py`**

Replace the current imports section. The existing imports are (lines 1–13):
```python
from datetime import datetime
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from templates_config import templates
from database import get_db
from models.user import User, UserRole
from models.device import Device
from models.lot import Lot
from models.stock_transfer import StockTransfer
from auth.dependencies import get_current_user, require_roles, verify_csrf
```

Replace with:
```python
from datetime import datetime
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from templates_config import templates
from database import get_db
from models.user import User, UserRole
from models.device import Device
from models.lot import Lot
from models.stock_transfer import StockTransfer
from models.master import MasterData
from auth.dependencies import get_current_user, require_roles, verify_csrf
from services.audit_engine import audit
```

- [ ] **Step 3: Remove the hardcoded `WAREHOUSES` constant and replace list_transfers with a dynamic version**

Remove the hardcoded `WAREHOUSES` list at lines 18–26:
```python
WAREHOUSES = [
    "TRC 1st Floor",
    "TRC 2nd Floor",
    "TRC 3rd Floor",
    "Bluemonk House Showroom",
    "Bluemonk Showroom",
    "Other",
]
```

Keep the `DEPARTMENTS` list (it has no MasterData category yet — keep hardcoded for now).

Replace the `new_transfer_form` GET handler body to load warehouses from MasterData. Find this function (starts around line 58):

```python
@router.get("/transfers/new", response_class=HTMLResponse)
async def new_transfer_form(
    request: Request,
    barcode: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    device = None
    if barcode:
        result = await db.execute(
            select(Device, Lot.lot_number)
            .join(Lot, Device.lot_id == Lot.id, isouter=True)
            .where(Device.barcode == barcode)
        )
        row = result.first()
        if row:
            device, lot_number = row
            device._lot_number = lot_number
    return templates.TemplateResponse("transfers/form.html", {
        "request": request, "device": device, "barcode": barcode,
        "warehouses": WAREHOUSES, "departments": DEPARTMENTS,
        "current_user": current_user, "error": None,
        "now": datetime.utcnow(),
    })
```

Replace the body with:

```python
@router.get("/transfers/new", response_class=HTMLResponse)
async def new_transfer_form(
    request: Request,
    barcode: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    device = None
    if barcode:
        result = await db.execute(
            select(Device, Lot.lot_number)
            .join(Lot, Device.lot_id == Lot.id, isouter=True)
            .where(Device.barcode == barcode)
        )
        row = result.first()
        if row:
            device, lot_number = row
            device._lot_number = lot_number

    # Load warehouses from Master Data (category='warehouse', active only)
    wh_result = await db.execute(
        select(MasterData.value)
        .where(MasterData.category == "warehouse", MasterData.is_active == True)
        .order_by(MasterData.display_order, MasterData.value)
    )
    warehouses = [r[0] for r in wh_result.all()] or FALLBACK_WAREHOUSES

    return templates.TemplateResponse("transfers/form.html", {
        "request": request, "device": device, "barcode": barcode,
        "warehouses": warehouses, "departments": DEPARTMENTS,
        "current_user": current_user, "error": None,
        "now": datetime.utcnow(),
    })
```

Add a fallback constant at the top of the file (after the imports, before the router definition) — this is used only if MasterData returns nothing:

```python
FALLBACK_WAREHOUSES = [
    "TRC 1st Floor",
    "TRC 2nd Floor",
    "TRC 3rd Floor",
    "Bluemonk House Showroom",
    "Bluemonk Showroom",
    "Other",
]

DEPARTMENTS = [
    "L1/L2 Engineer",
    "L3 Engineer",
    "QC",
    "Sales",
    "Cosmetic Refurb",
    "Management",
]
```

- [ ] **Step 4: Add `audit()` call to `create_transfer`**

In `create_transfer`, after `db.add(transfer)` and before `await db.commit()`, add the audit call. The current ending of `create_transfer` looks like:

```python
    db.add(transfer)
    # Update device warehouse field if it exists
    if hasattr(device, "warehouse") and to_warehouse:
        device.warehouse = to_warehouse
        device.updated_at = datetime.utcnow()

    db.add(transfer)
    await db.commit()
    return RedirectResponse(url=f"/transfers?success=Transfer+recorded+for+{barcode}", status_code=302)
```

Change to:

```python
    db.add(transfer)
    # Update device warehouse field if it exists
    if hasattr(device, "warehouse") and to_warehouse:
        device.warehouse = to_warehouse
        device.updated_at = datetime.utcnow()

    await audit(db, user=current_user, action="STOCK_TRANSFER",
                table_name="stock_transfers",
                record_id=str(transfer.id) if hasattr(transfer, "id") else None,
                new_value={
                    "barcode": barcode,
                    "transfer_type": transfer_type,
                    "from_warehouse": from_warehouse,
                    "to_warehouse": to_warehouse,
                },
                request=request)

    await db.commit()
    return RedirectResponse(url=f"/transfers?success=Transfer+recorded+for+{barcode}", status_code=302)
```

Note: `transfer.id` is populated by SQLAlchemy only after `db.add()` and flush; pass `None` as record_id here — the audit engine handles null record_id gracefully.

- [ ] **Step 5: Run the transfer tests**

```bash
python -m pytest tests/test_sprint20_p0_unit.py::test_transfers_create_has_audit_call tests/test_sprint20_p0_unit.py::test_transfers_loads_warehouses_from_master_data -v
```

Expected: PASS PASS

- [ ] **Step 6: Run full test suite**

```bash
python -m pytest --tb=short -q 2>&1 | tail -10
```

Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add routers/transfers.py
git commit -m "fix: add audit trail and MasterData-sourced warehouses to stock transfers"
```

---

### Task 5: Parts Auto-Link to Open Repair Job

**Files:**
- Modify: `routers/spare_parts.py`
- Test: `tests/test_sprint20_p0_unit.py::test_spare_parts_consume_links_repair_job`, `test_spare_parts_queries_in_progress_repair_job`

When a spare parts manager records consumption via `/spare-parts/consume`, the `repair_job_id` field on `SparePartConsumption` is always `None`. If the device has an open repair job, the consumption should be linked to it so the COGS calculation (Sprint 19) picks it up correctly.

`repair.py::complete_repair` already links parts correctly via `repair_job_id=job.id`. This task fixes the standalone consumption form.

- [ ] **Step 1: Run the failing tests**

```bash
python -m pytest tests/test_sprint20_p0_unit.py::test_spare_parts_consume_links_repair_job tests/test_sprint20_p0_unit.py::test_spare_parts_queries_in_progress_repair_job -v
```

Expected: FAIL FAIL (RepairJob not imported in spare_parts.py)

- [ ] **Step 2: Add RepairJob import to `routers/spare_parts.py`**

The current imports in `spare_parts.py` include:
```python
from models.spare_parts import SparePart, SparePartPurchase, SparePartConsumption, RAMTracking
```

Add `RepairJob` and `RepairStatus` imports after this line:

```python
from models.repair import RepairJob, RepairStatus
```

- [ ] **Step 3: Auto-find open RepairJob in `record_consumption`**

In `routers/spare_parts.py`, in the `record_consumption` function, the current device lookup block (around lines 234–239) reads:

```python
    device_id = None
    if device_barcode:
        dev_result = await db.execute(select(Device).where(Device.barcode == device_barcode))
        dev = dev_result.scalar_one_or_none()
        if dev:
            device_id = dev.id
```

Replace with:

```python
    device_id = None
    repair_job_id = None
    if device_barcode:
        dev_result = await db.execute(select(Device).where(Device.barcode == device_barcode))
        dev = dev_result.scalar_one_or_none()
        if dev:
            device_id = dev.id
            # Auto-link to the open repair job for this device (if any)
            job_result = await db.execute(
                select(RepairJob)
                .where(
                    RepairJob.device_id == dev.id,
                    RepairJob.status == RepairStatus.in_progress,
                )
                .order_by(RepairJob.started_at.desc())
                .limit(1)
            )
            open_job = job_result.scalars().first()
            if open_job:
                repair_job_id = open_job.id
```

Then update the `SparePartConsumption` constructor call (around line 242) to include `repair_job_id`:

```python
    consumption = SparePartConsumption(
        part_id=part_id, qty_used=qty_used,
        unit_cost=float(part.unit_price), total_cost=total,
        device_id=device_id,
        repair_job_id=repair_job_id,
        lot_id=lot_id or None, stage=stage or None,
        used_by=current_user.username, notes=notes or None,
    )
```

- [ ] **Step 4: Run the parts auto-link tests**

```bash
python -m pytest tests/test_sprint20_p0_unit.py::test_spare_parts_consume_links_repair_job tests/test_sprint20_p0_unit.py::test_spare_parts_queries_in_progress_repair_job -v
```

Expected: PASS PASS

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest --tb=short -q 2>&1 | tail -10
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add routers/spare_parts.py
git commit -m "fix: auto-link spare parts consumption to open repair job"
```

---

### Task 6: Session Expiry Warning Popup + Extend-Session Endpoint

**Files:**
- Modify: `routers/auth.py`
- Modify: `templates/base.html`
- Test: `tests/test_sprint20_p0_unit.py::test_auth_sets_session_expires_cookie`, `test_extend_session_route_exists`, `test_base_html_has_session_warning_modal`

The JWT token already defaults to 1440 minutes (24 hours) via `config.py`. The bug reported in UAT ("15 minutes") is likely the deployed `config.ini` having a low value, or the user confused account lockout (15 mins) with session expiry. This task adds a JS warning popup that:

1. Reads the `session_expires` cookie set at login (non-httponly, epoch seconds)
2. Shows a Bootstrap modal 5 minutes before expiry
3. Provides "Stay Logged In" button that calls `GET /auth/extend-session` (AJAX, no page reload)
4. Provides "Log Out" button

- [ ] **Step 1: Run the failing tests**

```bash
python -m pytest tests/test_sprint20_p0_unit.py::test_auth_sets_session_expires_cookie tests/test_sprint20_p0_unit.py::test_extend_session_route_exists tests/test_sprint20_p0_unit.py::test_base_html_has_session_warning_modal -v
```

Expected: FAIL FAIL FAIL

- [ ] **Step 2: Add `session_expires` cookie and `/auth/extend-session` to `routers/auth.py`**

The current `login` POST handler ends with:

```python
    csrf_tok = secrets.token_hex(32)
    response = RedirectResponse(url="/", status_code=302)
    _max_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    response.set_cookie("access_token", token, httponly=True, samesite="strict",
                        max_age=_max_age)
    response.set_cookie("csrf_token", csrf_tok, httponly=False, samesite="strict",
                        max_age=_max_age)
    return response
```

Add `datetime` to the imports at the top (it's already imported). Add `timedelta` if not present. Change the login return block to:

```python
    csrf_tok = secrets.token_hex(32)
    response = RedirectResponse(url="/", status_code=302)
    _max_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    import time as _time
    _expires_epoch = int(_time.time()) + _max_age
    response.set_cookie("access_token", token, httponly=True, samesite="strict",
                        max_age=_max_age)
    response.set_cookie("csrf_token", csrf_tok, httponly=False, samesite="strict",
                        max_age=_max_age)
    # session_expires: non-httponly so JS can read it for the warning popup
    response.set_cookie("session_expires", str(_expires_epoch), httponly=False,
                        samesite="strict", max_age=_max_age)
    return response
```

Add the `/auth/extend-session` endpoint after the `logout` handler (end of the file):

```python
@router.get("/extend-session")
async def extend_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Re-issues JWT and session_expires cookies without a page reload.
    Called by the session warning popup's 'Stay Logged In' button via fetch().
    Returns JSON {ok: true} on success, 401 if the current token is expired/invalid.
    """
    from fastapi.responses import JSONResponse
    from auth.dependencies import get_current_user as _get_user
    try:
        current_user = await _get_user(request, db)
    except Exception:
        return JSONResponse({"ok": False, "reason": "session_expired"}, status_code=401)

    token = create_access_token({"sub": current_user.username, "role": current_user.role})
    csrf_tok = secrets.token_hex(32)
    _max_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    import time as _time
    _expires_epoch = int(_time.time()) + _max_age

    response = JSONResponse({"ok": True})
    response.set_cookie("access_token", token, httponly=True, samesite="strict",
                        max_age=_max_age)
    response.set_cookie("csrf_token", csrf_tok, httponly=False, samesite="strict",
                        max_age=_max_age)
    response.set_cookie("session_expires", str(_expires_epoch), httponly=False,
                        samesite="strict", max_age=_max_age)
    return response
```

- [ ] **Step 3: Run the auth tests**

```bash
python -m pytest tests/test_sprint20_p0_unit.py::test_auth_sets_session_expires_cookie tests/test_sprint20_p0_unit.py::test_extend_session_route_exists -v
```

Expected: PASS PASS

- [ ] **Step 4: Add session warning modal to `templates/base.html`**

Insert the following block just before the closing `</body>` tag (currently line 391). The existing file ends with:

```html
{% block scripts %}{% endblock %}
<script>
/* CSRF Auto-Inject ... */
...
</script>
</body>
</html>
```

Insert between `{% block scripts %}{% endblock %}` and the `<script>/* CSRF Auto-Inject */` block:

```html
<!-- Session Expiry Warning Modal -->
<div class="modal fade" id="sessionModal" tabindex="-1" data-bs-backdrop="static" data-bs-keyboard="false">
  <div class="modal-dialog modal-sm">
    <div class="modal-content border-warning">
      <div class="modal-header bg-warning text-dark py-2">
        <h6 class="modal-title mb-0"><i class="bi bi-clock-history me-2"></i>Session Expiring Soon</h6>
      </div>
      <div class="modal-body py-3 text-center">
        <p class="mb-2 small">Your session expires in <strong id="sessionCountdown">5:00</strong>.</p>
        <p class="text-muted small mb-0">Click <em>Stay Logged In</em> to continue working.</p>
      </div>
      <div class="modal-footer py-2 justify-content-center gap-2">
        <button type="button" class="btn btn-warning btn-sm" id="sessionExtendBtn">
          <i class="bi bi-arrow-clockwise me-1"></i>Stay Logged In
        </button>
        <a href="/auth/login" class="btn btn-outline-secondary btn-sm">Log Out</a>
      </div>
    </div>
  </div>
</div>
<script>
(function () {
  var WARN_BEFORE_SECS = 300; // show modal 5 minutes before expiry
  function getCookieVal(name) {
    var match = document.cookie.split(';')
      .map(function(c){ return c.trim(); })
      .find(function(c){ return c.startsWith(name + '='); });
    return match ? decodeURIComponent(match.split('=')[1]) : null;
  }
  var expiresEpoch = parseInt(getCookieVal('session_expires') || '0', 10);
  if (!expiresEpoch) return; // no cookie — skip (e.g. if user cleared cookies)

  var sessionModal = null;
  var countdownInterval = null;

  function showWarning(secsLeft) {
    if (!sessionModal) {
      sessionModal = new bootstrap.Modal(document.getElementById('sessionModal'));
    }
    sessionModal.show();
    updateCountdown(secsLeft);
    countdownInterval = setInterval(function() {
      secsLeft -= 1;
      if (secsLeft <= 0) {
        clearInterval(countdownInterval);
        window.location.href = '/auth/login';
      } else {
        updateCountdown(secsLeft);
      }
    }, 1000);
  }

  function updateCountdown(secs) {
    var m = Math.floor(secs / 60), s = secs % 60;
    document.getElementById('sessionCountdown').textContent =
      m + ':' + (s < 10 ? '0' : '') + s;
  }

  // Schedule modal appearance
  var nowEpoch = Math.floor(Date.now() / 1000);
  var totalSecs = expiresEpoch - nowEpoch;
  if (totalSecs <= 0) {
    window.location.href = '/auth/login'; // already expired
    return;
  }
  var warnIn = (totalSecs - WARN_BEFORE_SECS) * 1000;
  if (warnIn <= 0) {
    // Already within warning window — show immediately with remaining time
    showWarning(totalSecs);
  } else {
    setTimeout(function() { showWarning(WARN_BEFORE_SECS); }, warnIn);
  }

  // Stay Logged In button
  document.getElementById('sessionExtendBtn').addEventListener('click', function() {
    fetch('/auth/extend-session', { credentials: 'same-origin' })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.ok) {
          clearInterval(countdownInterval);
          if (sessionModal) sessionModal.hide();
          // Re-schedule from new session_expires cookie
          var newExpires = parseInt(getCookieVal('session_expires') || '0', 10);
          var nowNow = Math.floor(Date.now() / 1000);
          var newWarnIn = (newExpires - nowNow - WARN_BEFORE_SECS) * 1000;
          if (newWarnIn > 0) {
            setTimeout(function() { showWarning(WARN_BEFORE_SECS); }, newWarnIn);
          }
        } else {
          window.location.href = '/auth/login';
        }
      })
      .catch(function() { window.location.href = '/auth/login'; });
  });
})();
</script>
```

- [ ] **Step 5: Run the base.html test**

```bash
python -m pytest tests/test_sprint20_p0_unit.py::test_base_html_has_session_warning_modal -v
```

Expected: PASS

- [ ] **Step 6: Run full test suite**

```bash
python -m pytest --tb=short -q 2>&1 | tail -10
```

Expected: all passing (249+ tests).

- [ ] **Step 7: Commit**

```bash
git add routers/auth.py templates/base.html
git commit -m "feat: session expiry warning popup + /auth/extend-session endpoint"
```

---

### Task 7: Final verification — all Sprint 20 P0 tests pass

- [ ] **Step 1: Run only the Sprint 20 P0 tests**

```bash
python -m pytest tests/test_sprint20_p0_unit.py -v
```

Expected: 14 tests, all PASS.

- [ ] **Step 2: Run the full test suite**

```bash
python -m pytest --tb=short -q 2>&1 | tail -5
```

Expected: all existing tests pass, no regressions.

- [ ] **Step 3: Smoke test the server**

```bash
python main.py &
curl -s http://localhost:8000/health | python -c "import sys,json; d=json.load(sys.stdin); print('OK' if d.get('status')=='ok' else 'FAIL')"
```

Expected: `OK`

- [ ] **Step 4: Final commit + tag**

```bash
git add -A
git commit -m "sprint(20): P0 fixes — stage integrity, session expiry, QC routing, transfer audit, parts auto-link" --allow-empty
```

---

## Self-Review

### Spec Coverage

| P0 Item | Task | Covered? |
|---------|------|----------|
| Session expiry — 24hr + popup | Task 6 | ✅ |
| Stage integrity — stale-stage action prevention | Task 2 | ✅ |
| QC routing — pass always → cleaning | Task 3 | ✅ |
| Stock transfer — audit + dynamic warehouses | Task 4 | ✅ |
| Parts auto-link — consumption → open repair job | Task 5 | ✅ |
| Master Data central control | Not needed — already built (`routers/master.py`) | ✅ |
| Finance sync (supplier payments → POs) | Deferred to Sprint 21 | — |

### Placeholder Scan

No placeholders present. Every code block is complete and implementable.

### Type Consistency

- `assert_device_in_stage(device: Device, expected: DeviceStage)` — used with `DeviceStage.l1`, `DeviceStage.qc_check`, etc. — consistent with imports in `repair.py` and `qc.py`.
- `repair_job_id` — UUID from `RepairJob.id` — matches `SparePartConsumption.repair_job_id` FK type (UUID).
- `session_expires` cookie — epoch integer as string — consistent between `auth.py` setter and `base.html` reader.
- `FALLBACK_WAREHOUSES` — list of strings — same type as the dynamic MasterData query output.

### Migration Check

No schema changes required. All fixes are code-only. The `repair_job_id` column on `spare_parts_consumption` was added in Sprint 19 migration `20260501_0900`. Alembic head remains `20260502_0800`.
