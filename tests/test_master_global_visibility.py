"""Master Data — "Global Visibility" tab (2026-09-02):

Lists every sidebar module (same list as Sub Admin Role, minus admin_master)
with an instant-AJAX toggle to hide it from the sidebar for EVERY user,
INCLUDING admin — a separate, stronger layer from Module Permissions
(RoleModulePermission/has_perm), which is per-role and always lets admin
through. Modeled directly on the existing breadcrumb-toggle feature
(routers/landing_pages.py) — same AppSetting-backed cache pattern, same
instant-save UX, no new SQLAlchemy model.

Master Data itself (admin_master) is excluded from the toggle list and the
toggle endpoint rejects it outright — hiding the page this control lives on
would strand admin with no UI path to undo it.
"""
import pathlib
import subprocess
import sys
import uuid

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def _unhide(app_client, module_key):
    """Restore visibility via the toggle endpoint itself, not a raw DB
    delete — get_cached_module_hidden is backed by an in-memory cache that a
    direct AppSetting delete would leave stale for the rest of the test
    session."""
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    app_client.post("/admin/master/global-visibility/toggle",
                    data={"csrf_token": csrf, "module_key": module_key, "hidden": "0"})


def test_global_visibility_tab_lists_modules_and_excludes_admin_master(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/admin/master?main_tab=global_visibility", follow_redirects=True).text
    assert ">Global Visibility<" in html
    assert 'id="gv-dashboard"' in html
    assert 'id="gv-admin_master"' not in html, "Master Data must not be toggleable — it hosts this control"


def test_toggle_hides_module_from_sidebar_for_admin_too(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    username, password = make_user("admin")
    try:
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        # The sidebar's own dashboard link markup — distinct from the
        # unrelated "Home" breadcrumb link that also points to /dashboard
        # (base.html:810), which module_hidden('dashboard') never gates.
        sidebar_link = 'href="/dashboard" class="nav-link'

        before = app_client.get("/dashboard", follow_redirects=True).text
        assert sidebar_link in before

        r = app_client.post("/admin/master/global-visibility/toggle",
                            data={"csrf_token": csrf, "module_key": "dashboard", "hidden": "1"})
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True

        after = app_client.get("/dashboard", follow_redirects=True).text
        assert sidebar_link not in after, "admin must also lose the sidebar link once hidden"
    finally:
        _unhide(app_client, "dashboard")


def test_toggle_back_on_restores_the_sidebar_link(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    try:
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        app_client.post("/admin/master/global-visibility/toggle",
                        data={"csrf_token": csrf, "module_key": "dashboard", "hidden": "1"})
        r = app_client.post("/admin/master/global-visibility/toggle",
                            data={"csrf_token": csrf, "module_key": "dashboard", "hidden": "0"})
        assert r.status_code == 200
        assert r.json()["hidden"] is False

        after = app_client.get("/dashboard", follow_redirects=True).text
        assert 'href="/dashboard" class="nav-link' in after
    finally:
        _unhide(app_client, "dashboard")


def test_admin_master_cannot_be_hidden_via_the_endpoint(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    csrf = app_client.cookies.get("csrf_token") or "dummy"
    r = app_client.post("/admin/master/global-visibility/toggle",
                        data={"csrf_token": csrf, "module_key": "admin_master", "hidden": "1"})
    assert r.status_code == 400
