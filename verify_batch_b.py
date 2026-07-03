"""
Throwaway verification script for Batch B (IQC Floor/Zone -> Location ID cascade).
Run: python verify_batch_b.py
Not part of the app; safe to leave uncommitted / delete later.
"""
import asyncio
import uuid
from sqlalchemy import select, text
from database import engine, AsyncSessionLocal
from models.location import StorageLocation, ZoneType, UnitType


async def run():
    async with AsyncSessionLocal() as db:
        # 1. Confirm devices.location_id column + FK exist
        async with engine.connect() as conn:
            r = await conn.execute(text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name='devices' AND column_name='location_id'"
            ))
            print("devices.location_id column:", r.fetchall())

            r2 = await conn.execute(text(
                "SELECT conname FROM pg_constraint WHERE conrelid = 'devices'::regclass "
                "AND confrelid = 'storage_locations'::regclass"
            ))
            print("FK constraints devices -> storage_locations:", r2.fetchall())

        # 2. Ensure at least one active StorageLocation per test zone (showroom, workshop)
        test_zones = [ZoneType.showroom, ZoneType.workshop]
        created = []
        for z in test_zones:
            existing = (await db.execute(
                select(StorageLocation).where(StorageLocation.zone == z, StorageLocation.is_active == True)
            )).scalars().first()
            if not existing:
                loc = StorageLocation(
                    id=uuid.uuid4(), zone=z, unit_type=UnitType.rack,
                    unit_id=f"TEST-{z.value.upper()}-1", slot=None,
                    description="verify_batch_b throwaway row", is_active=True,
                )
                db.add(loc)
                created.append(loc)
        if created:
            await db.commit()
            print(f"Created {len(created)} throwaway StorageLocation rows for testing: "
                  f"{[c.unit_id for c in created]}")
        else:
            print("Existing active StorageLocation rows found for test zones — reused them.")

    print("\nNow hit the endpoint manually (server must be running):")
    print("  GET /locations/api/by-zone?zone=showroom")
    print("  GET /locations/api/by-zone?zone=workshop")
    print("Expected: JSON list of {id, unit_id, display_name}")


if __name__ == "__main__":
    asyncio.run(run())
