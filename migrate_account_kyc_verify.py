"""One-shot migration: add KYC verification columns to crm_contacts for the
Account Detail page's "Verify KYC" action.

Run: python migrate_account_kyc_verify.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE crm_contacts ADD COLUMN IF NOT EXISTS kyc_verified BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE crm_contacts ADD COLUMN IF NOT EXISTS kyc_verified_by VARCHAR(50)",
    "ALTER TABLE crm_contacts ADD COLUMN IF NOT EXISTS kyc_verified_at TIMESTAMP",
]


async def main():
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt}")
            await conn.execute(text(stmt))
    print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(main())
