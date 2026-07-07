"""One-shot migration: add soft-delete (is_trashed/trashed_at) columns to
parts_grn and spare_parts, matching the existing Device/Lot trash convention.

Run: python migrate_parts_grn_sparepart_trash.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE parts_grn ADD COLUMN IF NOT EXISTS is_trashed BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE parts_grn ADD COLUMN IF NOT EXISTS trashed_at TIMESTAMP NULL",
    "ALTER TABLE spare_parts ADD COLUMN IF NOT EXISTS is_trashed BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE spare_parts ADD COLUMN IF NOT EXISTS trashed_at TIMESTAMP NULL",
]

async def main():
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt}")
            await conn.execute(text(stmt))
    print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(main())
