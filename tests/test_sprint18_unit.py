"""Sprint 18 unit tests — verify index=True is present on hot-query columns."""
import os

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "models")

def get_model_source(filename: str) -> str:
    path = os.path.join(MODELS_DIR, filename)
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_device_current_stage_indexed():
    src = get_model_source("device.py")
    idx = src.index("current_stage")
    segment = src[idx:idx+200]
    assert "index=True" in segment, "Device.current_stage missing index=True"


def test_repair_job_device_id_indexed():
    src = get_model_source("repair.py")
    idx = src.index("device_id")
    assert "index=True" in src[idx:idx+100], "RepairJob.device_id missing index=True"


def test_dealer_call_next_followup_indexed():
    src = get_model_source("dealers.py")
    idx = src.index("next_followup_date")
    seg = src[idx:idx+150]
    assert "index=True" in seg, "DealerCall.next_followup_date missing index=True"


def test_crm_activity_contact_id_indexed():
    src = get_model_source("crm.py")
    cls_idx = src.index("class CRMActivity")
    seg = src[cls_idx:cls_idx+1000]
    contact_idx = seg.index("contact_id")
    assert "index=True" in seg[contact_idx:contact_idx+120], "CRMActivity.contact_id missing index=True"


def test_dashboard_uses_group_by_for_stage_counts():
    src = open("routers/dashboard.py", encoding="utf-8").read()
    assert "GROUP BY" in src.upper() or "group_by" in src, \
        "dashboard.py stage_counts still uses per-stage loop instead of GROUP BY"


def test_dashboard_lot_pl_uses_batch_queries():
    src = open("routers/dashboard.py", encoding="utf-8").read()
    # N+1 pattern: await db.execute called inside the per-lot assembly loop.
    # With batch queries the loop body only does dict.get() — no DB calls.
    loop_start = src.find("for lot in lots:")
    assert loop_start != -1, "Expected 'for lot in lots:' assembly loop not found"
    loop_body = src[loop_start:loop_start + 600]
    assert "await db.execute" not in loop_body, \
        "dashboard.py still calls await db.execute inside 'for lot in lots:' (N+1 pattern)"


def test_control_engine_has_cache():
    src = open("services/control_engine.py", encoding="utf-8").read()
    assert "_transitions_cache" in src or "lru_cache" in src or "_cache" in src, \
        "control_engine.py does not cache AllowedTransitions"


def test_reports_sales_has_limit():
    src = open("routers/reports.py", encoding="utf-8").read()
    # Scope to the /sales route section specifically (not stage_movements which already has limit)
    sales_route_idx = src.find('"/sales"')
    assert sales_route_idx != -1, "Could not find \"/sales\" route in reports.py"
    sales_section = src[sales_route_idx:sales_route_idx + 900]
    assert ".limit(" in sales_section, \
        "reports.py /sales route query has no .limit() — unbounded query risk"


def test_composite_indexes_migration_exists():
    """Verify Alembic migration file for composite indexes exists."""
    import glob, os
    migrations = glob.glob(
        os.path.join(os.path.dirname(__file__), "..", "alembic", "versions", "*.py")
    )
    contents = [open(m).read() for m in migrations]
    found = any("ix_devices_stage_subcategory" in c for c in contents)
    assert found, "Composite index migration for ix_devices_stage_subcategory not found in alembic/versions/"
