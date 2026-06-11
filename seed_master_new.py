"""Seed new master data categories that were added in the expansion."""
import asyncio
from database import AsyncSessionLocal
from models.master import MasterData, MASTER_SEED
from sqlalchemy import select


async def seed():
    async with AsyncSessionLocal() as db:
        inserted = 0
        for category, values in MASTER_SEED.items():
            for value in values:
                existing = await db.execute(
                    select(MasterData).where(
                        MasterData.category == category,
                        MasterData.value == value
                    )
                )
                if not existing.scalar_one_or_none():
                    db.add(MasterData(category=category, value=value))
                    inserted += 1
        await db.commit()
        print(f"Seeded {inserted} new master data values.")


if __name__ == "__main__":
    asyncio.run(seed())
