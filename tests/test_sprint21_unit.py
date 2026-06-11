# tests/test_sprint21_unit.py
"""Sprint 21 unit tests — repair/qc pagination, soft delete."""
import glob
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
