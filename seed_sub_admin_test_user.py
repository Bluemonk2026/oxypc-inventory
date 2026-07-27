"""Seed a sub_admin test user for verifying the Sub Admin Role RBAC feature.

Creates (or refreshes) user 'subadmintest' with role 'sub_admin', and grants
that role the Admin Settings accordion modules so the accordion is visible on
login. Idempotent. Run on the target box:  python3 seed_sub_admin_test_user.py
"""
import asyncio
from sqlalchemy import select, delete
from database import AsyncSessionLocal
from models.user import User
from models.role_permissions import RoleModulePermission, CustomRole
from auth.dependencies import hash_password

USERNAME = "subadmintest"
PASSWORD = "SubAdmin@123"
GRANT = [
    "admin_settings", "admin_users", "admin_master", "sidebar_config",
    "landing_pages", "company_settings", "attendance_config", "move_device_internal",
    "terms_conditions",
]


async def main():
    async with AsyncSessionLocal() as s:
        cr = (await s.execute(
            select(CustomRole).where(CustomRole.role_name == "sub_admin")
        )).scalar_one_or_none()
        if not cr:
            s.add(CustomRole(role_name="sub_admin", display_name="Sub Admin", created_by="verify"))
            print("created sub_admin CustomRole")
        else:
            print("sub_admin CustomRole already present")

        u = (await s.execute(
            select(User).where(User.username == USERNAME)
        )).scalar_one_or_none()
        if not u:
            s.add(User(username=USERNAME, full_name="Sub Admin Test", role="sub_admin",
                       password_hash=hash_password(PASSWORD), status=True, created_by="verify"))
            print("created user", USERNAME)
        else:
            u.role = "sub_admin"
            u.password_hash = hash_password(PASSWORD)
            u.status = True
            print("updated existing user", USERNAME)

        await s.execute(delete(RoleModulePermission).where(RoleModulePermission.role_name == "sub_admin"))
        for m in GRANT:
            s.add(RoleModulePermission(role_name="sub_admin", module=m,
                  can_enable=True, can_add=True, can_edit=True, can_upload=True, updated_by="verify"))
        await s.commit()
        print("granted modules:", ", ".join(GRANT))


if __name__ == "__main__":
    asyncio.run(main())
