"""Split Permission Matrix modules (routers/cosmetic.py PERM_MODULE_BY_STAGE)
block only their own stage's Move action.

Kept in its own file/process: it seeds a RoleModulePermission row and only
THEN constructs its own TestClient (so app startup loads the fresh cache) —
mixing that with the shared app_client fixture in the same pytest process
causes an asyncpg cross-event-loop RuntimeError (see
test_role_additional_permissions_enforcement.py for the same pattern).
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


def _seed_device_at(stage, barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.lot import Lot
from models.device import Device, DeviceStage

async def main():
    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        db.add(Device(barcode="{barcode}", lot_id=lot.id, brand="ITestBrand", model="ITestModel",
                     current_stage=DeviceStage.{stage}))
        await db.commit()

asyncio.run(main())
""")


def _cleanup_device(barcode):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.device import Device, StageMovement
from models.work_order import WorkOrder

async def main():
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(select(Device).where(Device.barcode == "{barcode}"))).scalar_one_or_none()
        if dev:
            for wo in (await db.execute(select(WorkOrder).where(WorkOrder.device_id == dev.id))).scalars().all():
                await db.delete(wo)
            for m in (await db.execute(select(StageMovement).where(
                    StageMovement.device_id == dev.id))).scalars().all():
                await db.delete(m)
            await db.delete(dev)
        await db.commit()

asyncio.run(main())
""")


def test_split_permission_blocks_only_the_specific_stage(make_user):  # noqa: F811
    """Denying cosmetic_cleaning's edit bit blocks moving off Cleaning but
    must not block moving off Putty (a different, still-permissive module)."""
    suffix = uuid.uuid4().hex[:6]
    role_name = f"itest_cosm_role_{suffix}"
    barcode_clean = f"ITPERMCLEAN{suffix}"
    barcode_putty = f"ITPERMPUTTY{suffix}"
    _seed_device_at("cleaning", barcode_clean)
    _seed_device_at("putty", barcode_putty)

    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from database import AsyncSessionLocal
from models.role_permissions import RoleModulePermission

async def main():
    async with AsyncSessionLocal() as db:
        db.add(RoleModulePermission(role_name="{role_name}", module="cosmetic_cleaning",
                                    can_enable=False, can_edit=False))
        await db.commit()

asyncio.run(main())
""")

    username, password = make_user(role_name)
    eng_username, _ = make_user("cosmetic_manager")
    eng_id = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == "{eng_username}"))).scalar_one()
        print(u.id)

asyncio.run(main())
""")
    try:
        from fastapi.testclient import TestClient
        import main as main_module
        # Entered as a context manager on purpose — a bare TestClient(app)
        # skips startup/shutdown, so main.py's permission cache (which the
        # RoleModulePermission row seeded above must be loaded into) stays
        # empty and this test would pass for the wrong reason. Same pattern
        # as the app_client fixture (tests/conftest.py), constructed fresh
        # here instead so it loads AFTER the seed above.
        with TestClient(main_module.app) as client:
            _login(client, username, password)
            csrf = client.cookies.get("csrf_token") or "dummy"

            r_clean = client.post("/cosmetic/advance", data={
                "csrf_token": csrf, "barcode": barcode_clean, "engineer_user_id": eng_id,
            })
            assert r_clean.status_code == 403, r_clean.text[:300]

            r_putty = client.post("/cosmetic/advance", data={
                "csrf_token": csrf, "barcode": barcode_putty, "engineer_user_id": eng_id,
            })
            assert r_putty.status_code == 200, r_putty.text[:300]
    finally:
        _cleanup_device(barcode_clean)
        _cleanup_device(barcode_putty)
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


def test_completed_move_to_final_qc_has_no_assignee_but_still_checks_permission(make_user):  # noqa: F811
    """Cosmetic Completed's "Move to Final QC" doesn't require an assignee
    (see routers/cosmetic.py ASSIGN_ON_MOVE_STAGES), but the cosmetic_completed
    'edit' permission bit must still gate it — a role denied that bit can't
    bypass the check just because there's no modal/engineer_user_id anymore."""
    suffix = uuid.uuid4().hex[:6]
    role_name = f"itest_cosm_role2_{suffix}"
    barcode = f"ITPERMCOMP{suffix}"
    _seed_device_at("cosmetic_completed", barcode)

    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from database import AsyncSessionLocal
from models.role_permissions import RoleModulePermission

async def main():
    async with AsyncSessionLocal() as db:
        db.add(RoleModulePermission(role_name="{role_name}", module="cosmetic_completed",
                                    can_enable=False, can_edit=False))
        await db.commit()

asyncio.run(main())
""")

    username, password = make_user(role_name)
    try:
        from fastapi.testclient import TestClient
        import main as main_module
        with TestClient(main_module.app) as client:
            _login(client, username, password)
            csrf = client.cookies.get("csrf_token") or "dummy"
            r = client.post("/cosmetic/advance", data={"csrf_token": csrf, "barcode": barcode})
            assert r.status_code == 403, r.text[:300]
    finally:
        _cleanup_device(barcode)
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
