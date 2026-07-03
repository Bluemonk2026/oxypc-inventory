"""
OxyPC Inventory — Warranty + RMA Migration
Run ONCE to add warranty_type/warranty_expires_at to sales, and
return_type/serial_captured/warranty_status/complaint_text to returns.

Usage: python migrate_warranty_rma.py

Safety: this script does NOT run pg_dump itself (Windows environments
vary in pg_dump availability/PATH). Take a backup first, e.g.:
    pg_dump -Fc -h <host> -U <user> -d <dbname> -f backups/pre_warranty_rma_<date>.dump
Then run this script.
"""
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

from config import DATABASE_URL


async def run():
    print("=" * 55)
    print("  OxyPC — Warranty + RMA Migration")
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
        print("[1/2] Adding warranty columns to 'sales'...")
        await conn.execute(text(
            "ALTER TABLE sales ADD COLUMN IF NOT EXISTS warranty_type VARCHAR(20) DEFAULT 'none'"
        ))
        await conn.execute(text(
            "ALTER TABLE sales ADD COLUMN IF NOT EXISTS warranty_expires_at TIMESTAMP"
        ))
        print("    done")

        print("[2/2] Adding RMA columns to 'returns'...")
        await conn.execute(text(
            "ALTER TABLE returns ADD COLUMN IF NOT EXISTS return_type VARCHAR(20) DEFAULT 'customer'"
        ))
        await conn.execute(text(
            "ALTER TABLE returns ADD COLUMN IF NOT EXISTS serial_captured VARCHAR(100)"
        ))
        await conn.execute(text(
            "ALTER TABLE returns ADD COLUMN IF NOT EXISTS warranty_status VARCHAR(20)"
        ))
        await conn.execute(text(
            "ALTER TABLE returns ADD COLUMN IF NOT EXISTS complaint_text TEXT"
        ))
        print("    done")

    await engine.dispose()
    print("\nMigration complete.")


if __name__ == "__main__":
    asyncio.run(run())
