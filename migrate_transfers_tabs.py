"""
Batch C migration (throwaway runner, uncommitted).
Adds nullable columns to stock_transfers to support Bucket-move and Lot-move
tabs on the Assign Stock page, alongside the existing single-device move path.

Run: python migrate_transfers_tabs.py
Backup taken first via pg_dump (see backups/pre_transfers_tabs_*.dump).
"""
import asyncio
import asyncpg
from config import DATABASE_URL

# asyncpg needs the plain postgresql:// URL, not the +asyncpg SQLAlchemy variant
RAW_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

STATEMENTS = [
    # Which kind of move this transfer row represents: device | bucket | lot
    "ALTER TABLE stock_transfers ADD COLUMN IF NOT EXISTS move_kind VARCHAR(20) NOT NULL DEFAULT 'device'",
    # Bucket move support — device_id stays NOT NULL for legacy single-device rows,
    # but a bucket-move creates one stock_transfers row per member device, so we
    # still populate device_id per-row AND tag the originating bucket here for traceability.
    "ALTER TABLE stock_transfers ADD COLUMN IF NOT EXISTS bucket_id UUID NULL REFERENCES buckets(id)",
    # Lot move support — same pattern: one row per member device, tagged with lot_id.
    "ALTER TABLE stock_transfers ADD COLUMN IF NOT EXISTS lot_id UUID NULL REFERENCES lots(id)",
    # Destination StorageLocation for this transfer (Task 4 Floor/Zone + Location ID cascade)
    "ALTER TABLE stock_transfers ADD COLUMN IF NOT EXISTS to_location_id UUID NULL REFERENCES storage_locations(id)",
    "CREATE INDEX IF NOT EXISTS ix_stock_transfers_bucket_id ON stock_transfers(bucket_id)",
    "CREATE INDEX IF NOT EXISTS ix_stock_transfers_lot_id ON stock_transfers(lot_id)",
    "CREATE INDEX IF NOT EXISTS ix_stock_transfers_to_location_id ON stock_transfers(to_location_id)",
]


async def main():
    conn = await asyncpg.connect(RAW_URL)
    try:
        for stmt in STATEMENTS:
            print(f"Running: {stmt}")
            await conn.execute(stmt)
        print("Migration complete.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
