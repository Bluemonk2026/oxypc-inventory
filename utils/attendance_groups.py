"""Attendance Group manager lookups, shared beyond the Attendance module.

Groups are configured in Application Settings -> Attendance Config: a named
group, one manager username, and a member list. The manager designation started
as an attendance-report scope, but it is the only place the app records "this
person supervises these people", so other modules (Dealer Management) now lean
on it to decide who can act on a team's records.

Both helpers are one query and are safe to call per request.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.attendance_group import AttendanceGroup, AttendanceGroupMember


async def managed_usernames(db: AsyncSession, username: str) -> list:
    """Usernames in every active group this user manages.

    Empty list means the user manages nothing — callers must treat that as
    "not a manager", not as "manages everyone".
    """
    if not username:
        return []
    group_ids = (await db.execute(
        select(AttendanceGroup.id).where(
            AttendanceGroup.manager_username == username,
            AttendanceGroup.is_active == True,
        )
    )).scalars().all()
    if not group_ids:
        return []
    members = (await db.execute(
        select(AttendanceGroupMember.username)
        .where(AttendanceGroupMember.group_id.in_(group_ids))
    )).scalars().all()
    return sorted(set(members))


async def is_group_manager(db: AsyncSession, username: str) -> bool:
    """Whether this user manages at least one active Attendance Group.

    True even for a group with no members yet — the designation is what grants
    the capability, not the size of the team.
    """
    if not username:
        return False
    found = (await db.execute(
        select(AttendanceGroup.id).where(
            AttendanceGroup.manager_username == username,
            AttendanceGroup.is_active == True,
        ).limit(1)
    )).scalar_one_or_none()
    return found is not None
