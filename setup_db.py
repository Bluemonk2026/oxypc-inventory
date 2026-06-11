"""
OxyPC Inventory — First Run Database Setup
Run this ONCE after installing PostgreSQL to create tables and admin user.
Usage: python setup_db.py
"""
import asyncio
import sys
import getpass
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text

from config import DATABASE_URL
from database import Base
from models import User, LoginLog, Lot, Device, StageMovement, RepairJob, QCCheck, Sale, Return
from models import SparePart, SparePartPurchase, SparePartConsumption, RAMTracking, MasterData
from models.user import UserRole
from models.master import MASTER_SEED
from auth.dependencies import hash_password


async def create_tables(engine):
    print("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("  Tables created successfully.")


async def create_admin(session: AsyncSession):
    from sqlalchemy import select
    result = await session.execute(select(User).where(User.username == "admin"))
    if result.scalar_one_or_none():
        print("  Admin user already exists. Skipping.")
        return

    print("\nCreate admin account:")
    username = input("  Admin username [admin]: ").strip() or "admin"
    full_name = input("  Admin full name [OxyPC Admin]: ").strip() or "OxyPC Admin"

    while True:
        password = getpass.getpass("  Password [oxypc@admin123]: ").strip() or "oxypc@admin123"
        confirm = getpass.getpass("  Confirm password: ").strip() or "oxypc@admin123"
        if password == confirm:
            break
        print("  Passwords don't match. Try again.")

    admin = User(
        username=username,
        full_name=full_name,
        password_hash=hash_password(password),
        role=UserRole.admin,
        status=True,
        created_by="setup",
    )
    session.add(admin)
    await session.commit()
    print(f"\n  Admin user '{username}' created.")
    print(f"  Login at: http://localhost:8000")


async def seed_master_data(session: AsyncSession):
    from sqlalchemy import select
    existing = await session.execute(select(MasterData))
    if existing.scalars().first():
        print("  Master data already seeded. Skipping.")
        return
    print("Seeding master data...")
    count = 0
    for category, values in MASTER_SEED.items():
        for i, value in enumerate(values):
            item = MasterData(category=category, value=value, display_order=i)
            session.add(item)
            count += 1
    await session.commit()
    print(f"  {count} master data values seeded.")


async def main():
    print("=" * 50)
    print("  OxyPC Inventory — Database Setup")
    print("=" * 50)
    print(f"\nDatabase: {DATABASE_URL}\n")

    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        print("  Database connection: OK")
    except Exception as e:
        print(f"\nERROR: Cannot connect to database.")
        print(f"  {e}")
        print("\nMake sure PostgreSQL is running and the database exists:")
        print("  psql -U postgres -c \"CREATE USER oxypc WITH PASSWORD 'oxypc123';\"")
        print("  psql -U postgres -c \"CREATE DATABASE oxypc_db OWNER oxypc;\"")
        sys.exit(1)

    await create_tables(engine)

    async with SessionLocal() as session:
        await create_admin(session)
        await seed_master_data(session)

    await engine.dispose()
    print("\n" + "=" * 50)
    print("  Setup complete!")
    print("  Run:  python main.py")
    print("  Then open: http://localhost:8000")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
