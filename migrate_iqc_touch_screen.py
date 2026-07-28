"""One-shot migration: add touch_screen column to iqc_inspections
for the new Touch Screen option in the IQC form's Screen/Display card.

Run: python migrate_iqc_touch_screen.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE iqc_inspections ADD COLUMN IF NOT EXISTS touch_screen VARCHAR(15)",
]


async def main():
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt}")
            await conn.execute(text(stmt))
    print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(main())
