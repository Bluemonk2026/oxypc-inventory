"""Smoke test: L1/L2 <-> L3/L4 status-driven repair hand-off flow.

Single event loop (httpx ASGITransport) to avoid asyncpg loop-binding issues.
Impersonates roles via app.dependency_overrides[get_current_user] with
pre-fetched (detached) User objects. Creates throwaway devices on an existing
lot; soft-deactivates them at the end (no hard deletes, per project policy).
"""
import asyncio
import uuid
import httpx

from main import app
from database import AsyncSessionLocal
from auth.dependencies import get_current_user
from models.user import User
from models.lot import Lot
from models.device import Device, DeviceStage
from models.work_order import WorkOrder
from sqlalchemy import select
from db_validator import validate_and_fix
from database import engine

CSRF = "smoketoken"
results = []


def check(label, cond):
    results.append((label, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")


async def get_device(did):
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(Device).where(Device.id == did))).scalar_one()


async def main():
    # Ensure new columns are provisioned (startup path)
    await validate_and_fix(engine)

    async with AsyncSessionLocal() as db:
        lot = (await db.execute(select(Lot).limit(1))).scalars().first()
        dev = Device(barcode=f"SMK{uuid.uuid4().hex[:8].upper()}", lot_id=lot.id,
                     brand="TestBrand", model="TestModel",
                     current_stage=DeviceStage.l1, l1l2_status="New")
        dev2 = Device(barcode=f"SMK{uuid.uuid4().hex[:8].upper()}", lot_id=lot.id,
                      brand="TestBrand", model="TestModel2",
                      current_stage=DeviceStage.l1, l1l2_status="New")
        db.add(dev); db.add(dev2)
        l3u = (await db.execute(select(User).where(User.role == "l3_engineer", User.status == True))).scalars().first()
        if not l3u:
            l3u = User(username=f"smoke_l3_{uuid.uuid4().hex[:4]}", full_name="Smoke L3 Eng",
                       password_hash="x", role="l3_engineer", status=True)
            db.add(l3u)
        qcu = (await db.execute(select(User).where(User.role == "qc_inspector", User.status == True))).scalars().first()
        if not qcu:
            qcu = User(username=f"smoke_qc_{uuid.uuid4().hex[:4]}", full_name="Smoke QC Eng",
                       password_hash="x", role="qc_inspector", status=True)
            db.add(qcu)
        admin = (await db.execute(select(User).where(User.role == "admin", User.status == True))).scalars().first()
        await db.commit()
        # eager-load attributes we will use, then detach
        for u in (l3u, qcu, admin):
            _ = (u.id, u.username, u.full_name, u.role, u.status)
        did, bc = str(dev.id), dev.barcode
        did2, bc2 = str(dev2.id), dev2.barcode
        l3user, qcuser = l3u.username, qcu.username
        admin_obj, l3_obj, qc_obj = admin, l3u, qcu

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                 cookies={"csrf_token": CSRF}) as client:

        def act_as(u):
            app.dependency_overrides[get_current_user] = lambda: u

        print("\nStep 1: GET /repair/l1")
        act_as(admin_obj)
        r = await client.get("/repair/l1")
        check("GET /repair/l1 -> 200", r.status_code == 200)

        print("\nStep 2: POST /repair/request-l3l4")
        r = await client.post("/repair/request-l3l4",
                              data={"csrf_token": CSRF, "device_id": did, "assigned_l3l4_username": l3user})
        check("request-l3l4 -> 302", r.status_code == 302)
        dev = await get_device(did)
        check("device.l1l2_status == 'Requested to L3/L4'", dev.l1l2_status == "Requested to L3/L4")
        async with AsyncSessionLocal() as db:
            wos = (await db.execute(select(WorkOrder).where(
                WorkOrder.device_id == did, WorkOrder.work_id.like("L3L4-%")))).scalars().all()
        check("one L3L4- WorkOrder created", len(wos) == 1 and wos[0].work_id.startswith("L3L4-"))
        check("WorkOrder assigned to l3 engineer", wos[0].assigned_username == l3user)
        check("WorkOrder.work_id fits VARCHAR(12)", len(wos[0].work_id) <= 12)

        print("\nStep 3: GET /repair/l3l4 as L3 engineer (device visible)")
        act_as(l3_obj)
        r = await client.get("/repair/l3l4")
        check("GET /repair/l3l4 -> 200", r.status_code == 200)
        check("device barcode present on L3/L4 page", bc in r.text)

        print("\nStep 4: POST /repair/l3l4-start")
        r = await client.post("/repair/l3l4-start", data={"csrf_token": CSRF, "device_id": did})
        check("l3l4-start -> 302", r.status_code == 302)
        dev = await get_device(did)
        check("device.l34_status == 'Repair Started'", dev.l34_status == "Repair Started")

        print("\nStep 5: POST /repair/l3l4-complete")
        r = await client.post("/repair/l3l4-complete", data={"csrf_token": CSRF, "device_id": did})
        check("l3l4-complete -> 302", r.status_code == 302)
        dev = await get_device(did)
        check("device.l34_status == 'Completed'", dev.l34_status == "Completed")

        print("\nStep 6: L1/L2 page reflects L3/L4 Status = Completed")
        act_as(admin_obj)
        r = await client.get("/repair/l1")
        check("L1/L2 page shows 'Completed' + barcode", "Completed" in r.text and bc in r.text)

        print("\nStep 7: Scrap path -> new request, start, scrap Normal")
        await client.post("/repair/request-l3l4",
                          data={"csrf_token": CSRF, "device_id": did, "assigned_l3l4_username": l3user})
        act_as(l3_obj)
        await client.post("/repair/l3l4-start", data={"csrf_token": CSRF, "device_id": did})
        r = await client.post("/repair/l3l4-scrap",
                              data={"csrf_token": CSRF, "device_id": did, "scrap_type": "Normal Scrap"})
        check("l3l4-scrap -> 302", r.status_code == 302)
        dev = await get_device(did)
        check("device.l34_status == 'Normal Scrap'", dev.l34_status == "Normal Scrap")

        print("\nStep 8: L1/L2 shows only Back to Production; POST back-to-production")
        act_as(admin_obj)
        r = await client.get("/repair/l1")
        check("Back to Production button present", "Back to Production" in r.text)
        r = await client.post("/repair/back-to-production", data={"csrf_token": CSRF, "device_id": did})
        check("back-to-production -> 302", r.status_code == 302)
        dev = await get_device(did)
        check("device.current_stage == scrapped", dev.current_stage == DeviceStage.scrapped)

        print("\nStep 9: L1/L2 complete-to-stress on device 2")
        r = await client.post("/repair/l1l2-start", data={"csrf_token": CSRF, "device_id": did2})
        check("l1l2-start -> 302", r.status_code == 302)
        r = await client.post("/repair/l1l2-complete-to-stress",
                              data={"csrf_token": CSRF, "device_id": did2, "stress_engineer_username": qcuser})
        check("l1l2-complete-to-stress -> 302", r.status_code == 302)
        dev2 = await get_device(did2)
        check("device2.current_stage == qc_check (Stress Test)", dev2.current_stage == DeviceStage.qc_check)

    # cleanup: soft-deactivate throwaway devices
    async with AsyncSessionLocal() as db:
        for x in (did, did2):
            d = (await db.execute(select(Device).where(Device.id == x))).scalar_one()
            d.is_active = False
        await db.commit()

    app.dependency_overrides.clear()
    passed = sum(1 for _, ok in results if ok)
    print(f"\n==== RESULT: {passed}/{len(results)} checks passed ====")
    print("OVERALL:", "PASS" if passed == len(results) else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())
