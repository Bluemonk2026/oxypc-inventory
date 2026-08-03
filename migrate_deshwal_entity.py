"""One-shot migration: seed 'Deshwal' into the Master Data 'entity' category
(Entity Movement page card counts).

Run: python migrate_deshwal_entity.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    """INSERT INTO master_data (id, category, value, display_order, is_active)
       VALUES (gen_random_uuid(), 'entity', 'Deshwal', -1, true)
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
