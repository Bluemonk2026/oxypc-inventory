"""
OxyPC Inventory — Widen dealers.phone column
Run ONCE to widen dealers.phone from VARCHAR(20) to VARCHAR(100) so a single
cell can hold multiple comma/slash/semicolon/pipe-separated phone numbers
(bulk upload now accepts these instead of rejecting them).

Usage: python migrate_widen_dealer_phone.py
"""
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

from config import DATABASE_URL


async def run():
    print("=" * 55)
    print("  OxyPC — Widen dealers.phone Migration")
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
        print("[1/1] Widening dealers.phone to VARCHAR(100)...")
        await conn.execute(text(
            "ALTER TABLE dealers ALTER COLUMN phone TYPE VARCHAR(100)"
        ))
        print("    done")

    await engine.dispose()
    print("\nMigration complete.")


if __name__ == "__main__":
    asyncio.run(run())
