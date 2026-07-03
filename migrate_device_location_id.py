"""
OxyPC Inventory — devices.location_id migration
Adds a nullable FK column devices.location_id -> storage_locations(id)
so IQC Entry / Device Edit can attach a precise storage location via
the Floor/Zone -> Location ID cascade.

Run ONCE: python migrate_device_location_id.py
"""
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

from config import DATABASE_URL


async def run():
    print("=" * 55)
    print("  OxyPC — devices.location_id Migration")
    print("=" * 55)

    engine = create_async_engine(DATABASE_URL, echo=False)

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        print("  DB connection: OK\n")
    except Exception as e:
        print(f"\nERROR: Cannot connect to database.\n  {e}")
        sys.exit(1)

    async with engine.begin() as conn:
        print("[1/2] Adding column devices.location_id ...")
        await conn.execute(text("""
            ALTER TABLE devices
            ADD COLUMN IF NOT EXISTS location_id UUID NULL
            REFERENCES storage_locations(id)
        """))
        print("    column 'location_id' ready")

        print("[2/2] Creating index idx_devices_location_id ...")
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_devices_location_id "
            "ON devices(location_id)"
        ))
        print("    index ready")

    await engine.dispose()

    print("\n" + "=" * 55)
    print("  Migration complete: devices.location_id added.")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    asyncio.run(run())
