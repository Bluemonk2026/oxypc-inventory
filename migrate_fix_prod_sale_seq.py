"""
OxyPC Inventory — Production missing-sequence fix
The `sale_number_seq` Postgres sequence (used by _next_sale_number() in
routers/sales.py to generate "SALE-0001"-style numbers) exists on local dev
but was never created in production — it was set up manually via psql at
some point rather than through a tracked migration. Calling nextval() on a
sequence that doesn't exist throws immediately, so every /sales/new page
load (and thus the whole "record a sale" flow) 500s in production.

Verified before writing this: production's `sales` table has 0 rows, so
starting the sequence at 1 cannot collide with an existing sale number.

Usage: python migrate_fix_prod_sale_seq.py
Backup taken first: backups/pre_prod_sync_<timestamp>.dump
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "CREATE SEQUENCE IF NOT EXISTS sale_number_seq START WITH 1",
]


async def main():
    for stmt in STATEMENTS:
        print(f"Running: {stmt}")
        async with engine.begin() as conn:
            await conn.execute(text(stmt))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
