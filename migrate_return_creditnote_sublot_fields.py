"""One-shot migration: add Tag Return Status / Sub-Lot Number tracking
(devices), Credit Note capture fields (returns), and the "As-Is Lot"
Transfer Type master-data value used by the Return / Change Floor / GRN
Post-IQC / Inventory Manager / Production Manager batch (2026-09-22).

Run: python migrate_return_creditnote_sublot_fields.py
"""
import asyncio
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession
from database import engine
from models.master import MasterData

STATEMENTS = [
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS tag_return_status VARCHAR(120) NULL",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS sub_lot_number VARCHAR(50) NULL",
    "ALTER TABLE returns ADD COLUMN IF NOT EXISTS cn_number VARCHAR(50) NULL",
    "ALTER TABLE returns ADD COLUMN IF NOT EXISTS customer_name VARCHAR(100) NULL",
    "ALTER TABLE returns ADD COLUMN IF NOT EXISTS customer_phone VARCHAR(20) NULL",
    "ALTER TABLE returns ADD COLUMN IF NOT EXISTS customer_state VARCHAR(100) NULL",
    "ALTER TABLE returns ADD COLUMN IF NOT EXISTS customer_address TEXT NULL",
]


async def seed_as_is_lot_transfer_type():
    async with AsyncSession(engine) as session:
        existing = (await session.execute(
            select(MasterData).where(MasterData.category == "transfer_type", MasterData.value == "as_is_lot")
        )).scalar_one_or_none()
        if existing:
            print("  'as_is_lot' transfer_type already seeded. Skipping.")
            return
        max_order = (await session.execute(
            select(MasterData.display_order).where(MasterData.category == "transfer_type")
            .order_by(MasterData.display_order.desc()).limit(1)
        )).scalar()
        session.add(MasterData(category="transfer_type", value="as_is_lot",
                                display_order=(max_order or 0) + 1, is_active=True))
        await session.commit()
        print("  Seeded 'as_is_lot' transfer_type master-data value.")


async def main():
    for stmt in STATEMENTS:
        print(f"Running: {stmt}")
        async with engine.begin() as conn:
            await conn.execute(text(stmt))
    await seed_as_is_lot_transfer_type()
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
