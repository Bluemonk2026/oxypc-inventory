"""Upload Tags result banner (2026-09-03), on /devices and /sales/ready:
 - Moved from directly below the table (`<table>.closest('.card').after(...)`)
   to the top of the page (`document.querySelector('main').prepend(...)`),
   with a smooth scrollIntoView so it's visible even if the user had
   scrolled down before uploading.
 - /sales/ready's page-level access (routers/sales.py `ready_allowed`) was
   the same require_roles(admin, sales, sales_manager, telecaller) reused
   by the page view itself, Multi-Request, Multi-Sell, and Upload Tags
   alike — opened to every logged-in user (get_current_user), matching
   /devices' already-unrestricted view_allowed, so every role can reach
   the page and see the banner. /devices needed no change here.
"""
import pathlib

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _read(folder, name):
    return (pathlib.Path(ROOT) / "templates" / folder / name).read_text(encoding="utf-8")


def test_devices_banner_prepends_to_main_not_after_the_table():
    src = _read("devices", "list.html")
    assert "document.querySelector('main').prepend(alertBox);" in src
    assert "closest('.card').after(alertBox)" not in src
    assert "alertBox.scrollIntoView(" in src


def test_ready_to_sale_banner_prepends_to_main_not_after_the_table():
    src = _read("sales", "ready_list.html")
    assert "document.querySelector('main').prepend(alertBox);" in src
    assert "closest('.card').after(alertBox)" not in src
    assert "alertBox.scrollIntoView(" in src


def test_ready_allowed_is_open_to_every_role_not_require_roles():
    src = (pathlib.Path(ROOT) / "routers" / "sales.py").read_text(encoding="utf-8")
    assert "ready_allowed = get_current_user" in src
    # `allowed` (used elsewhere in this router) is untouched — only the
    # Ready to Sale page's own gate was broadened.
    assert "allowed = require_roles(UserRole.admin, UserRole.sales, UserRole.sales_manager, UserRole.telecaller)" in src


def test_a_role_outside_the_old_allow_list_can_now_reach_sales_ready(app_client, make_user):  # noqa: F811
    # inventory_manager was never in require_roles(admin, sales,
    # sales_manager, telecaller) — a live request against it is the real
    # proof the page-level gate was actually loosened, not just the source
    # string.
    username, password = make_user("inventory_manager")
    _login(app_client, username, password)
    r = app_client.get("/sales/ready", follow_redirects=False)
    assert r.status_code == 200, r.text[:300]
