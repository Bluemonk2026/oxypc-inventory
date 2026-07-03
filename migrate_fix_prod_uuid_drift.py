"""
OxyPC Inventory — Production schema-drift fix (part 2)
Same root cause as migrate_fix_prod_location_id_type.py: these UUID FK
columns were created as TEXT in the production (Supabase) DB instead of
UUID, unlike the ORM models and local dev's schema. This breaks any query
that JOINs/filters them against a real UUID column or list of UUID
objects — e.g. /api/buckets, /api/buckets/device-map, and the
telecalling/sales pages that read stock_transfers.

Verified before writing this: all non-null values in every column below
are valid UUID-shaped strings, so the ALTER is a safe in-place cast.

Usage: python migrate_fix_prod_uuid_drift.py
Backup taken first: backups/pre_prod_sync_<timestamp>.dump
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE buckets ALTER COLUMN location_id TYPE uuid USING location_id::uuid",
    "ALTER TABLE devices ALTER COLUMN bucket_id TYPE uuid USING bucket_id::uuid",
    "ALTER TABLE stock_transfers ALTER COLUMN bucket_id TYPE uuid USING bucket_id::uuid",
    "ALTER TABLE stock_transfers ALTER COLUMN lot_id TYPE uuid USING lot_id::uuid",
    "ALTER TABLE stock_transfers ALTER COLUMN to_location_id TYPE uuid USING to_location_id::uuid",
]


async def main():
    for stmt in STATEMENTS:
        print(f"Running: {stmt}")
        async with engine.begin() as conn:
            await conn.execute(text(stmt))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
