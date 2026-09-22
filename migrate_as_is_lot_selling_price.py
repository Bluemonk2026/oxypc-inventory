"""One-shot migration: add Device.min_selling_price / max_selling_price —
Ready to Sale page's new "As-Is Lot" table Edit modal (2026-09-22).

Run: python migrate_as_is_lot_selling_price.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS min_selling_price NUMERIC(12,2) NULL",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS max_selling_price NUMERIC(12,2) NULL",
]


async def main():
    for stmt in STATEMENTS:
        print(f"Running: {stmt}")
        async with engine.begin() as conn:
            await conn.execute(text(stmt))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
