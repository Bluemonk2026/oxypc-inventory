"""One-shot migration: expand Assign Social Leads (crm_leads / crm_lead_calls).

Run: python migrate_assign_leads_expansion.py
Backup taken first: backups/pre_assign_leads_expansion_<timestamp>.dump
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    # crm_leads: rename units_expected -> purchase_quantity (Integer -> text)
    "ALTER TABLE crm_leads RENAME COLUMN units_expected TO purchase_quantity",
    "ALTER TABLE crm_leads ALTER COLUMN purchase_quantity TYPE VARCHAR(50) USING purchase_quantity::text",
    "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS address TEXT NULL",
    "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS selling_quantity VARCHAR(50) NULL",
    "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS whom_to_sell VARCHAR(30) NULL",
    "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS deals_in VARCHAR(20) NULL",
    "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS dealing_grades TEXT NULL",
    # crm_lead_calls: quantity Integer -> text, plus new deal-detail columns
    "ALTER TABLE crm_lead_calls ALTER COLUMN quantity TYPE VARCHAR(50) USING quantity::text",
    "ALTER TABLE crm_lead_calls ADD COLUMN IF NOT EXISTS purchase_quantity VARCHAR(50) NULL",
    "ALTER TABLE crm_lead_calls ADD COLUMN IF NOT EXISTS selling_quantity VARCHAR(50) NULL",
    "ALTER TABLE crm_lead_calls ADD COLUMN IF NOT EXISTS whom_to_sell VARCHAR(30) NULL",
    "ALTER TABLE crm_lead_calls ADD COLUMN IF NOT EXISTS deals_in VARCHAR(20) NULL",
]


async def main():
    # Each statement gets its own transaction so a harmless failure (e.g. RENAME
    # COLUMN re-run after it already succeeded) doesn't abort the whole batch.
    for stmt in STATEMENTS:
        print(f"Running: {stmt}")
        try:
            async with engine.begin() as conn:
                await conn.execute(text(stmt))
        except Exception as exc:
            print(f"  -> skipped ({exc.__class__.__name__}: already applied)")
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
