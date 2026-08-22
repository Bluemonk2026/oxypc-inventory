"""Topbar Back/Forward history pill.

Replaces the old plain "Back" button. Server-side we only control whether the
control renders at all (hidden on the homepage) and that both buttons start
disabled — enabling them is a client-side decision the browser makes from its
own session history, which a server-rendered test can't observe.

"Homepage" here means where routers/auth.py's `_first_landing()` drops each
role right after login: /dashboard for admin, /attendance for everyone else.
(routers/dashboard.py's bare "/" redirects admin to /devices instead — a
separate, pre-existing mismatch with login's own landing page, not something
this control follows.)
"""
import pytest

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def test_nav_history_pill_hidden_on_admin_home(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/dashboard", follow_redirects=True).text
    assert 'id="navHistoryBack"' not in html
    assert 'id="navHistoryForward"' not in html
    assert 'onclick="history.back()"' not in html, "old plain Back button must be gone"


def test_nav_history_pill_hidden_on_non_admin_home(app_client, make_user):  # noqa: F811
    username, password = make_user("spare_parts_manager")
    _login(app_client, username, password)
    html = app_client.get("/attendance", follow_redirects=True).text
    assert 'id="navHistoryBack"' not in html
    assert 'id="navHistoryForward"' not in html


def test_nav_history_pill_shown_and_disabled_by_default_elsewhere(app_client, make_user):  # noqa: F811
    username, password = make_user("spare_parts_manager")
    _login(app_client, username, password)
    html = app_client.get("/spare-parts", follow_redirects=True).text
    assert 'id="navHistoryBack"' in html
    assert 'id="navHistoryForward"' in html
    # Both start disabled in the server-rendered markup; JS enables them
    # based on the per-tab sessionStorage history stack after load.
    back = html.split('id="navHistoryBack"', 1)[1].split(">", 1)[0]
    fwd = html.split('id="navHistoryForward"', 1)[1].split(">", 1)[0]
    assert "disabled" in back
    assert "disabled" in fwd
