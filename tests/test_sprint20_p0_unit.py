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


# ── TASK 6: Session Expiry ─────────────────────────────────────────────────────

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
