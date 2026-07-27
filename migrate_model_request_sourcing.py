"""One-shot migration: add procurement-close columns to model_requests for
the Procure Dashboard's "Device Sourcing" tab (Close Deal action, distinct
from TRC's stock-fulfillment "Update" action).

Run: python migrate_model_request_sourcing.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE model_requests ADD COLUMN IF NOT EXISTS source_deal_id VARCHAR(50)",
    "ALTER TABLE model_requests ADD COLUMN IF NOT EXISTS sourcing_notes TEXT",
    "ALTER TABLE model_requests ADD COLUMN IF NOT EXISTS closed_by VARCHAR(50)",
    "ALTER TABLE model_requests ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP",
]


async def main():
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt}")
            await conn.execute(text(stmt))
    print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(main())
