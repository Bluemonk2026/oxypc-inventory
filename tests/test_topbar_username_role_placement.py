"""Topbar (templates/base.html) username/role block, 2026-09-03:
 - Moved to after the Logout button (was between the server-status badge
   and the notification bell).
 - Role badge now sits below the username (stacked in a flex-column),
   not beside it inline.
 - Username rendered uppercase via Bootstrap's text-uppercase utility
   (CSS text-transform, not a Python .upper() call — current_user.full_name
   itself is untouched, so anything reading it elsewhere still gets the
   original casing).
 - Username at 1rem font-size, and the whole stacked block padded 1rem
   left/right (Bootstrap's px-3 utility).
"""
from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def test_username_role_block_comes_after_the_logout_form(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/dashboard", follow_redirects=True).text

    logout_pos = html.index('action="/auth/logout"')
    profile_pos = html.index('href="/auth/profile"')
    assert logout_pos < profile_pos


def test_username_is_stacked_above_role_badge_and_uppercased(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/dashboard", follow_redirects=True).text

    block_start = html.index('<!-- Username + role, stacked')
    block_end = html.index('</div>', html.index('badge bg-primary mt-1', block_start)) + len('</div>')
    block = html[block_start:block_end]

    assert "text-uppercase" in block
    assert 'href="/auth/profile"' in block
    name_pos = block.index('href="/auth/profile"')
    badge_pos = block.index('badge bg-primary mt-1')
    assert name_pos < badge_pos  # name markup precedes the role badge markup
    assert "d-flex flex-column" in block
    assert "px-3" in block  # 1rem left/right padding on the whole block
    assert 'style="font-size:1rem"' in block  # username font-size
