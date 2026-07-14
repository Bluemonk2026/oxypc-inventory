"""Smoke test — Stress Test page 'Fail' and 'Complete' assignment endpoints.

Follows the same throwaway-verification pattern used by verify_*.py scripts at
the repo root (AsyncClient + dependency_overrides on get_current_user/get_db),
but lives in tests/ as a pytest-discoverable async test (pytest.ini sets
asyncio_mode = auto, so plain `async def test_*` functions run without any
extra fixture).

Covers:
  POST /stress/{barcode}/fail              -> assigns device to an L1 engineer
  POST /stress/{barcode}/complete-to-paint  -> sends device to Cleaning, assigned
                                               to a Paint/Cleaning-pool engineer

Creates its own Lot/Device/User fixtures and cleans them up at the end so it
can run repeatedly against a real dev DB without leaving residue.
"""
import uuid

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from main import app
from database import get_db, AsyncSessionLocal
from auth.dependencies import get_current_user
from models.user import User, UserRole
from models.device import Device, DeviceStage, StageMovement
from models.lot import Lot
from models.work_order import WorkOrder


class FakeAdmin:
    id = None
    username = "verify_admin"
    role = UserRole.admin
    status = True
    full_name = "Verify Admin"


_CURRENT_USER = {"user": None}


async def _override_user():
    return _CURRENT_USER["user"]


async def _override_db():
    async with AsyncSessionLocal() as db:
        yield db


@pytest.mark.asyncio
async def test_stress_fail_and_complete_assign():
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db
    _CURRENT_USER["user"] = FakeAdmin()

    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        assert lot, "Need at least one Lot in the DB to attach a test device to"

        l1_engineer = (await db.execute(
            select(User).where(User.role == UserRole.l1_engineer, User.status == True)
        )).scalars().first()
        paint_engineer = (await db.execute(
            select(User).where(User.role.in_(
                [UserRole.qc_inspector, UserRole.inventory_manager, UserRole.sales_manager]
            ), User.status == True)
        )).scalars().first()

        device_fail = Device(
            barcode=f"VSF-{uuid.uuid4().hex[:8]}", lot_id=lot.id,
            brand="VerifyBrand", model="VerifyModel",
            current_stage=DeviceStage.qc_check,
        )
        device_complete = Device(
            barcode=f"VSC-{uuid.uuid4().hex[:8]}", lot_id=lot.id,
            brand="VerifyBrand", model="VerifyModel",
            current_stage=DeviceStage.qc_check,
        )
        db.add(device_fail)
        db.add(device_complete)
        await db.commit()
        fail_barcode = device_fail.barcode
        complete_barcode = device_complete.barcode
        fail_device_id = device_fail.id
        complete_device_id = device_complete.id

    transport = ASGITransport(app=app, raise_app_exceptions=True)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # verify_csrf requires the form's csrf_token to match the
            # csrf_token cookie (double-submit pattern) — set both to the
            # same dummy value so requests reach the real handler instead of
            # being redirected to /auth/login for a "missing cookie".
            c.cookies.set("csrf_token", "smoketest-csrf")
            # ── Fail: assign to L1/L2 engineer (or confirm expected 4xx if no
            # engineer is seeded — either way this proves no 500). ──────────
            if l1_engineer:
                r = await c.post(
                    f"/stress/{fail_barcode}/fail",
                    data={"engineer_user_id": str(l1_engineer.id), "notes": "smoke test",
                          "csrf_token": "smoketest-csrf"},
                    follow_redirects=False,
                )
                assert r.status_code in (302, 303, 307), f"/fail returned {r.status_code}: {r.text[:300]}"
            else:
                r = await c.post(
                    f"/stress/{fail_barcode}/fail",
                    data={"engineer_user_id": str(uuid.uuid4()), "notes": "smoke test",
                          "csrf_token": "smoketest-csrf"},
                    follow_redirects=False,
                )
                assert r.status_code in (400, 404), f"/fail returned {r.status_code}: {r.text[:300]}"

            # ── Complete: assign to Paint/Cleaning-pool engineer ─────────────
            if paint_engineer:
                r2 = await c.post(
                    f"/stress/{complete_barcode}/complete-to-paint",
                    data={"engineer_user_id": str(paint_engineer.id), "notes": "smoke test",
                          "csrf_token": "smoketest-csrf"},
                    follow_redirects=False,
                )
                assert r2.status_code in (302, 303, 307), (
                    f"/complete-to-paint returned {r2.status_code}: {r2.text[:300]}"
                )
            else:
                r2 = await c.post(
                    f"/stress/{complete_barcode}/complete-to-paint",
                    data={"engineer_user_id": str(uuid.uuid4()), "notes": "smoke test",
                          "csrf_token": "smoketest-csrf"},
                    follow_redirects=False,
                )
                assert r2.status_code in (400, 404), (
                    f"/complete-to-paint returned {r2.status_code}: {r2.text[:300]}"
                )

        # ── Assertions on DB side-effects when an engineer was available ────
        async with AsyncSessionLocal() as db:
            if l1_engineer:
                dev = (await db.execute(select(Device).where(Device.id == fail_device_id))).scalar_one()
                assert dev.current_stage in (DeviceStage.l1, DeviceStage.l2), (
                    f"Device not moved to L1/L2, still at {dev.current_stage}"
                )
                wo = (await db.execute(
                    select(WorkOrder).where(WorkOrder.device_id == fail_device_id)
                )).scalars().first()
                assert wo is not None, "No WorkOrder created for /fail assignment"
                assert wo.assigned_user_id == l1_engineer.id

            if paint_engineer:
                dev2 = (await db.execute(select(Device).where(Device.id == complete_device_id))).scalar_one()
                assert dev2.current_stage == DeviceStage.cleaning, (
                    f"Device not moved to Cleaning, still at {dev2.current_stage}"
                )
                wo2 = (await db.execute(
                    select(WorkOrder).where(WorkOrder.device_id == complete_device_id)
                )).scalars().first()
                assert wo2 is not None, "No WorkOrder created for /complete-to-paint assignment"
                assert wo2.assigned_user_id == paint_engineer.id

    finally:
        # ── Cleanup: remove everything this test created ────────────────────
        async with AsyncSessionLocal() as db:
            for did in (fail_device_id, complete_device_id):
                wos = (await db.execute(select(WorkOrder).where(WorkOrder.device_id == did))).scalars().all()
                for wo in wos:
                    await db.delete(wo)
                movements = (await db.execute(
                    select(StageMovement).where(StageMovement.device_id == did)
                )).scalars().all()
                for m in movements:
                    await db.delete(m)
                dev = (await db.execute(select(Device).where(Device.id == did))).scalar_one_or_none()
                if dev:
                    await db.delete(dev)
            await db.commit()
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)
