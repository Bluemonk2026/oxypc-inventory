"""2026-09-22: the single "trade_partner" Module Permission matrix key was
split into 8 page-specific keys (trade_partner_partners, _listings,
_bookings, _my_desk, _floors, _settings, _manage_lots, _bids) so each Trade
Partner admin page can be enabled per role independently, all defaulting to
disabled for every role (see migrate_seed_trade_partner_split_perms.py).

Kept in its own file/process, same reason as
test_cosmetic_split_permission_isolated.py: it seeds a RoleModulePermission
row and only THEN constructs its own TestClient so app startup loads the
fresh permission cache -- mixing that with the shared app_client fixture in
the same pytest process causes an asyncpg cross-event-loop RuntimeError.
"""
import pathlib
import subprocess
import sys
import uuid

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def _cleanup_role(role_name):
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


def test_split_permission_blocks_only_its_own_page(make_user):  # noqa: F811
    """Denying trade_partner_partners must block /trade-partner/partners but
    NOT /trade-partner/listings -- proving the two pages are now gated by
    independent module keys instead of one shared 'trade_partner' switch."""
    suffix = uuid.uuid4().hex[:6]
    role_name = f"itest_tp_role_{suffix}"

    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from database import AsyncSessionLocal
from models.role_permissions import RoleModulePermission

async def main():
    async with AsyncSessionLocal() as db:
        db.add(RoleModulePermission(role_name="{role_name}", module="trade_partner_partners",
                                    can_enable=False))
        await db.commit()

asyncio.run(main())
""")

    username, password = make_user(role_name)
    try:
        from fastapi.testclient import TestClient
        import main as main_module
        # Entered as a context manager on purpose -- a bare TestClient(app)
        # skips startup, so the seeded row above never loads into the
        # in-memory permission cache and this test would pass for the wrong
        # reason.
        with TestClient(main_module.app) as client:
            _login(client, username, password)

            r_partners = client.get("/trade-partner/partners", follow_redirects=False)
            assert r_partners.status_code == 403, r_partners.text[:300]

            # No row seeded for trade_partner_listings -> permissive default
            # (has_perm(): no matrix row for the module -> allow).
            r_listings = client.get("/trade-partner/listings", follow_redirects=False)
            assert r_listings.status_code == 200, r_listings.text[:300]
    finally:
        _cleanup_role(role_name)


def test_perm_modules_has_all_8_split_keys_and_no_bare_trade_partner():
    src = (pathlib.Path(ROOT) / "routers" / "master.py").read_text(encoding="utf-8")
    for key in ["trade_partner_partners", "trade_partner_listings", "trade_partner_bookings",
                "trade_partner_my_desk", "trade_partner_floors", "trade_partner_settings",
                "trade_partner_manage_lots", "trade_partner_bids"]:
        assert f'("{key}"' in src, f"PERM_MODULES missing {key}"
    assert '("trade_partner",' not in src


def test_migration_seed_script_module_list_matches_perm_modules():
    """Guards against the seed script's NEW_MODULES silently drifting from
    the actual PERM_MODULES trade_partner_* keys if either list is edited
    later without touching the other."""
    seed_src = (pathlib.Path(ROOT) / "migrate_seed_trade_partner_split_perms.py").read_text(encoding="utf-8")
    master_src = (pathlib.Path(ROOT) / "routers" / "master.py").read_text(encoding="utf-8")
    expected = ["trade_partner_partners", "trade_partner_listings", "trade_partner_bookings",
                "trade_partner_my_desk", "trade_partner_floors", "trade_partner_settings",
                "trade_partner_manage_lots", "trade_partner_bids"]
    for key in expected:
        assert f'"{key}"' in seed_src, f"migrate_seed_trade_partner_split_perms.py missing {key}"
        assert f'("{key}"' in master_src, f"PERM_MODULES missing {key}"


def test_all_partner_admin_routes_use_a_split_key_not_the_old_shared_one():
    src = (pathlib.Path(ROOT) / "routers" / "partner_admin.py").read_text(encoding="utf-8")
    assert 'require_module_perm("trade_partner")' not in src
    assert 'require_module_perm("trade_partner",' not in src
