"""
OxyPC Inventory — Production schema-drift fix
devices.location_id was created as TEXT in the production (Supabase) DB
instead of UUID, unlike local dev's schema and the ORM model
(models/device.py: Column(UUID(as_uuid=True), ForeignKey("storage_locations.id"))).
This breaks any query that JOINs Device.location_id to StorageLocation.id
(Postgres has no "text = uuid" operator) — e.g. Inventory Search's Model
Based table, which is why /devices 500s in production.

Verified before writing this: 0 devices currently have a non-null
location_id in production, so this ALTER is a no-op for existing data.

Usage: python migrate_fix_prod_location_id_type.py
Backup taken first: backups/pre_prod_sync_<timestamp>.dump
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE devices ALTER COLUMN location_id TYPE uuid USING location_id::uuid",
]


async def main():
    for stmt in STATEMENTS:
        print(f"Running: {stmt}")
        async with engine.begin() as conn:
            await conn.execute(text(stmt))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
