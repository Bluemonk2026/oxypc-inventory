"""One-shot migration: create attendance_groups and attendance_group_members
tables for the Attendance Config feature (group manager scoping).

Run: python migrate_attendance_groups.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS attendance_groups (
        id UUID PRIMARY KEY,
        name VARCHAR(100) NOT NULL UNIQUE,
        manager_username VARCHAR(50) NOT NULL,
        created_by VARCHAR(50) NULL,
        created_at TIMESTAMP NULL,
        is_active BOOLEAN NOT NULL DEFAULT true
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_attendance_groups_manager_username ON attendance_groups (manager_username)",
    """
    CREATE TABLE IF NOT EXISTS attendance_group_members (
        id UUID PRIMARY KEY,
        group_id UUID NOT NULL REFERENCES attendance_groups(id),
        username VARCHAR(50) NOT NULL,
        created_at TIMESTAMP NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_attendance_group_members_group_id ON attendance_group_members (group_id)",
    "CREATE INDEX IF NOT EXISTS ix_attendance_group_members_username ON attendance_group_members (username)",
]

async def main():
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt.strip()[:80]}...")
            await conn.execute(text(stmt))
    print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(main())
