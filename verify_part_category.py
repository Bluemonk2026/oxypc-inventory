"""Throwaway verification for the Part Category rename + New Request/Replace
modal + Part Category column changes."""
import asyncio
from httpx import AsyncClient, ASGITransport
from main import app
from database import get_db, AsyncSessionLocal
from auth.dependencies import get_current_user
from models.user import UserRole
from models.spare_parts import IQC_PART_CATEGORIES


class FakeAdmin:
    id = None  # audit_logs.user_id is nullable — avoids an FK violation on a fake user
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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.cookies.set("csrf_token", "verify-csrf-token")

        # Spare Parts page: labels + new Part Category column
        r = await c.get("/spare-parts")
        assert r.status_code == 200, r.status_code
        assert "Part Category" in r.text, "Part Category label missing from spare-parts page"
        assert r.text.count("Part Category") >= 2, "expected Part Category on both Add New Part + Harvest modal + table header"
        print("Spare Parts page OK — Part Category present")

        # Add New Part page
        r = await c.get("/spare-parts/new")
        assert r.status_code == 200
        assert "Part Category" in r.text
        print("Add New Part page OK")

        # Parts GRN new page — Add Line Item modal
        r = await c.get("/parts-grn/new")
        assert r.status_code == 200
        assert "Part Category" in r.text
        for cat in IQC_PART_CATEGORIES:
            assert cat in r.text, f"IQC category {cat} missing from Add Line Item dropdown"
        print("Parts GRN new page OK — IQC-derived categories present:", IQC_PART_CATEGORIES)

        # Find any existing device to test the Parts Consumption modal on
        from sqlalchemy import select
        from models.device import Device
        async with AsyncSessionLocal() as db:
            device = (await db.execute(select(Device).limit(1))).scalars().first()
        assert device, "no device found in DB to test device detail page"
        barcode = device.barcode

        r = await c.get(f"/devices/{barcode}")
        assert r.status_code == 200, r.status_code
        assert "openPartRequestModal" in r.text
        assert "ALL_SPARE_PARTS" in r.text
        assert "pr_category" in r.text and "pr_part_name" in r.text
        print("Device detail page OK — New Request/Replace modal present")

        # Submit a part request via the new create endpoint with part_category
        r = await c.post("/part-requests/create", data={
            "barcode": barcode, "part_name": "Test Part XYZ",
            "part_category": "RAM", "request_type": "new", "qty": "2",
            "csrf_token": "verify-csrf-token",
        })
        assert r.status_code in (302, 307), r.status_code
        print("Part request created OK")

        # Confirm it shows up with Part Category on the Part Requests tab
        r = await c.get("/spare-parts")
        assert "Test Part XYZ" in r.text
        assert ">RAM<" in r.text or "RAM</td>" in r.text
        print("Part Requests tab shows Part Category OK")

    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
