"""Fix userrole enum - add missing values: sales_manager, telecaller"""
import asyncio
import asyncpg


async def fix():
    conn = await asyncpg.connect("postgresql://oxypc:oxypc123@localhost:5432/oxypc_db")

    # Check current enum values
    rows = await conn.fetch(
        "SELECT enumlabel FROM pg_enum "
        "JOIN pg_type ON pg_enum.enumtypid = pg_type.oid "
        "WHERE pg_type.typname = 'userrole' ORDER BY enumsortorder"
    )
    current = [r["enumlabel"] for r in rows]
    print("Current userrole values:", current)

    # Add missing values
    missing = ["sales_manager", "telecaller"]
    for val in missing:
        if val not in current:
            await conn.execute(f"ALTER TYPE userrole ADD VALUE IF NOT EXISTS '{val}'")
            print(f"  + Added: {val}")
        else:
            print(f"  . Already exists: {val}")

    # Verify
    rows2 = await conn.fetch(
        "SELECT enumlabel FROM pg_enum "
        "JOIN pg_type ON pg_enum.enumtypid = pg_type.oid "
        "WHERE pg_type.typname = 'userrole' ORDER BY enumsortorder"
    )
    print("Updated userrole values:", [r["enumlabel"] for r in rows2])
    await conn.close()
    print("Done.")


asyncio.run(fix())
