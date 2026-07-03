"""
OxyPC Inventory — Performance indexing cleanup
- Add missing index on device_location_logs.location_id (Storage Location
  Master's per-location device count query filters/groups by this column;
  without an index it does a sequential scan of the whole table).
- Drop the duplicate index on devices.location_id (idx_devices_location_id
  and ix_devices_location_id were both created, covering the exact same
  column — redundant index maintenance cost on every device write).

Usage: python migrate_perf_indexes.py
Backup taken first: backups/pre_perf_indexes_<timestamp>.dump
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS ix_device_location_logs_location_id ON device_location_logs (location_id)",
    "DROP INDEX IF EXISTS idx_devices_location_id",
]


async def main():
    for stmt in STATEMENTS:
        print(f"Running: {stmt}")
        async with engine.begin() as conn:
            await conn.execute(text(stmt))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
