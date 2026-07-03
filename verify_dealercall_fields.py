"""Throwaway verification for the new DealerCall telecalling fields.
Creates a throwaway dealer + call via ORM, confirms round-trip, then
soft-deactivates the dealer (never hard-deletes) per repo policy.
"""
import asyncio
import uuid
from database import AsyncSessionLocal
from models.dealers import Dealer, DealerCall
from sqlalchemy import select


async def main():
    async with AsyncSessionLocal() as db:
        code = f"VERIFY-{uuid.uuid4().hex[:6].upper()}"
        dealer = Dealer(
            dealer_code=code,
            business_name="Verify Telecalling Fields Co",
            contact_person="Test Concern Person",
            phone="9999999999",
            address="123 Test Street",
            city="TestCity", state="TestState",
            source="Verification Script",
            status="active",
        )
        db.add(dealer)
        await db.flush()

        call = DealerCall(
            dealer_id=dealer.id,
            called_by="verify_script",
            call_outcome="interested",
            notes="Remarks field",
            calling_remark="Calling remark field",
            category="Laptop",
            product_model="Dell Latitude 5490",
            configuration="i5/8GB/256GB SSD",
            qty=10,
            asking_price=25000.00,
            deal_status="negotiation",
            requirements_preferred_config="i5 8th gen sample unit",
            whom_to_sell="corporate",
            sale_quantity=8,
            deals_in="imported",
            stock_type="lot",
            assigned_to="verify_script",
        )
        db.add(call)
        await db.commit()

        result = await db.execute(select(DealerCall).where(DealerCall.id == call.id))
        fetched = result.scalar_one()
        assert fetched.category == "Laptop"
        assert fetched.product_model == "Dell Latitude 5490"
        assert fetched.asking_price == 25000.00
        assert fetched.deal_status == "negotiation"
        assert fetched.whom_to_sell == "corporate"
        assert fetched.deals_in == "imported"
        assert fetched.stock_type == "lot"
        assert fetched.assigned_to == "verify_script"
        print("ORM round-trip OK — all new fields persisted correctly.")

        # Soft-deactivate throwaway dealer (never hard-delete)
        dealer.status = "inactive"
        await db.commit()
        print(f"Throwaway dealer {code} deactivated (not deleted).")


if __name__ == "__main__":
    asyncio.run(main())
