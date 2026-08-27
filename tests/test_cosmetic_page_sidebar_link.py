"""Dynamic "Cosmetic Stage" sidebar link (templates/base.html, formerly
labelled "Cosmetic Page"):
 - Shown to any role scoped to at least one of the 6 mid-pipeline stages
   (Cleaning, Putty, Dry Sanding, Masking, Painting, Water Sanding) that
   isn't admin/cosmetic_manager — including admin-created CUSTOM roles
   (e.g. a "Cosmetic Cleaning" role scoped to one stage), which aren't in
   the UserRole enum at all. The gate is a blacklist of admin/
   cosmetic_manager, not a whitelist of qc_inspector/inventory_manager/
   sales_manager — a whitelist would silently exclude custom roles.
 - Points at whichever of the 6 mid-pipeline stages is enabled for that role
   in the Module Permission Matrix, in pipeline order — not a fixed page.
 - Disappears entirely if none of the 6 are enabled for that role.
 - The full "Cosmetic & Paint" hub link is now hidden for a genuine
   single-stage "Cosmetic User" role (e.g. a custom "Cosmetic Cleaning"
   role) even if cosmetic_received/cosmetic_completed are enabled for them
   in the Permission Matrix — this is a deliberate override, not a bug (see
   routers/cosmetic.py _is_cosmetic_stage_role). The 3 general-purpose
   supervisor roles (qc_inspector/inventory_manager/sales_manager) are
   explicitly excluded from that override and keep seeing BOTH links,
   unchanged from before this feature — only Admin, Cosmetic Manager, and
   those 3 roles get the hub.

Only the default-permission cases live here (no RoleModulePermission rows
seeded, so has_perm's enable=True default applies) — they can safely share
the app_client fixture. The cases that seed a RoleModulePermission row live
in test_cosmetic_page_sidebar_link_isolated.py instead: main.py's permission
cache is loaded once at app startup, so a row written after app_client's app
already started would silently not apply — see that file's docstring.
"""
from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def test_admin_and_cosmetic_manager_see_hub_not_stage_link(app_client, make_user):  # noqa: F811
    for role in ("admin", "cosmetic_manager"):
        username, password = make_user(role)
        _login(app_client, username, password)
        html = app_client.get("/cosmetic/cleaning", follow_redirects=True).text
        assert "Cosmetic &amp; Paint" in html or "Cosmetic & Paint" in html
        assert "Cosmetic Stage" not in html


def test_qc_inspector_sees_both_links_default_permissions(app_client, make_user):  # noqa: F811
    # qc_inspector is one of the 3 general-purpose supervisor roles excluded
    # from the hub-hiding override — unchanged from before this feature: the
    # hub still shows (permission-matrix driven) and the dynamic stage link
    # picks the first stage in pipeline order (Cleaning).
    username, password = make_user("qc_inspector")
    _login(app_client, username, password)
    html = app_client.get("/cosmetic/cleaning", follow_redirects=True).text
    assert "Cosmetic &amp; Paint" in html or "Cosmetic & Paint" in html
    assert "Cosmetic Stage" in html
    assert 'href="/cosmetic/cleaning"' in html


def test_custom_role_sees_stage_link_not_hub_default_permissions(app_client, make_user):  # noqa: F811
    # A role name that isn't in the UserRole enum at all — e.g. an
    # admin-created "Cosmetic Cleaning" role — must still get the dynamic
    # link, and never the full pipeline hub. Regression test for the
    # whitelist bug: qc_inspector/inventory_manager/sales_manager only
    # covered the 3 built-in roles, so a real custom role never matched no
    # matter what was enabled for it.
    username, password = make_user("cosmetic_cleaning_specialist")
    _login(app_client, username, password)
    html = app_client.get("/cosmetic/cleaning", follow_redirects=True).text
    assert "Cosmetic &amp; Paint" not in html and "Cosmetic & Paint" not in html
    assert "Cosmetic Stage" in html
    assert 'href="/cosmetic/cleaning"' in html
