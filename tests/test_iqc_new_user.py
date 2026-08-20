"""New IQC entry must work for a freshly created user.

Reported from production: newly added users get a 500 when submitting the
New IQC form. IQC entry is deliberately open to every signed-in user
(routers/iqc.py, comment above `current_user`), so a brand-new account with a
non-privileged role must be able to register a tag.

The test drives the real HTTP path — login, CSRF, form POST — because the bug
is in request handling, not in a helper that a unit test would reach.
"""
import uuid

import pytest
from sqlalchemy import select


def _login(client, username, password):
    """Log in through the real form so the auth + CSRF cookies get set."""
    client.get("/auth/login")
    csrf = client.cookies.get("csrf_token") or "dummy"
    return client.post(
        "/auth/login",
        data={"username": username, "password": password, "csrf_token": csrf},
        follow_redirects=False,
    )


# Run user setup/teardown in a separate process. The app's async engine is a
# module-level singleton whose asyncpg connections bind to the loop that opened
# them; TestClient runs its own loop, so touching that engine from the test
# process either raises "attached to a different loop" or deadlocks on dispose.
# A subprocess sidesteps the shared engine entirely.
_SETUP_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from auth.dependencies import hash_password
from database import AsyncSessionLocal
from models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        u = User(username="{username}", password_hash=hash_password("{password}"),
                 full_name="IQC Test User", role="{role}", status=True)
        db.add(u)
        await db.commit()
        print(u.id)

asyncio.run(main())
"""

_TEARDOWN_SRC = """
import asyncio, sys
sys.path.insert(0, r"{root}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.user import User
from models.device import Device

async def main():
    async with AsyncSessionLocal() as db:
        u = (await db.execute(
            select(User).where(User.username == "{username}"))).scalar_one_or_none()
        if u:
            u.status = False          # soft-delete; this project never drops rows
        # Retire any tag this test registered, so a run against production data
        # leaves no live device behind.
        devs = (await db.execute(
            select(Device).where(Device.barcode.like("ITEST%")))).scalars().all()
        for d in devs:
            d.is_active = False
        await db.commit()

asyncio.run(main())
"""


# Roles a newly added user realistically lands on. `role` is free text
# (RoleType in models/user.py) precisely so custom roles are allowed, so a new
# account may carry a role name no built-in allow-list or label map knows about.
NEW_USER_ROLES = ["iqc_inspector", "sub_admin", "custom_floor_role", ""]


@pytest.fixture()
def make_user():
    """Factory: create a brand-new user with a given role, clean up after."""
    import pathlib
    import subprocess
    import sys

    root = str(pathlib.Path(__file__).resolve().parent.parent)
    created = []

    def _run(src, username, role):
        r = subprocess.run(
            [sys.executable, "-c", src.format(root=root, username=username,
                                              password="TestPass1234", role=role)],
            capture_output=True, text=True, cwd=root, timeout=120,
        )
        if r.returncode != 0:
            raise RuntimeError(f"user setup failed:\n{r.stdout}\n{r.stderr}")
        return r.stdout.strip()

    def _make(role):
        username = f"itest_new_{uuid.uuid4().hex[:8]}"
        _run(_SETUP_SRC, username, role)
        created.append(username)
        return username, "TestPass1234"

    yield _make

    for username in created:
        _run(_TEARDOWN_SRC, username, "")


@pytest.mark.parametrize("role", NEW_USER_ROLES)
def test_new_user_can_open_iqc_form(app_client, make_user, role):
    username, password = make_user(role)
    _login(app_client, username, password)

    r = app_client.get("/iqc/new", follow_redirects=False)
    assert r.status_code != 500, (
        f"GET /iqc/new returned 500 for a new user with role {role!r}:\n{r.text[:2000]}"
    )
    assert r.status_code == 200, f"expected the form, got {r.status_code}"


@pytest.mark.parametrize("role", NEW_USER_ROLES)
def test_new_user_can_submit_iqc_entry(app_client, make_user, role):
    """The reported failure: submitting the form 500s for a new user.

    Posts only the fields a technician actually fills for a quick entry, which
    is also the shape most likely to expose missing-default handling.
    """
    username, password = make_user(role)
    _login(app_client, username, password)

    app_client.get("/iqc/new")
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    barcode = f"ITEST{uuid.uuid4().hex[:10].upper()}"

    r = app_client.post(
        "/iqc/new",
        data={
            "csrf_token": csrf,
            "barcode": barcode,
            # lot_id deliberately blank — the handler is supposed to fall back
            # to the "Unassigned" lot rather than fail.
            "lot_id": "",
            "power_on": "Yes",
            "status": "Power On",
        },
        follow_redirects=False,
    )

    assert r.status_code != 500, (
        f"POST /iqc/new returned 500 for a new user with role {role!r}:\n{r.text[:3000]}"
    )
    # 302 = saved and redirected; 200 = re-rendered form with a field error.
    # Either is acceptable behaviour, a 500 is not.
    assert r.status_code in (200, 302), f"unexpected status {r.status_code}"

    # A save redirects to /iqc. If that page 500s the technician sees a 500 on
    # submit even though the device was written — indistinguishable from a
    # failed save, so follow the redirect rather than stopping at the 302.
    if r.status_code == 302:
        landing = app_client.get(r.headers["location"], follow_redirects=True)
        assert landing.status_code != 500, (
            f"redirect target after saving 500s for role {role!r}:\n{landing.text[:3000]}"
        )


@pytest.mark.parametrize("role", NEW_USER_ROLES)
def test_new_user_can_open_iqc_list(app_client, make_user, role):
    """The IQC list is where a save lands — it must not 500 for a new user."""
    username, password = make_user(role)
    _login(app_client, username, password)

    r = app_client.get("/iqc", follow_redirects=True)
    assert r.status_code != 500, (
        f"GET /iqc returned 500 for a new user with role {role!r}:\n{r.text[:3000]}"
    )
