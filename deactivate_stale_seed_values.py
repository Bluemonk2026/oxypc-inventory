"""Deactivate (never delete) MasterData rows seeded with wrong values in an
earlier pass of this session, now superseded by corrected values that match
the actual option values used in each template."""
import asyncio
from sqlalchemy import select, and_
from database import AsyncSessionLocal
from models.master import MasterData

STALE = {
    "dealer_credit_reason": [
        "Goods Returned", "Damaged Goods", "Wrong Item Delivered",
        "Short Delivery", "Price Adjustment", "Other",
    ],
    "transfer_type": ["TRC to Showroom", "Showroom to TRC", "Showroom Lot"],
    "customer_state": ["Delhi", "Other State (IGST)"],
    "sale_warranty_type": ["No Warranty", "30 Days", "6 Months", "1 Year"],
    "return_type": ["Customer Return", "Dealer Return"],
    "market_trade_type": ["Selling (I have)", "Buying (I need)"],
    "market_item_category": ["Monitor", "TFT"],
    "market_condition": ["Refurbished", "New", "Used", "As-Is"],
}


async def main():
    async with AsyncSessionLocal() as db:
        deactivated = 0
        for category, values in STALE.items():
            result = await db.execute(
                select(MasterData).where(
                    MasterData.category == category, MasterData.value.in_(values)
                )
            )
            for row in result.scalars().all():
                row.is_active = False
                deactivated += 1
        await db.commit()
        print(f"Deactivated {deactivated} stale rows (soft, reversible via /admin/master).")


if __name__ == "__main__":
    asyncio.run(main())
