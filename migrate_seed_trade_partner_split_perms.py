"""
OxyPC Inventory — seed can_enable=False rows for the 8 newly-split Trade
Partner modules (trade_partner_partners, trade_partner_listings,
trade_partner_bookings, trade_partner_my_desk, trade_partner_floors,
trade_partner_settings, trade_partner_manage_lots, trade_partner_bids),
for EVERY role — not just roles with an existing matrix (unlike
migrate_seed_app_settings_perms.py's precedent).

Why: has_perm() defaults to PERMISSIVE (True) when a role has no row for a
module. These 8 pages replace one shared "trade_partner" key (2026-09-22
split, routers/master.py PERM_MODULES) so each can be enabled independently
— but the ask was that access to all of them starts OFF for everyone, not
just for roles an admin already locked down. So this seeds an explicit
can_enable=False row for every role (built-in UserRole enum members, every
CustomRole, every role value actually in use on a User row, and every role
already holding a matrix row) except admin, which always bypasses the
matrix regardless of what's seeded here.

Idempotent: skips any role/module pair that already has a row.

Usage: python migrate_seed_trade_partner_split_perms.py
"""
import asyncio
from sqlalchemy import select
from database import AsyncSessionLocal
from models.role_permissions import RoleModulePermission, CustomRole
from models.user import User, UserRole

NEW_MODULES = [
    "trade_partner_partners", "trade_partner_listings", "trade_partner_bookings",
    "trade_partner_my_desk", "trade_partner_floors", "trade_partner_settings",
    "trade_partner_manage_lots", "trade_partner_bids",
]


async def main():
    async with AsyncSessionLocal() as db:
        builtin_roles = {r.value for r in UserRole}
        custom_roles = set((await db.execute(select(CustomRole.role_name))).scalars().all())
        user_roles = {
            (r.value if hasattr(r, "value") else str(r))
            for r in (await db.execute(select(User.role).distinct())).scalars().all()
        }
        matrix_roles = set((await db.execute(
            select(RoleModulePermission.role_name).distinct()
        )).scalars().all())

        all_roles = (builtin_roles | custom_roles | user_roles | matrix_roles) - {"admin"}
        print(f"Roles to seed (excluding admin): {sorted(all_roles)}")

        inserted = 0
        for role_name in sorted(all_roles):
            existing_mods = set((await db.execute(
                select(RoleModulePermission.module).where(RoleModulePermission.role_name == role_name)
            )).scalars().all())
            for mod in NEW_MODULES:
                if mod in existing_mods:
                    continue
                db.add(RoleModulePermission(
                    role_name=role_name, module=mod,
                    can_enable=False, can_add=False, can_edit=False, can_upload=False,
                    updated_by="migrate_seed_trade_partner_split_perms.py",
                ))
                inserted += 1
        await db.commit()
        print(f"Inserted {inserted} can_enable=False rows.")


if __name__ == "__main__":
    asyncio.run(main())
