"""
OxyPC Inventory — UAT User Seeder
Run AFTER setup_db.py to create one test account for every role.
Usage: python seed_uat_users.py
"""
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from config import DATABASE_URL
from models.user import User, UserRole
from auth.dependencies import hash_password

# ─────────────────────────────────────────────
#  UAT USER DEFINITIONS  (username / password / role)
# ─────────────────────────────────────────────
UAT_USERS = [
    {
        "username":  "uat_admin",
        "full_name": "UAT Admin User",
        "password":  "UatAdmin@123",
        "role":      UserRole.admin,
    },
    {
        "username":  "uat_invmgr",
        "full_name": "UAT Inventory Manager",
        "password":  "UatInvMgr@123",
        "role":      UserRole.inventory_manager,
    },
    {
        "username":  "uat_iqc",
        "full_name": "UAT IQC Inspector",
        "password":  "UatIqc@123",
        "role":      UserRole.iqc_inspector,
    },
    {
        "username":  "uat_l1",
        "full_name": "UAT L1 Engineer",
        "password":  "UatL1@123",
        "role":      UserRole.l1_engineer,
    },
    {
        "username":  "uat_l2",
        "full_name": "UAT L2 Engineer",
        "password":  "UatL2@123",
        "role":      UserRole.l2_engineer,
    },
    {
        "username":  "uat_l3",
        "full_name": "UAT L3 Engineer",
        "password":  "UatL3@123",
        "role":      UserRole.l3_engineer,
    },
    {
        "username":  "uat_qc",
        "full_name": "UAT QC Inspector",
        "password":  "UatQc@123",
        "role":      UserRole.qc_inspector,
    },
    {
        "username":  "uat_sales",
        "full_name": "UAT Sales Executive",
        "password":  "UatSales@123",
        "role":      UserRole.sales,
    },
    {
        "username":  "uat_spares",
        "full_name": "UAT Spare Parts Manager",
        "password":  "UatSpares@123",
        "role":      UserRole.spare_parts_manager,
    },
]


async def seed(session: AsyncSession):
    created = 0
    skipped = 0
    for u in UAT_USERS:
        result = await session.execute(
            select(User).where(User.username == u["username"])
        )
        if result.scalar_one_or_none():
            print(f"  [SKIP]  {u['username']:20s}  (already exists)")
            skipped += 1
            continue

        user = User(
            username=u["username"],
            full_name=u["full_name"],
            password_hash=hash_password(u["password"]),
            role=u["role"],
            status=True,
            created_by="uat_seeder",
        )
        session.add(user)
        print(f"  [OK]    {u['username']:20s}  role={u['role'].value:22s}  pass={u['password']}")
        created += 1

    await session.commit()
    print(f"\n  Done — {created} created, {skipped} skipped.")


async def main():
    print("=" * 60)
    print("  OxyPC — UAT User Seeder")
    print("=" * 60)

    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    try:
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        print(f"\nERROR: Cannot connect to database: {e}")
        sys.exit(1)

    async with SessionLocal() as session:
        await seed(session)

    await engine.dispose()
    print("\n  Run the app and log in with any of the above credentials.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
