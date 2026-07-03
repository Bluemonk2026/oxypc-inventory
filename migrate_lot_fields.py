"""
OxyPC Inventory — Lot Condition + Selling Price Migration
Adds `condition` and `selling_price` to lots, needed for:
- IQC Line Item "Create/Add Lot" modal (Condition, Selling Price fields)
- Inventory Search Lot Based table

Usage: python migrate_lot_fields.py
Backup taken first: backups/pre_lot_fields_<timestamp>.dump
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE lots ADD COLUMN IF NOT EXISTS condition VARCHAR(30) NULL",
    "ALTER TABLE lots ADD COLUMN IF NOT EXISTS selling_price NUMERIC(12,2) NULL",
]


async def main():
    for stmt in STATEMENTS:
        print(f"Running: {stmt}")
        async with engine.begin() as conn:
            await conn.execute(text(stmt))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
