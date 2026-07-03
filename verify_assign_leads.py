"""Throwaway HTTP-level verification for the Assign Social Leads expansion."""
import asyncio
from httpx import AsyncClient, ASGITransport
from main import app
from database import get_db, AsyncSessionLocal
from auth.dependencies import get_current_user
from models.user import UserRole


class FakeAdmin:
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

        r = await c.get("/crm/assign-leads")
        assert r.status_code == 200, r.status_code
        assert "summaryCardsRow1" in r.text
        assert "Purchase Quantity" in r.text
        assert "Whom to Sale" in r.text
        assert "Full Remark" not in r.text or "id=\"editRemark\"" not in r.text
        print("Page load OK")

        r = await c.post("/crm/assign-leads/group", data={"name": "Verify Group", "csrf_token": "verify-csrf-token"})
        assert r.status_code == 200, r.text
        group = r.json()
        gid = group["id"]
        print("Group created:", gid)

        r = await c.post("/crm/assign-leads/lead", data={
            "group_id": gid, "name": "Test Lead", "phone": "9999999999",
            "address": "123 Test St", "device_categories": '["Laptop"]',
            "purchase_quantity": "10", "selling_quantity": "8",
            "whom_to_sell": "Corporate", "deals_in": "Indian",
            "dealing_grades": '["Grade A","Lot"]', "platform": "Facebook",
            "csrf_token": "verify-csrf-token",
        })
        assert r.status_code == 200, r.text
        lead = r.json()["lead"]
        lead_id = lead["id"]
        assert lead["purchase_quantity"] == "10"
        assert lead["dealing_grades"] == ["Grade A", "Lot"]
        print("Lead created:", lead_id)

        r = await c.post(f"/crm/assign-leads/lead/{lead_id}/call", data={
            "calling_date": "2026-07-03", "outcome": "interested",
            "device_categories": '["Desktop"]', "quantity": "5 units approx",
            "purchase_quantity": "12", "selling_quantity": "9",
            "whom_to_sell": "Retail", "deals_in": "Imported",
            "full_remarks": "Called and discussed pricing", "csrf_token": "verify-csrf-token",
        })
        assert r.status_code == 200, r.text
        print("Call logged")

        r = await c.get(f"/crm/assign-leads/group/{gid}/leads")
        assert r.status_code == 200
        leads = r.json()["leads"]
        assert len(leads) == 1
        ld = leads[0]
        assert ld["call_status"] == "interested"
        assert ld["latest_quantity"] == "5 units approx"
        assert ld["latest_device_categories"] == "Desktop"
        assert ld["latest_full_remarks"] == "Called and discussed pricing"
        assert ld["latest_deals_in"] == "Imported"
        print("Group-leads refresh endpoint OK — latest call data merged correctly")

        r = await c.get("/crm/assign-leads/summary")
        assert r.status_code == 200
        s = r.json()
        assert s["platform"]["Facebook"] == 1
        assert s["connection"]["interested"] == 1
        assert s["grades"]["Grade A"] == 1
        assert s["grades"]["Lot"] == 1
        assert s["categories"]["Laptop"] == 1
        print("Summary endpoint OK:", s)

        # cleanup: soft-remove is not modeled for leads/groups here, but this is
        # throwaway verification data in a dev DB — leave it for manual inspection
        # or delete via the UI. Not deleting via direct SQL per no-delete policy.

    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
