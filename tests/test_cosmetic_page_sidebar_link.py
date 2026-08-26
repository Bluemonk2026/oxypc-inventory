"""Dynamic "Cosmetic Page" sidebar link (templates/base.html):
 - Additive to the existing "Cosmetic & Paint" hub link, which is unchanged —
   it's still shown to ANY role with any of the 8 cosmetic modules enabled in
   the Module Permission Matrix, exactly as before this batch.
 - The new link only ever appears for the non-manager cosmetic-eligible roles
   (qc_inspector, inventory_manager, sales_manager) — never admin or
   cosmetic_manager, who already reach every stage via the hub link's tabs.
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
