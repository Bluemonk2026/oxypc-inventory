"""Functional test: permission SAVE -> cache -> has_perm enforcement, and add-role."""
import asyncio
import urllib.request
import urllib.error
import urllib.parse

from sqlalchemy import select, delete
from database import AsyncSessionLocal
from models.user import User, UserRole
from models.role_permissions import RoleModulePermission, CustomRole, has_perm, _PERM_CACHE
from routers.master import load_all_permissions_to_cache
from auth.dependencies import create_access_token

BASE = "http://127.0.0.1:8000"
CSRF = "testcsrf"


async def admin_user():
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(User).where(User.role == UserRole.admin, User.status == True).limit(1)
        )).scalar_one()


def post(path, token, fields):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(BASE + path, data=data, method="POST")
    req.add_header("Cookie", f"access_token={token}; csrf_token={CSRF}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.geturl()
    except urllib.error.HTTPError as e:
        return e.code, str(e)


async def main():
    u = await admin_user()
    token = create_access_token({"sub": u.username})

    # ── Save a restrictive matrix for 'sales': grant dashboard+sales(enable,add),
    #    explicitly REVOKE 'lots' and 'telecalling' (omit their checkboxes) ──────
    fields = {
        "csrf_token": CSRF,
        "role_name": "sales",
        "perm_dashboard_can_enable": "on",
        "perm_sales_can_enable": "on",
        "perm_sales_can_add": "on",
        "perm_sales_can_edit": "on",
        # lots / telecalling intentionally omitted -> revoked
    }
    s, _ = post("/admin/master/permissions/save", token, fields)
    print(f"[save sales matrix] HTTP {s}")

    # Verify DB persisted
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(RoleModulePermission).where(RoleModulePermission.role_name == "sales")
        )).scalars().all()
        by_mod = {r.module: r for r in rows}
    print(f"  DB rows for sales: {len(rows)}")
    print(f"  lots.can_enable   = {by_mod['lots'].can_enable}   (expect False)")
    print(f"  sales.can_enable  = {by_mod['sales'].can_enable}  (expect True)")
    print(f"  sales.can_add     = {by_mod['sales'].can_add}     (expect True)")
    print(f"  sales.can_upload  = {by_mod['sales'].can_upload}  (expect False)")

    # Warm THIS process's cache from DB (the server already warmed its own on save).
    async with AsyncSessionLocal() as db:
        await load_all_permissions_to_cache(db)

    # Verify in-memory cache + has_perm (what the nav + dependency use)
    print("\n[has_perm enforcement]")
    checks = [
        ("sales", "lots", "enable", False),
        ("sales", "telecalling", "enable", False),
        ("sales", "sales", "enable", True),
        ("sales", "sales", "add", True),
        ("sales", "sales", "upload", False),
        ("admin", "lots", "enable", True),   # admin always True
    ]
    ok = True
    for role, mod, act, expect in checks:
        got = has_perm(role, mod, act)
        flag = "OK " if got == expect else "FAIL"
        if got != expect:
            ok = False
        print(f"  {flag} has_perm({role},{mod},{act}) = {got} (expect {expect})")

    # ── Test add-role ────────────────────────────────────────────────────────
    print("\n[add-role]")
    s2, _ = post("/admin/master/permissions/add-role", token, {
        "csrf_token": CSRF,
        "role_name": "Warehouse Manager",   # should sanitize -> warehouse_manager
        "display_name": "Warehouse Manager",
    })
    print(f"  add-role HTTP {s2}")
    async with AsyncSessionLocal() as db:
        cr = (await db.execute(
            select(CustomRole).where(CustomRole.role_name == "warehouse_manager")
        )).scalar_one_or_none()
    print(f"  custom role created: {cr.role_name if cr else None} (expect warehouse_manager)")

    # ── Cleanup: restore sales to unrestricted (delete matrix rows) so we don't
    #    accidentally lock the real sales role out. Also remove test custom role. ─
    async with AsyncSessionLocal() as db:
        await db.execute(delete(RoleModulePermission).where(RoleModulePermission.role_name == "sales"))
        await db.execute(delete(CustomRole).where(CustomRole.role_name == "warehouse_manager"))
        await db.commit()
    _PERM_CACHE.pop("sales", None)
    print("\n[cleanup] sales matrix + test role removed; sales back to permissive")

    print("\nRESULT:", "PASS" if (s == 200 and ok and cr is not None) else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())
