"""Group Config membership is transitive (utils/attendance_groups.
managed_usernames): if Manager A has 10 members and Manager A is themselves
a member under Manager B, Manager B's team automatically includes all 10 of
A's members too — wherever this helper backs a "manager sees their team"
decision (WorkID Status, Attendance Report, Dealer Management, the Cosmetic
pipeline's Manager/Member visibility and Move-modal dropdown).
"""
import pathlib
import subprocess
import sys
import uuid

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def _seed_group(name, manager_username, member_usernames):
    members_py = repr(list(member_usernames))
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from database import AsyncSessionLocal
from models.attendance_group import AttendanceGroup, AttendanceGroupMember

async def main():
    async with AsyncSessionLocal() as db:
        g = AttendanceGroup(name="{name}", manager_username="{manager_username}", is_active=True)
        db.add(g)
        await db.flush()
        for uname in {members_py}:
            db.add(AttendanceGroupMember(group_id=g.id, username=uname))
        await db.commit()
        print(g.id)

asyncio.run(main())
""")


def _cleanup_group(group_id):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.attendance_group import AttendanceGroup, AttendanceGroupMember

async def main():
    async with AsyncSessionLocal() as db:
        for m in (await db.execute(select(AttendanceGroupMember).where(
                AttendanceGroupMember.group_id == "{group_id}"))).scalars().all():
            await db.delete(m)
        g = (await db.execute(select(AttendanceGroup).where(AttendanceGroup.id == "{group_id}"))).scalar_one_or_none()
        if g:
            await db.delete(g)
        await db.commit()

asyncio.run(main())
""")


def _managed_usernames(username):
    return _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from database import AsyncSessionLocal
from utils.attendance_groups import managed_usernames

async def main():
    async with AsyncSessionLocal() as db:
        print(",".join(await managed_usernames(db, "{username}")))

asyncio.run(main())
""")


def test_manager_of_a_manager_inherits_their_whole_team():
    suffix = uuid.uuid4().hex[:6]
    manager_a = f"itest_mgrA_{suffix}"
    manager_b = f"itest_mgrB_{suffix}"
    members_of_a = [f"itest_m{i}_{suffix}" for i in range(3)]

    group_a_id = _seed_group(f"ITestTeamA{suffix}", manager_a, members_of_a)
    group_b_id = _seed_group(f"ITestTeamB{suffix}", manager_b, [manager_a])
    try:
        result = set(filter(None, _managed_usernames(manager_b).split(",")))
        assert result == set(members_of_a) | {manager_a}, result

        # Manager A's own team is unaffected — still just their direct members.
        result_a = set(filter(None, _managed_usernames(manager_a).split(",")))
        assert result_a == set(members_of_a), result_a
    finally:
        _cleanup_group(group_a_id)
        _cleanup_group(group_b_id)


def test_three_level_chain_flattens_fully():
    suffix = uuid.uuid4().hex[:6]
    top = f"itest_top_{suffix}"
    mid = f"itest_mid_{suffix}"
    leaf_manager = f"itest_leaf_{suffix}"
    leaf_members = [f"itest_lm{i}_{suffix}" for i in range(2)]

    g1 = _seed_group(f"ITestLeaf{suffix}", leaf_manager, leaf_members)
    g2 = _seed_group(f"ITestMid{suffix}", mid, [leaf_manager])
    g3 = _seed_group(f"ITestTop{suffix}", top, [mid])
    try:
        result = set(filter(None, _managed_usernames(top).split(",")))
        assert result == {mid, leaf_manager} | set(leaf_members), result
    finally:
        _cleanup_group(g1)
        _cleanup_group(g2)
        _cleanup_group(g3)


def test_cycle_does_not_infinite_loop():
    """A manages a group containing B; B manages a group containing A."""
    suffix = uuid.uuid4().hex[:6]
    user_a = f"itest_cyc_a_{suffix}"
    user_b = f"itest_cyc_b_{suffix}"

    g1 = _seed_group(f"ITestCycA{suffix}", user_a, [user_b])
    g2 = _seed_group(f"ITestCycB{suffix}", user_b, [user_a])
    try:
        result = set(filter(None, _managed_usernames(user_a).split(",")))
        assert result == {user_b}, result
    finally:
        _cleanup_group(g1)
        _cleanup_group(g2)


def test_workid_status_and_attendance_report_both_use_the_shared_helper():
    """Both call sites were previously duplicated, non-transitive inline
    queries — confirm they now delegate to managed_usernames instead of
    re-querying AttendanceGroup/AttendanceGroupMember directly."""
    ws_src = open(pathlib.Path(ROOT) / "routers" / "workid_status.py", encoding="utf-8").read()
    assert "from utils.attendance_groups import managed_usernames" in ws_src
    assert "AttendanceGroup" not in ws_src

    att_src = open(pathlib.Path(ROOT) / "routers" / "attendance.py", encoding="utf-8").read()
    assert "from utils.attendance_groups import is_group_manager, managed_usernames" in att_src
