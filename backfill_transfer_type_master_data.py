"""One-off backfill: adds the "Ready for Sale" / "Scrap for Sale" Transfer
Type options to the admin-managed master_data table. /transfers' Transfer
Type dropdown reads from master_data (via utils.master_data.master_options),
not from models.master.MASTER_SEED directly — MASTER_SEED only seeds a brand
new database (see setup_db.py). Existing databases need existing categories
backfilled by hand. Idempotent — safe to run more than once.

Usage: python backfill_transfer_type_master_data.py
"""
import asyncio

from database import AsyncSessionLocal
from models.master import MasterData
import models.scrap_for_sale  # noqa: F401 — registers ScrapForSale before any mapper touches StockTransfer
from sqlalchemy import select


NEW_VALUES = ["ready_for_sale", "scrap_for_sale"]


async def main():
    async with AsyncSessionLocal() as db:
        existing = set((await db.execute(
            select(MasterData.value).where(MasterData.category == "transfer_type")
        )).scalars().all())
        added = []
        max_order = (await db.execute(
            select(MasterData.display_order).where(MasterData.category == "transfer_type")
            .order_by(MasterData.display_order.desc()).limit(1)
        )).scalar() or 0
        for i, value in enumerate(NEW_VALUES, start=1):
            if value in existing:
                continue
            db.add(MasterData(category="transfer_type", value=value, display_order=max_order + i))
            added.append(value)
        if added:
            await db.commit()
        print(f"Added: {added or '(none — already present)'}")


if __name__ == "__main__":
    asyncio.run(main())
