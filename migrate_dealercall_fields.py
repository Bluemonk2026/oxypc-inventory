"""One-shot migration: add telecalling deal-detail columns to dealer_calls.

Run: python migrate_dealercall_fields.py
Backup taken first: backups/pre_dealercall_fields_<timestamp>.dump
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE dealer_calls ADD COLUMN IF NOT EXISTS calling_remark TEXT NULL",
    "ALTER TABLE dealer_calls ADD COLUMN IF NOT EXISTS category VARCHAR(50) NULL",
    "ALTER TABLE dealer_calls ADD COLUMN IF NOT EXISTS product_model VARCHAR(200) NULL",
    "ALTER TABLE dealer_calls ADD COLUMN IF NOT EXISTS configuration VARCHAR(200) NULL",
    "ALTER TABLE dealer_calls ADD COLUMN IF NOT EXISTS qty INTEGER NULL",
    "ALTER TABLE dealer_calls ADD COLUMN IF NOT EXISTS asking_price NUMERIC(12,2) NULL",
    "ALTER TABLE dealer_calls ADD COLUMN IF NOT EXISTS deal_status VARCHAR(30) NULL",
    "ALTER TABLE dealer_calls ADD COLUMN IF NOT EXISTS requirements_preferred_config TEXT NULL",
    "ALTER TABLE dealer_calls ADD COLUMN IF NOT EXISTS whom_to_sell VARCHAR(30) NULL",
    "ALTER TABLE dealer_calls ADD COLUMN IF NOT EXISTS sale_quantity INTEGER NULL",
    "ALTER TABLE dealer_calls ADD COLUMN IF NOT EXISTS deals_in VARCHAR(20) NULL",
    "ALTER TABLE dealer_calls ADD COLUMN IF NOT EXISTS stock_type VARCHAR(20) NULL",
    "ALTER TABLE dealer_calls ADD COLUMN IF NOT EXISTS assigned_to VARCHAR(50) NULL",
    "CREATE INDEX IF NOT EXISTS idx_dealer_calls_assigned_to ON dealer_calls(assigned_to)",
]


async def main():
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt}")
            await conn.execute(text(stmt))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
