"""One-shot migration: Device.l34_activity column + seed Master Data
'l34_activity' category (L3/L4 Mark Complete Activities dropdown).

Run: python migrate_l34_activity.py
"""
import asyncio
from sqlalchemy import text
from database import engine

ACTIVITIES = [
    "Motherboard Repair", "Chip Level Repair", "Component Replacement",
    "Reballing", "Cleaning & Reflow", "Data Recovery", "Other",
]

STATEMENTS = [
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS l34_activity VARCHAR(100) NULL",
] + [
    f"""INSERT INTO master_data (id, category, value, display_order, is_active)
       VALUES (gen_random_uuid(), 'l34_activity', '{v}', {i}, true)
       ON CONFLICT (category, value) DO NOTHING"""
    for i, v in enumerate(ACTIVITIES)
]

async def main():
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt}")
            await conn.execute(text(stmt))
    print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(main())
