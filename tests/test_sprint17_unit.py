# tests/test_sprint17_unit.py
import os


def test_gitignore_excludes_config_ini():
    """config.ini must be listed in .gitignore."""
    content = open(".gitignore", encoding="utf-8").read()
    assert "config.ini" in content, ".gitignore does not exclude config.ini"


def test_startup_banner_has_no_default_password():
    """main.py startup banner must not print the default admin password."""
    src = open("main.py", encoding="utf-8").read()
    assert "oxypc@admin123" not in src, \
        "main.py still prints the default admin password in startup banner"


def test_main_has_generic_exception_handler():
    """main.py must have a generic Exception handler."""
    src = open("main.py", encoding="utf-8").read()
    assert "@app.exception_handler(Exception)" in src, \
        "main.py missing generic Exception handler"


def test_requirements_are_pinned():
    """requirements.txt must use == for all runtime packages (pyinstaller exempt)."""
    lines = open("requirements.txt", encoding="utf-8").readlines()
    pkg_lines = [l.strip() for l in lines if l.strip() and not l.startswith("#")]
    unpinned = [l for l in pkg_lines if ">=" in l or ">" in l]
    unpinned = [l for l in unpinned if "pyinstaller" not in l.lower()]
    assert not unpinned, f"requirements.txt has unpinned packages: {unpinned}"


def test_auto_fix_respects_env_var():
    """main.py startup must check OXYPC_AUTO_FIX env var before running DDL fix."""
    src = open("main.py", encoding="utf-8").read()
    assert "OXYPC_AUTO_FIX" in src, \
        "main.py startup does not gate auto-fix on OXYPC_AUTO_FIX env var"


def test_limiter_supports_forwarded_for():
    """limiter.py must support X-Forwarded-For for reverse proxy deployments."""
    src = open("limiter.py", encoding="utf-8").read()
    assert "get_ipaddr" in src or "OXYPC_TRUSTED_PROXY" in src, \
        "limiter.py does not handle X-Forwarded-For"


def test_high_risk_routers_have_csrf():
    """High-risk mutation routers must import verify_csrf."""
    high_risk = [
        "routers/admin.py",
        "routers/sales.py",
        "routers/stock.py",
        "routers/repair.py",
        "routers/iqc.py",
        "routers/grn.py",
        "routers/transfers.py",
        "routers/spare_parts.py",
        "routers/qc.py",
        "routers/cosmetic.py",
    ]
    missing = []
    for path in high_risk:
        src = open(path, encoding="utf-8").read()
        if "verify_csrf" not in src:
            missing.append(path)
    assert not missing, f"These routers are missing verify_csrf: {missing}"


def test_crm_routers_have_csrf():
    """CRM mutation routers must import verify_csrf."""
    crm = [
        "routers/crm_contacts.py",
        "routers/crm_activities.py",
        "routers/crm_sourcing.py",
        "routers/crm_sales.py",
        "routers/crm_quotes.py",
        "routers/crm_purchase_orders.py",
    ]
    missing = []
    for path in crm:
        src = open(path, encoding="utf-8").read()
        if "verify_csrf" not in src:
            missing.append(path)
    assert not missing, f"CRM routers missing verify_csrf: {missing}"
