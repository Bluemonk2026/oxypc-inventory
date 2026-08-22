"""User Management gets a Delete button — soft-delete only (status=False),
same as unchecking "Account Active" on Edit. Never a hard row delete: this
project's own convention is never to physically remove a user row (login
history, audit logs, and anything else with a users.id FK stays intact)."""
import pytest

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def test_delete_button_present_for_other_users_not_for_self(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)
    html = app_client.get("/admin/users", follow_redirects=True).text
    assert 'action="/admin/users/' in html and '/delete"' in html

    # The row for the currently logged-in admin must not offer a Delete button
    # for themselves (server-side guard too, but the button shouldn't tempt it).
    self_row = html.split(f">{username}<", 1)[1].split("</tr>", 1)[0]
    assert "/delete" not in self_row


def test_delete_sets_status_false_and_admin_cannot_delete_self(app_client, make_user):  # noqa: F811
    admin_username, admin_password = make_user("admin")
    target_username, _ = make_user("spare_parts_manager")
    _login(app_client, admin_username, admin_password)
    csrf = app_client.cookies.get("csrf_token") or "dummy"

    html = app_client.get("/admin/users", follow_redirects=True).text
    row = html.split(f">{target_username}<", 1)[1].split("</tr>", 1)[0]
    user_id = row.split('/admin/users/', 1)[1].split('/edit"', 1)[0]

    r = app_client.post(f"/admin/users/{user_id}/delete", data={"csrf_token": csrf}, follow_redirects=False)
    assert r.status_code == 302, r.text[:500]

    # Deleted (status=False) users disappear from the default list — same
    # soft-delete-hides-by-default convention as is_trashed/is_active
    # elsewhere in this app. Showing "Inactive" but still listed is exactly
    # the "Delete doesn't work" symptom this replaces.
    html2 = app_client.get("/admin/users", follow_redirects=True).text
    assert f">{target_username}<" not in html2

    # Still findable/recoverable via Show Inactive.
    html3 = app_client.get("/admin/users", params={"show_inactive": "on"}, follow_redirects=True).text
    row3 = html3.split(f">{target_username}<", 1)[1].split("</tr>", 1)[0]
    assert "Inactive" in row3

    # Self-delete guarded server-side too, not just hidden in the UI.
    admin_id_row = html.split(f">{admin_username}<", 1)[1]
    admin_id = admin_id_row.split('/admin/users/', 1)[1].split('/edit"', 1)[0]
    r2 = app_client.post(f"/admin/users/{admin_id}/delete", data={"csrf_token": csrf}, follow_redirects=False)
    assert r2.status_code == 400
