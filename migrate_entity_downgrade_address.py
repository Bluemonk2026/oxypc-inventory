"""One-shot migration: Device entity, SparePart part_type, PartRequest
downgrade support, and Sale/PartSale customer address.

Run: python migrate_entity_downgrade_address.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS entity VARCHAR(30) NULL",
    "ALTER TABLE spare_parts ADD COLUMN IF NOT EXISTS part_type VARCHAR(20) NULL",
    "ALTER TABLE part_requests ALTER COLUMN request_type TYPE VARCHAR(20)",
    "ALTER TABLE part_requests ADD COLUMN IF NOT EXISTS downgrade_type VARCHAR(20) NULL",
    "ALTER TABLE part_requests ADD COLUMN IF NOT EXISTS part_make VARCHAR(100) NULL",
    "ALTER TABLE part_requests ADD COLUMN IF NOT EXISTS part_model VARCHAR(100) NULL",
    "ALTER TABLE sales ADD COLUMN IF NOT EXISTS customer_address TEXT NULL",
    "ALTER TABLE part_sales ADD COLUMN IF NOT EXISTS customer_address TEXT NULL",
    """INSERT INTO master_data (id, category, value, display_order, is_active)
       VALUES (gen_random_uuid(), 'entity', 'OxyPC Computers', 0, true)
       ON CONFLICT (category, value) DO NOTHING""",
    """INSERT INTO master_data (id, category, value, display_order, is_active)
       VALUES (gen_random_uuid(), 'entity', 'Renew Circuits', 1, true)
       ON CONFLICT (category, value) DO NOTHING""",
]

async def main():
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt}")
            await conn.execute(text(stmt))
    print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(main())
