"""One-shot migration: add the Credit Note workflow fields to `returns`
(cn_stage, debit_note_number, debit_note_amount, payment_invoice) —
new dedicated Credit Note page (2026-09-22).

Run: python migrate_credit_note_workflow.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE returns ADD COLUMN IF NOT EXISTS cn_stage VARCHAR(30) NULL",
    "ALTER TABLE returns ADD COLUMN IF NOT EXISTS debit_note_number VARCHAR(50) NULL",
    "ALTER TABLE returns ADD COLUMN IF NOT EXISTS debit_note_amount NUMERIC(12,2) NULL",
    "ALTER TABLE returns ADD COLUMN IF NOT EXISTS payment_invoice VARCHAR(100) NULL",
]


async def main():
    for stmt in STATEMENTS:
        print(f"Running: {stmt}")
        async with engine.begin() as conn:
            await conn.execute(text(stmt))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
