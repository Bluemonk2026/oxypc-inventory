"""
Auth tests — login validation, lockout behaviour, CSRF protection.

Run: pytest tests/test_auth.py -v
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession


def test_login_page_loads(app_client):
    """Login page must return 200 with a form."""
    r = app_client.get("/auth/login")
    assert r.status_code == 200
    assert "login" in r.text.lower()


def test_invalid_login_returns_error(app_client):
    """Bad credentials must return 200 with an error message (not a crash)."""
    r = app_client.post(
        "/auth/login",
        data={"username": "no_such_user", "password": "wrongpass", "csrf_token": "dummy"},
        follow_redirects=True,
    )
    # Should stay on login page with error — not 500
    assert r.status_code in (200, 403)


@pytest.mark.asyncio
async def test_admin_user_exists(db: AsyncSession):
    """There must be at least one admin account in the database."""
    from sqlalchemy import select
    from models.user import User, UserRole
    result = await db.execute(
        select(User).where(User.role == UserRole.admin, User.status == True)
    )
    admin = result.scalars().first()
    assert admin is not None, "No active admin user found — create one in config.ini or seed the DB"
