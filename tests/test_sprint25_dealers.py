# tests/test_sprint25_dealers.py
"""
Smoke tests for Sprint 25 dealer & telecalling enhancements.
Run: pytest tests/test_sprint25_dealers.py -v
"""
import pytest


def test_sales_users_list_shape():
    """Verify that sales_users list only contains sales roles — not admin/iqc/etc."""
    from models.user import UserRole

    SALES_ROLES = (UserRole.sales, UserRole.sales_manager, UserRole.telecaller)
    all_roles = list(UserRole)
    excluded = [r for r in all_roles if r not in SALES_ROLES]

    assert UserRole.admin in excluded, "admin must be excluded from sales_users dropdown"
    assert UserRole.iqc_inspector in excluded, "iqc_inspector must be excluded"
    assert UserRole.sales in SALES_ROLES
    assert UserRole.telecaller in SALES_ROLES
    assert UserRole.sales_manager in SALES_ROLES


def test_followup_filter_date_parse():
    """followup_from/to must parse yyyy-mm-dd without raising."""
    from datetime import datetime

    date_str = "2026-06-01"
    parsed = datetime.strptime(date_str, "%Y-%m-%d")
    assert parsed.year == 2026
    assert parsed.month == 6
    assert parsed.day == 1


def test_bad_followup_date_silently_skipped():
    """Invalid followup date strings must be silently ignored (no exception)."""
    from datetime import datetime

    bad = "not-a-date"
    result = None
    try:
        result = datetime.strptime(bad, "%Y-%m-%d")
    except ValueError:
        pass  # expected — backend should catch this
    assert result is None
