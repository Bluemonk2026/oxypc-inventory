# tests/test_sprint19_unit.py
"""Sprint 19 unit tests — CostConfig model, backup script, P&L calculation."""
from pathlib import Path
_ROOT = Path(__file__).parent.parent


def test_cost_config_model_fields():
    """CostConfig ORM model must have key, value, description, updated_by, updated_at."""
    src = (_ROOT / "models/cost_config.py").read_text(encoding="utf-8")
    for field in ["key", "value", "description", "updated_by", "updated_at"]:
        assert field in src, f"CostConfig missing field: {field}"


def test_cost_config_exported_from_models_init():
    """models/__init__.py must export CostConfig."""
    src = (_ROOT / "models/__init__.py").read_text(encoding="utf-8")
    assert "CostConfig" in src, "models/__init__.py missing CostConfig export"


def test_cost_config_migration_exists():
    """Migration file for cost_config must exist with correct down_revision."""
    import glob
    files = glob.glob(str(_ROOT / "alembic/versions/*cost_config*.py"))
    assert files, "No cost_config migration file found"
    content = Path(files[0]).read_text(encoding="utf-8")
    assert "20260501_0900" in content, "Migration down_revision must be 20260501_0900"
    assert "cost_config" in content, "Migration must create cost_config table"


def test_db_validator_seeds_cost_config():
    """db_validator.py must seed repair_labour_rate and cosmetic_rate."""
    src = (_ROOT / "db_validator.py").read_text(encoding="utf-8")
    assert "repair_labour_rate" in src, "db_validator missing repair_labour_rate seed"
    assert "cosmetic_rate" in src, "db_validator missing cosmetic_rate seed"


def test_admin_has_cost_config_routes():
    """admin router must expose GET and POST /cost-config routes."""
    import importlib
    mod = importlib.import_module("routers.admin")
    router = mod.router
    paths = [r.path for r in router.routes]
    assert any("cost-config" in p for p in paths), \
        f"No cost-config route in admin router. Routes: {paths}"
    # Verify both GET and POST handlers exist by name
    assert hasattr(mod, "cost_config_view"), "cost_config_view handler not found in admin.py"
    assert hasattr(mod, "cost_config_save"), "cost_config_save handler not found in admin.py"


def test_cost_config_template_exists():
    """templates/admin/cost_config.html must exist with required form fields."""
    from pathlib import Path
    _ROOT = Path(__file__).parent.parent
    content = (_ROOT / "templates" / "admin" / "cost_config.html").read_text(encoding="utf-8")
    assert "repair_labour_rate" in content, "cost_config.html missing repair_labour_rate"
    assert "cosmetic_rate" in content, "cost_config.html missing cosmetic_rate"
    assert 'method="post"' in content.lower() or "method='post'" in content.lower(), \
        "cost_config.html missing POST form"
    assert "csrf_token" in content, "cost_config.html missing csrf_token"


def test_dashboard_loads_cost_config():
    """routers/dashboard.py must import CostConfig for P&L rate loading."""
    from pathlib import Path
    _ROOT = Path(__file__).parent.parent
    src = (_ROOT / "routers" / "dashboard.py").read_text(encoding="utf-8")
    assert "CostConfig" in src, "dashboard.py must import CostConfig"


def test_dashboard_cosmetic_cost_in_lot_pl():
    """routers/dashboard.py lot_pl must include cosmetic_cost key."""
    from pathlib import Path
    _ROOT = Path(__file__).parent.parent
    src = (_ROOT / "routers" / "dashboard.py").read_text(encoding="utf-8")
    assert "cosmetic_cost" in src, "dashboard.py lot_pl missing cosmetic_cost"


def test_dashboard_lot_pl_includes_cosmetic_in_total():
    """dashboard.py total_cost must include cosmetic_cost."""
    from pathlib import Path
    _ROOT = Path(__file__).parent.parent
    src = (_ROOT / "routers" / "dashboard.py").read_text(encoding="utf-8")
    assert "total_cost = buying + parts_cost + labour_cost + cosmetic_cost" in src, \
        "dashboard.py total_cost formula must include cosmetic_cost"


def test_lot_detail_computes_profit():
    """routers/stock.py lot_detail must pass lot_profit to template context."""
    from pathlib import Path
    _ROOT = Path(__file__).parent.parent
    src = (_ROOT / "routers" / "stock.py").read_text(encoding="utf-8")
    assert "lot_profit" in src, "stock.py lot_detail missing lot_profit in context"
    assert "cosmetic_cost" in src, "stock.py lot_detail missing cosmetic_cost"


def test_lot_detail_template_shows_profit():
    """templates/lots/detail.html must display lot_profit."""
    from pathlib import Path
    _ROOT = Path(__file__).parent.parent
    src = (_ROOT / "templates" / "lots" / "detail.html").read_text(encoding="utf-8")
    assert "lot_profit" in src, "lots/detail.html missing lot_profit display"


def test_backup_script_exists():
    """scripts/backup_db.py must exist."""
    from pathlib import Path
    _ROOT = Path(__file__).parent.parent
    assert (_ROOT / "scripts" / "backup_db.py").exists(), "scripts/backup_db.py not found"


def test_backup_script_parses_db_url():
    """backup_db.py must strip +asyncpg from DATABASE_URL for pg_dump."""
    from pathlib import Path
    _ROOT = Path(__file__).parent.parent
    src = (_ROOT / "scripts" / "backup_db.py").read_text(encoding="utf-8")
    assert "+asyncpg" in src or "replace" in src, \
        "backup_db.py must strip +asyncpg from DATABASE_URL for pg_dump"


def test_backup_script_has_retention():
    """backup_db.py must delete backups older than 30 days."""
    from pathlib import Path
    _ROOT = Path(__file__).parent.parent
    src = (_ROOT / "scripts" / "backup_db.py").read_text(encoding="utf-8")
    assert "30" in src, "backup_db.py missing 30-day retention logic"
    assert "unlink" in src or "remove" in src, "backup_db.py missing file deletion"


def test_backup_filename_format():
    """backup_db.py must generate oxypc_*.sql.gz filenames."""
    from pathlib import Path
    _ROOT = Path(__file__).parent.parent
    src = (_ROOT / "scripts" / "backup_db.py").read_text(encoding="utf-8")
    assert "oxypc_" in src, "backup_db.py must use 'oxypc_' filename prefix"
    assert ".sql.gz" in src, "backup_db.py must produce .sql.gz files"


def test_backup_task_bat_exists():
    """scripts/setup_backup_task.bat must exist and reference schtasks at 02:00."""
    from pathlib import Path
    _ROOT = Path(__file__).parent.parent
    bat = _ROOT / "scripts" / "setup_backup_task.bat"
    assert bat.exists(), "scripts/setup_backup_task.bat not found"
    src = bat.read_text(encoding="utf-8")
    assert "schtasks" in src.lower(), "bat file must use schtasks"
    assert "02:00" in src, "bat file must schedule at 02:00"
    assert "backup_db.py" in src, "bat file must call backup_db.py"


def test_admin_has_backup_routes():
    """routers/admin.py must have /backup-status and /backup-now routes."""
    import importlib
    mod = importlib.import_module("routers.admin")
    router = mod.router
    paths = [r.path for r in router.routes]
    assert any("backup-status" in p for p in paths), \
        f"No backup-status route. Routes: {paths}"
    assert any("backup-now" in p for p in paths), \
        f"No backup-now route. Routes: {paths}"


def test_admin_users_template_has_backup_card():
    """templates/admin/users.html must contain backup status UI."""
    from pathlib import Path
    _ROOT = Path(__file__).parent.parent
    src = (_ROOT / "templates" / "admin" / "users.html").read_text(encoding="utf-8")
    assert "backup" in src.lower(), "users.html missing backup card"
    assert "backup-now" in src, "users.html missing Run Backup Now button"
