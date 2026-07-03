"""
OxyPC Inventory — seed can_enable=False rows for the 7 newly-matrix-managed
Application Settings modules (move_device_internal, stage_control,
aging_tracker, stage_audit_log, system_audit_log, landing_pages,
wa_audit_log), for every role that already has an explicit permission
matrix configured.

Why: has_perm() defaults to PERMISSIVE (True) when a role has no row for a
module. These 7 modules were previously hard-gated to role=='admin' in the
sidebar; now that the sidebar also checks has_perm(), any role with an
existing (non-empty) matrix — meaning an admin has deliberately locked that
role down to a specific module set — would otherwise silently gain access
to these sensitive admin tools the moment this code ships, until the admin
re-saves that role's matrix. This script closes that window by writing an
explicit can_enable=False row for each already-configured role, so nothing
new becomes visible until an admin deliberately checks the box.

Roles with NO existing matrix rows at all are untouched — they were already
fully permissive for every module before this change, so this doesn't
change their access.

Usage: python migrate_seed_app_settings_perms.py
"""
import asyncio
from sqlalchemy import select
from database import AsyncSessionLocal
from models.role_permissions import RoleModulePermission

NEW_MODULES = [
    "move_device_internal", "stage_control", "aging_tracker",
    "stage_audit_log", "system_audit_log", "landing_pages", "wa_audit_log",
]


async def main():
    async with AsyncSessionLocal() as db:
        roles = (await db.execute(select(RoleModulePermission.role_name).distinct())).scalars().all()
        print(f"Roles with an existing matrix: {roles}")

        inserted = 0
        for role_name in roles:
            existing_mods = set((await db.execute(
                select(RoleModulePermission.module).where(RoleModulePermission.role_name == role_name)
            )).scalars().all())
            for mod in NEW_MODULES:
                if mod in existing_mods:
                    continue
                db.add(RoleModulePermission(
                    role_name=role_name, module=mod,
                    can_enable=False, can_add=False, can_edit=False, can_upload=False,
                    updated_by="migrate_seed_app_settings_perms.py",
                ))
                inserted += 1
        await db.commit()
        print(f"Inserted {inserted} can_enable=False rows.")


if __name__ == "__main__":
    asyncio.run(main())
