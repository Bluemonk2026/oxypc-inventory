"""One-shot migration: create the companies table for the multi-company
Company Setting page, and seed it with the single company profile that
previously lived in app_settings (company_name/address/gstin/state/
state_code/phone/email) so no existing data is lost.

Run: python migrate_companies.py
"""
import asyncio
import uuid
from sqlalchemy import text
from database import engine

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS companies (
        id UUID PRIMARY KEY,
        company_name VARCHAR(200) NOT NULL,
        company_address VARCHAR(500) NULL,
        company_gstin VARCHAR(20) NULL,
        company_state VARCHAR(100) NULL,
        company_state_code VARCHAR(5) NULL,
        company_phone VARCHAR(50) NULL,
        company_email VARCHAR(100) NULL,
        is_active BOOLEAN NOT NULL DEFAULT true,
        created_by VARCHAR(50) NULL,
        created_at TIMESTAMP NULL,
        updated_at TIMESTAMP NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_companies_is_active ON companies (is_active)",
]


async def main():
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt.strip()[:80]}...")
            await conn.execute(text(stmt))

        existing = (await conn.execute(text("SELECT COUNT(*) FROM companies"))).scalar()
        if existing:
            print(f"companies already has {existing} row(s) — skipping seed.")
        else:
            row = (await conn.execute(text(
                "SELECT key, value FROM app_settings WHERE key IN "
                "('company_name','company_address','company_gstin','company_state',"
                "'company_state_code','company_phone','company_email')"
            ))).fetchall()
            vals = {k: v for k, v in row}
            if vals.get("company_name"):
                await conn.execute(text("""
                    INSERT INTO companies (id, company_name, company_address, company_gstin,
                        company_state, company_state_code, company_phone, company_email,
                        is_active, created_by, created_at, updated_at)
                    VALUES (:id, :name, :address, :gstin, :state, :state_code, :phone, :email,
                        true, 'migration', now(), now())
                """), {
                    "id": str(uuid.uuid4()),
                    "name": vals.get("company_name"),
                    "address": vals.get("company_address"),
                    "gstin": vals.get("company_gstin"),
                    "state": vals.get("company_state"),
                    "state_code": vals.get("company_state_code"),
                    "phone": vals.get("company_phone"),
                    "email": vals.get("company_email"),
                })
                print(f"Seeded companies with existing profile: {vals.get('company_name')}")
            else:
                print("No existing company_name in app_settings — nothing to seed.")
    print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(main())
