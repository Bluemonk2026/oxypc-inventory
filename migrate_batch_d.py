"""
Batch D migration — Stock Inward / TRC Production cost-parts tables,
bucket location + movement tracking.

Run: python migrate_batch_d.py
Backup already taken: backups/pre_batchD_20260703_113711.dump
"""
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from config import DATABASE_URL


STATEMENTS = [
    # devices.location_id — FK to storage_locations, used by Add-to-Bucket rework
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS location_id UUID REFERENCES storage_locations(id)",
    "CREATE INDEX IF NOT EXISTS ix_devices_location_id ON devices(location_id)",

    # buckets — location FK + production assignment tracking
    "ALTER TABLE buckets ADD COLUMN IF NOT EXISTS location_id UUID REFERENCES storage_locations(id)",
    "ALTER TABLE buckets ADD COLUMN IF NOT EXISTS assigned_to_production BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE buckets ADD COLUMN IF NOT EXISTS assigned_to_production_by VARCHAR(50)",
    "ALTER TABLE buckets ADD COLUMN IF NOT EXISTS assigned_to_production_at TIMESTAMP",
]


async def main():
    engine = create_async_engine(DATABASE_URL, echo=True)
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            await conn.execute(text(stmt))
    await engine.dispose()
    print("Batch D migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
