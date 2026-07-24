"""One-shot migration: dealers.crm_contact_id as a real UUID FK.

Why this exists rather than leaving it to the startup provisioner:

db_validator._sql_type() had no UUID branch, so ADD COLUMN emitted TEXT for
every postgresql.UUID column. A text column holding uuid-shaped strings cannot
carry a foreign key and forces a cast on every comparison — the same drift
migrate_fix_prod_uuid_drift.py had to repair before. The type map is fixed now,
but any database that already ran the old code has a TEXT column sitting there,
and the provisioner will not correct an existing column's type.

Safe to run repeatedly, and safe on a database that never had the bad column:
  - creates the column as UUID if absent
  - converts TEXT -> UUID only if it is currently TEXT
  - adds the FK constraint only if it is missing

Run: python migrate_dealer_crm_contact_link.py
"""
import asyncio
from sqlalchemy import text
from database import engine


async def main():
    async with engine.begin() as conn:
        col_type = (await conn.execute(text("""
            select data_type from information_schema.columns
            where table_name = 'dealers' and column_name = 'crm_contact_id'
        """))).scalar()

        if col_type is None:
            print("column absent -> creating as UUID")
            await conn.execute(text(
                "ALTER TABLE dealers ADD COLUMN crm_contact_id UUID NULL"))
        elif col_type.lower() in ("text", "character varying"):
            # USING is required: postgres will not implicitly cast text->uuid.
            # Any row whose value is not a valid uuid would abort the ALTER,
            # which is the correct outcome - it means the data is not what the
            # model claims and silently discarding it would be worse.
            print(f"column is {col_type} -> converting to UUID")
            await conn.execute(text(
                "ALTER TABLE dealers ALTER COLUMN crm_contact_id "
                "TYPE UUID USING NULLIF(crm_contact_id, '')::uuid"))
        else:
            print(f"column already {col_type} -> no type change needed")

        has_fk = (await conn.execute(text("""
            select 1 from information_schema.table_constraints tc
            join information_schema.key_column_usage kcu
              on tc.constraint_name = kcu.constraint_name
            where tc.table_name = 'dealers'
              and tc.constraint_type = 'FOREIGN KEY'
              and kcu.column_name = 'crm_contact_id'
            limit 1
        """))).scalar()
        if has_fk:
            print("FK already present")
        else:
            print("adding FK dealers.crm_contact_id -> crm_contacts.id")
            await conn.execute(text(
                "ALTER TABLE dealers ADD CONSTRAINT fk_dealers_crm_contact "
                "FOREIGN KEY (crm_contact_id) REFERENCES crm_contacts(id)"))

        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_dealers_crm_contact_id "
            "ON dealers (crm_contact_id)"))

    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
