"""Throwaway verification for Assign Social Leads: new Status values,
master-data config, Status filter, and accordion pill counts."""
import asyncio
from httpx import AsyncClient, ASGITransport
from main import app
from database import get_db, AsyncSessionLocal
from auth.dependencies import get_current_user
from models.user import UserRole


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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.cookies.set("csrf_token", "verify-csrf-token")

        # Page load: new statuses in dropdown/filter, pills present
        r = await c.get("/crm/assign-leads")
        assert r.status_code == 200, r.status_code
        for label in ["Not In Stock", "High Price", "Invalid No"]:
            assert label in r.text, f"{label} missing from page"
        assert 'name="status"' in r.text, "Status filter dropdown missing"
        assert "grp-pills-" in r.text or "leadsAccordion" in r.text
        print("Page load OK — new statuses + filter present")

        # Master data admin page shows the new category
        r = await c.get("/admin/master?tab=sales")
        assert r.status_code == 200
        assert "Assign Leads: Status" in r.text
        print("Master data admin page OK")

        # Create group + lead, log calls with new statuses, verify pills + filter
        r = await c.post("/crm/assign-leads/group", data={"name": "ASL Verify Group", "csrf_token": "verify-csrf-token"})
        assert r.status_code == 200, r.text
        gid = r.json()["id"]

        r = await c.post("/crm/assign-leads/lead", data={
            "group_id": gid, "name": "Invalid Lead", "phone": "1234567890",
            "csrf_token": "verify-csrf-token",
        })
        assert r.status_code == 200, r.text
        lead_id = r.json()["lead"]["id"]

        r = await c.post(f"/crm/assign-leads/lead/{lead_id}/call", data={
            "calling_date": "2026-07-03", "outcome": "invalid_no",
            "csrf_token": "verify-csrf-token",
        })
        assert r.status_code == 200, r.text

        r = await c.get(f"/crm/assign-leads/group/{gid}/leads")
        data = r.json()
        assert data["pills"]["invalid_no"] == 1, data["pills"]
        print("Pill count via refresh endpoint OK:", data["pills"])

        # Status filter narrows the accordion table
        r = await c.get("/crm/assign-leads", params={"status": "invalid_no"})
        assert "Invalid Lead" in r.text
        r2 = await c.get("/crm/assign-leads", params={"status": "interested"})
        assert "Invalid Lead" not in r2.text
        print("Status filter narrows accordion tables OK")

    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
