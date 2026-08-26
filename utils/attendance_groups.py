"""Attendance Group manager lookups, shared beyond the Attendance module.

Groups are configured in Application Settings -> Group Config (Attendance
Config): a named group, one manager username, and a member list. The manager
designation started as an attendance-report scope, but it is the only place
the app records "this person supervises these people", so other modules
(Dealer Management, WorkID Status, the Cosmetic pipeline) now lean on it to
decide who can act on a team's records.

Membership is transitive: if Manager B's group contains A as a member, and A
manages their own group of 10, then B's team automatically includes A's 10
members too (and so on down any chain) — the same rule applies everywhere
these helpers back a "manager sees their team" decision, since it all comes
from this one function. Cycles (A manages a group containing B, B manages a
group containing A) can't cause an infinite loop — each username is expanded
as a manager at most once.

Both helpers are one query and are safe to call per request.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.attendance_group import AttendanceGroup, AttendanceGroupMember


async def managed_usernames(db: AsyncSession, username: str) -> list:
    """Usernames in every active group this user manages, transitively: a
    member who themselves manages a group contributes their own members too,
    all the way down the chain.

    Empty list means the user manages nothing — callers must treat that as
    "not a manager", not as "manages everyone".
    """
    if not username:
        return []
    # One query for the whole manager->members graph rather than one round
    # trip per level of the chain — cheap even for a deep org, and the only
    # way to do this without an unbounded number of queries for an unknown
    # chain depth.
    rows = (await db.execute(
        select(AttendanceGroup.manager_username, AttendanceGroupMember.username)
        .join(AttendanceGroupMember, AttendanceGroupMember.group_id == AttendanceGroup.id)
        .where(AttendanceGroup.is_active == True)
    )).all()
    members_by_manager: dict = {}
    for manager, member in rows:
        members_by_manager.setdefault(manager, set()).add(member)

    result: set = set()
    expanded: set = set()
    stack = [username]
    while stack:
        manager = stack.pop()
        if manager in expanded:
            continue
        expanded.add(manager)
        for member in members_by_manager.get(manager, ()):
            if member not in result:
                result.add(member)
                stack.append(member)
    # A genuine cycle (A manages a group containing B, B manages a group
    # containing A) makes the transitive closure mathematically include A
    # themselves — harmless in theory, but a manager showing up in their own
    # team reads as a bug wherever this feeds a dropdown or a visibility
    # check, so it's excluded explicitly rather than relying on callers to
    # remember to.
    result.discard(username)
    return sorted(result)


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
