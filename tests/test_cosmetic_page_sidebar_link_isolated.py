"""Dynamic "Cosmetic Page" sidebar link — cases that seed a RoleModulePermission
row (see test_cosmetic_page_sidebar_link.py for the default-permission cases).

Kept in its own file/process: it seeds the row and only THEN constructs its
own TestClient (so app startup loads the fresh permission cache) — mixing
that with the shared app_client fixture in the same pytest process causes an
asyncpg cross-event-loop RuntimeError (see
test_cosmetic_split_permission_isolated.py for the same pattern).
"""
import pathlib
import subprocess
import sys

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def _seed_perm(role_name, module, can_enable):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.role_permissions import RoleModulePermission

async def main():
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(RoleModulePermission).where(
            RoleModulePermission.role_name == "{role_name}",
            RoleModulePermission.module == "{module}"))).scalar_one_or_none()
        if row:
            row.can_enable = {can_enable}
        else:
            db.add(RoleModulePermission(role_name="{role_name}", module="{module}",
                                        can_enable={can_enable}, can_edit=True))
        await db.commit()

asyncio.run(main())
""")


def _clear_perms(role_name):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.role_permissions import RoleModulePermission

async def main():
    async with AsyncSessionLocal() as db:
        for row in (await db.execute(select(RoleModulePermission).where(
                RoleModulePermission.role_name == "{role_name}"))).scalars().all():
            await db.delete(row)
        await db.commit()

asyncio.run(main())
""")


def test_dynamic_link_skips_disabled_stages_in_pipeline_order(make_user):  # noqa: F811
    role_name = "inventory_manager"
    try:
        # has_perm defaults enable=True when no row exists, so every stage
        # ahead of Masking in pipeline order must be explicitly disabled —
        # not just Cleaning/Putty — or the unseeded default lets Dry Sanding
        # win instead.
        _seed_perm(role_name, "cosmetic_cleaning", False)
        _seed_perm(role_name, "cosmetic_putty", False)
        _seed_perm(role_name, "cosmetic_dry_sanding", False)
        _seed_perm(role_name, "cosmetic_masking", True)
        username, password = make_user(role_name)

        from fastapi.testclient import TestClient
        import main as main_module
        with TestClient(main_module.app) as client:
            _login(client, username, password)
            html = client.get("/cosmetic/masking", follow_redirects=True).text
            assert "Cosmetic Page" in html
            assert 'href="/cosmetic/masking"' in html
            assert 'href="/cosmetic/cleaning"' not in html
            assert 'href="/cosmetic/putty"' not in html
    finally:
        _clear_perms(role_name)


def test_custom_role_scoped_to_a_single_late_stage(make_user):  # noqa: F811
    """A completely custom role name (not qc_inspector/inventory_manager/
    sales_manager, not any built-in role) scoped to Water Sanding — the last
    of the 6 mid-pipeline stages — proves the fix generalizes to ANY cosmetic
    role for ANY stage, not just the "Cosmetic Cleaning" case reported."""
    role_name = "cosmetic_water_sanding_specialist"
    try:
        for module in ("cosmetic_cleaning", "cosmetic_putty", "cosmetic_dry_sanding",
                        "cosmetic_masking", "cosmetic_painting"):
            _seed_perm(role_name, module, False)
        _seed_perm(role_name, "cosmetic_water_sanding", True)
        username, password = make_user(role_name)

        from fastapi.testclient import TestClient
        import main as main_module
        with TestClient(main_module.app) as client:
            _login(client, username, password)
            html = client.get("/cosmetic/water_sanding", follow_redirects=True).text
            assert "Cosmetic Page" in html
            assert 'href="/cosmetic/water_sanding"' in html
    finally:
        _clear_perms(role_name)


def test_dynamic_link_hidden_when_all_six_stages_disabled(make_user):  # noqa: F811
    role_name = "sales_manager"
    try:
        for module in ("cosmetic_cleaning", "cosmetic_putty", "cosmetic_dry_sanding",
                        "cosmetic_masking", "cosmetic_painting", "cosmetic_water_sanding"):
            _seed_perm(role_name, module, False)
        username, password = make_user(role_name)

        from fastapi.testclient import TestClient
        import main as main_module
        with TestClient(main_module.app) as client:
            _login(client, username, password)
            html = client.get("/cosmetic/cosmetic_received", follow_redirects=True).text
            assert "Cosmetic Page" not in html
    finally:
        _clear_perms(role_name)
