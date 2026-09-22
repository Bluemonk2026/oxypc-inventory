"""
OxyPC Inventory — seed the "External Partner Test" Entity master-data value
(2026-09-22, see routers/partner_admin.py manage_lots and
models/master.py EXTERNAL_PARTNER_TEST_ENTITY).

Kept active (not disabled) deliberately: utils/master_data.py's
entity_values() is the single source of truth for the Entity dropdown AND
for Bulk Upload IQC's entity validation — an inactive value would make Bulk
Upload reject it, breaking the test-data intake flow this entity exists for.
Records tagged with it are instead excluded from live dashboards/reports by
an explicit Device.entity != EXTERNAL_PARTNER_TEST_ENTITY default (see
routers/dashboard.py, devices.py, stock.py, entity_movement.py).

Idempotent — safe to run more than once.

Usage: python migrate_seed_external_partner_test_entity.py
"""
import asyncio
from sqlalchemy import select
from database import AsyncSessionLocal
from models.master import MasterData, EXTERNAL_PARTNER_TEST_ENTITY


async def main():
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(select(MasterData).where(
            MasterData.category == "entity",
            MasterData.value == EXTERNAL_PARTNER_TEST_ENTITY,
        ))).scalar_one_or_none()
        if existing:
            if not existing.is_active:
                existing.is_active = True
                await db.commit()
                print("re-activated existing row")
            else:
                print("already exists and active")
            return
        db.add(MasterData(
            category="entity", value=EXTERNAL_PARTNER_TEST_ENTITY,
            description=("Isolated test data for External Partner (Trade Partner) portal "
                         "testing -- excluded from live dashboards/reports by default."),
            display_order=999, is_active=True,
        ))
        await db.commit()
        print("created")


if __name__ == "__main__":
    asyncio.run(main())
