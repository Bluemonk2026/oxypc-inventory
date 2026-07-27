"""One-shot migration: add KYC document columns to crm_contacts and a
person_role column to crm_contact_numbers, for the restructured Add Account
page (Company Details / KYC Documents / Contact Numbers sections).

Run: python migrate_account_kyc.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE crm_contacts ADD COLUMN IF NOT EXISTS gstin_doc_path VARCHAR(255)",
    "ALTER TABLE crm_contacts ADD COLUMN IF NOT EXISTS pan_doc_path VARCHAR(255)",
    "ALTER TABLE crm_contacts ADD COLUMN IF NOT EXISTS bank_cheque_number VARCHAR(50)",
    "ALTER TABLE crm_contacts ADD COLUMN IF NOT EXISTS bank_cheque_doc_path VARCHAR(255)",
    "ALTER TABLE crm_contacts ADD COLUMN IF NOT EXISTS msme_number VARCHAR(50)",
    "ALTER TABLE crm_contacts ADD COLUMN IF NOT EXISTS msme_doc_path VARCHAR(255)",
    "ALTER TABLE crm_contacts ADD COLUMN IF NOT EXISTS director1_id_number VARCHAR(50)",
    "ALTER TABLE crm_contacts ADD COLUMN IF NOT EXISTS director1_doc_path VARCHAR(255)",
    "ALTER TABLE crm_contacts ADD COLUMN IF NOT EXISTS director2_id_number VARCHAR(50)",
    "ALTER TABLE crm_contacts ADD COLUMN IF NOT EXISTS director2_doc_path VARCHAR(255)",
    "ALTER TABLE crm_contact_numbers ADD COLUMN IF NOT EXISTS person_role VARCHAR(30)",
]


async def main():
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt}")
            await conn.execute(text(stmt))
    print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(main())
