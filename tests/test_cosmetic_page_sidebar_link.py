"""Dynamic "Cosmetic Page" sidebar link (templates/base.html):
 - Additive to the existing "Cosmetic & Paint" hub link, which is unchanged —
   it's still shown to ANY role with any of the 8 cosmetic modules enabled in
   the Module Permission Matrix, exactly as before this batch.
 - The new link appears for every role EXCEPT admin and cosmetic_manager
   (who already reach every stage via the hub link's tabs) — including
   admin-created CUSTOM roles (e.g. a "Cosmetic Cleaning" role scoped to one
   stage), which aren't in the UserRole enum at all. The gate is a blacklist
   of those two roles, not a whitelist of qc_inspector/inventory_manager/
   sales_manager — a whitelist would silently exclude custom roles.
 - Points at whichever of the 6 mid-pipeline stages (Cleaning, Putty, Dry
   Sanding, Masking, Painting, Water Sanding) is enabled for that role in the
   Module Permission Matrix, in pipeline order — not a fixed page.
 - Disappears entirely if none of the 6 are enabled for that role.

Only the default-permission cases live here (no RoleModulePermission rows
seeded, so has_perm's enable=True default applies) — they can safely share
the app_client fixture. The cases that seed a RoleModulePermission row live
in test_cosmetic_page_sidebar_link_isolated.py instead: main.py's permission
cache is loaded once at app startup, so a row written after app_client's app
already started would silently not apply — see that file's docstring.
"""
from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def test_admin_and_cosmetic_manager_never_see_dynamic_link(app_client, make_user):  # noqa: F811
    for role in ("admin", "cosmetic_manager"):
        username, password = make_user(role)
        _login(app_client, username, password)
        html = app_client.get("/cosmetic/cleaning", follow_redirects=True).text
        assert "Cosmetic &amp; Paint" in html or "Cosmetic & Paint" in html
        assert "Cosmetic Page" not in html


def test_qc_inspector_sees_both_links_default_permissions(app_client, make_user):  # noqa: F811
    # No RoleModulePermission rows seeded — has_perm defaults enable=True, so
    # the hub link still shows (unchanged, permission-matrix driven) and the
    # new dynamic link picks the first stage in pipeline order (Cleaning).
    username, password = make_user("qc_inspector")
    _login(app_client, username, password)
    html = app_client.get("/cosmetic/cleaning", follow_redirects=True).text
    assert "Cosmetic &amp; Paint" in html or "Cosmetic & Paint" in html
    assert "Cosmetic Page" in html
    assert 'href="/cosmetic/cleaning"' in html


def test_custom_role_sees_dynamic_link_default_permissions(app_client, make_user):  # noqa: F811
    # A role name that isn't in the UserRole enum at all — e.g. an
    # admin-created "Cosmetic Cleaning" role — must still get the dynamic
    # link. Regression test for the whitelist bug: qc_inspector/
    # inventory_manager/sales_manager only covered the 3 built-in roles, so a
    # real custom role never matched no matter what was enabled for it.
    username, password = make_user("cosmetic_cleaning_specialist")
    _login(app_client, username, password)
    html = app_client.get("/cosmetic/cleaning", follow_redirects=True).text
    assert "Cosmetic Page" in html
    assert 'href="/cosmetic/cleaning"' in html
