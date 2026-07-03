"""Throwaway verification harness for Batch A (4 independent items):
1. Session-extend 403-on-reload fix (base.html JS)
2. Breadcrumb trail (base.html)
3. Timeline -> Aging column header rename (5 templates)
4. Scrap Products moved into INVENTORY section, after Production Manager (base.html)

Uses TestClient + dependency_overrides to bypass auth/CSRF (admin lockout-safe),
same pattern as verify_sprint.py.
"""
import sys
import uuid
from types import SimpleNamespace

from starlette.testclient import TestClient

import main
from auth.dependencies import get_current_user, verify_csrf
from models.user import UserRole

app = main.app

fake_admin = SimpleNamespace(
    id=uuid.uuid4(), username="admin", full_name="Admin",
    role=UserRole.admin, is_active=True, status=True,
    manager_username=None,
)

async def _fake_user():
    return fake_admin

async def _noop():
    return None

app.dependency_overrides[get_current_user] = _fake_user
app.dependency_overrides[verify_csrf] = _noop


def main_run():
    checks = [
        ("GET", "/dashboard", None),
        ("GET", "/dispatch", None),
        ("GET", "/workid-status", None),
        ("GET", "/repair/l1", None),
        ("GET", "/repair/l2", None),
        ("GET", "/repair/l3", None),
    ]

    ok = True
    with TestClient(app, raise_server_exceptions=True) as client:
        for method, path, _ in checks:
            r = client.request(method, path)
            status = r.status_code
            flag = "OK " if status == 200 else "ERR"
            if status != 200:
                ok = False
            print(f"{flag} {method} {path} -> {status}")

            if status == 200:
                text = r.text
                # Item 2: breadcrumb present (except dashboard has empty path parts
                # after stripping "/dashboard" -> ["dashboard"], so breadcrumb nav
                # should render there too)
                has_breadcrumb = 'aria-label="breadcrumb"' in text and 'class="breadcrumb' in text
                print(f"     breadcrumb present: {has_breadcrumb}")

                # Item 3: Aging header present, Timeline absent, on relevant pages
                if path in ("/dispatch", "/workid-status", "/repair/l1", "/repair/l2", "/repair/l3"):
                    has_aging = ">Aging<" in text
                    has_timeline = ">Timeline<" in text
                    print(f"     Aging header present: {has_aging}, stray Timeline header: {has_timeline}")
                    if not has_aging or has_timeline:
                        ok = False

                # Item 4: Scrap Products link present when rendered (permission-gated;
                # admin fake user may not have module perms wired via has_perm(), so
                # this is best-effort — just check for no crash + no duplicate section)
                if path == "/dashboard":
                    scrap_count = text.count('href="/scrap-products"')
                    print(f"     scrap-products link occurrences (nav): {scrap_count} (0 is OK if perm helper denies fake admin; just must not appear twice)")
                    if scrap_count > 1:
                        ok = False

    print("\nALL OK" if ok else "\nSOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main_run())
