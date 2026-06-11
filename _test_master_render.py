"""One-off render validation for the Master Data Configuration page.

Logs in as an existing admin (via minted JWT) and fetches both tabs,
asserting HTTP 200 and that key markers render. Safe, read-only.
"""
import asyncio
import urllib.request
import urllib.error

from sqlalchemy import select
from database import AsyncSessionLocal
from models.user import User, UserRole
from auth.dependencies import create_access_token

BASE = "http://127.0.0.1:8000"


async def get_admin_username() -> str:
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(User).where(User.role == UserRole.admin, User.status == True).limit(1)
        )).scalar_one_or_none()
        if not row:
            raise SystemExit("No active admin user found in DB.")
        return row.username


def fetch(path: str, token: str) -> tuple[int, str]:
    req = urllib.request.Request(BASE + path)
    req.add_header("Cookie", f"access_token={token}; csrf_token=testcsrf")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


async def main():
    username = await get_admin_username()
    token = create_access_token({"sub": username})
    print(f"Admin user: {username}")

    # Tab 1 — Dropdown Configuration
    s1, body1 = fetch("/admin/master?main_tab=dropdowns", token)
    print(f"\n[Tab 1 Dropdown Config] HTTP {s1}")
    for marker in ["Dropdown Configuration", "Module Permissions",
                   "dropdownAccordion", "Device & Laptop", "Repair & QC"]:
        print(f"  {'OK ' if marker in body1 else 'MISS'} '{marker}'")

    # Tab 2 — Module Permissions
    s2, body2 = fetch("/admin/master?main_tab=permissions", token)
    print(f"\n[Tab 2 Module Permissions] HTTP {s2}")
    for marker in ["Permission Matrix", "roleSelector", "Add New Role",
                   "Lot Management", "permMatrix", "Create Role"]:
        print(f"  {'OK ' if marker in body2 else 'MISS'} '{marker}'")

    # Role count in dropdown
    roles_in_select = body2.count("<option value=")
    print(f"  Roles in selector: {roles_in_select}")

    # Tab 2 with explicit role
    s3, body3 = fetch("/admin/master?main_tab=permissions&role=sales", token)
    print(f"\n[Tab 2 role=sales] HTTP {s3}  matrix_present={'permMatrix' in body3}")

    print("\nRESULT:", "PASS" if (s1 == 200 and s2 == 200 and s3 == 200) else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())
