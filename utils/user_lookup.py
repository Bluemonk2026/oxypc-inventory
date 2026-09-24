"""Shared "who added this / who do they report to" display helper.

Used by any list page that shows a record's creator (CRM Contacts' Added By,
Deals' Created By, ...) alongside their manager, per User.reports_to (set via
Admin > User Management). Centralised so the resolution logic — username ->
full_name, then reports_to username -> full_name — isn't duplicated per page.
"""
from sqlalchemy import select
from models.user import User


async def added_by_display_map(db) -> dict[str, dict]:
    """{username: {"name": full_name, "reports_to": manager_full_name_or_None}}."""
    rows = (await db.execute(select(User.username, User.full_name, User.reports_to))).all()
    full_name_by_username = {u: (n or u) for u, n, _ in rows}
    reports_to_by_username = {u: r for u, _, r in rows}
    return {
        u: {
            "name": full_name_by_username[u],
            "reports_to": full_name_by_username.get(reports_to_by_username[u], reports_to_by_username[u])
                          if reports_to_by_username[u] else None,
        }
        for u in full_name_by_username
    }
