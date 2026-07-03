"""Throwaway verification: Part Category unification across Add New Part /
Add Line Item / Add Harvest Part / Device Detail modal, and CRM detail-page
activity_type/outcome wiring."""
import asyncio
from httpx import AsyncClient, ASGITransport
from main import app
from database import get_db, AsyncSessionLocal
from auth.dependencies import get_current_user
from models.user import UserRole
from utils.master_data import refresh_master_cache, master_options
from sqlalchemy import select
from models.device import Device
from models.crm import CRMSourcingDeal


class FakeAdmin:
    id = None
    username = "verify_admin"
    role = UserRole.admin
    status = True
    full_name = "Verify Admin"


async def override_user():
    return FakeAdmin()


async def override_db():
    async with AsyncSessionLocal() as db:
        yield db


app.dependency_overrides[get_current_user] = override_user
app.dependency_overrides[get_db] = override_db


async def main():
    async with AsyncSessionLocal() as db:
        await refresh_master_cache(db)
        device = (await db.execute(select(Device).limit(1))).scalars().first()
        deal = (await db.execute(select(CRMSourcingDeal).limit(1))).scalars().first()

    part_cats = master_options("iqc_part_category")
    assert "RAM" in part_cats and "Charging Port" in part_cats
    print("iqc_part_category:", part_cats)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.cookies.set("csrf_token", "verify-csrf-token")

        r = await c.get("/spare-parts/new")
        assert r.status_code == 200 and "Charging Port" in r.text
        print("Add New Part page: uses unified Part Category list OK")

        r = await c.get("/parts-grn/new")
        assert r.status_code == 200 and "Charging Port" in r.text
        print("Add Line Item modal: uses unified Part Category list OK")

        r = await c.get("/spare-parts")
        assert r.status_code == 200 and "Charging Port" in r.text
        print("Add Harvest Part modal: uses unified Part Category list OK")

        if device:
            r = await c.get(f"/devices/{device.barcode}")
            assert r.status_code == 200
            assert "PART_CATEGORY_OPTIONS" in r.text
            assert "Charging Port" in r.text
            print("Device Detail New Request/Replace modal: uses unified Part Category list OK")

        if deal:
            r = await c.get(f"/crm/sourcing/{deal.id}")
            assert r.status_code == 200
            assert 'name="activity_type"' in r.text
            assert 'name="outcome"' in r.text
            print("CRM sourcing detail page: activity_type/outcome present OK")

    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
