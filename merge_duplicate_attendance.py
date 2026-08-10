"""Merge duplicate (user_id, date) attendance rows, then add the unique index.

Background: attendance had no unique constraint on (user_id, date). A Check In
submitted twice before the first POST returned inserted two rows, and every
later read of that user's day then raised MultipleResultsFound -> HTTP 500.
routers/attendance.py now holds a per-user advisory lock so no new duplicates
can form; this script cleans up the ones created before that landed and adds
the constraint so the database enforces it too.

Merge rule, per duplicated (user_id, date):
  survivor      = earliest real check_in (a row with no check_in never wins)
  check_out     = latest non-null check_out across the group
  check_in_ip / check_out_ip / notes / marked_by = survivor's value, else the
                  first non-null found in the group (nothing is dropped)
  status        = survivor's (it was derived from the survivor's check-in time)
The other rows are deleted. Every value they carried is folded into the
survivor first.

Usage:
    python merge_duplicate_attendance.py            # dry run, changes nothing
    python merge_duplicate_attendance.py --apply     # merge + create the index
"""
import asyncio, sys
sys.path.insert(0, ".")
from sqlalchemy import select, func, delete, text
from database import AsyncSessionLocal, engine
from models.attendance import Attendance

APPLY = "--apply" in sys.argv
INDEX_NAME = "uq_attendance_user_date"


def _pick_survivor(rows):
    """Earliest real check-in wins; a row with no check_in only wins if no row
    in the group has one."""
    with_ci = [r for r in rows if r.check_in is not None]
    if with_ci:
        return min(with_ci, key=lambda r: r.check_in)
    return min(rows, key=lambda r: r.created_at or r.date)


def _first(rows, attr):
    for r in rows:
        v = getattr(r, attr)
        if v is not None and v != "":
            return v
    return None


async def main():
    print(f"DB: {engine.url.host}")
    print(f"MODE: {'APPLY — will merge and create the index' if APPLY else 'DRY RUN — no changes'}\n")

    async with AsyncSessionLocal() as db:
        groups = (await db.execute(
            select(Attendance.user_id, Attendance.date)
            .group_by(Attendance.user_id, Attendance.date)
            .having(func.count() > 1)
            .order_by(Attendance.date)
        )).all()

        print(f"duplicated (user_id, date) groups: {len(groups)}")
        merged = deleted = 0

        for uid, d in groups:
            rows = (await db.execute(
                select(Attendance)
                .where(Attendance.user_id == uid, Attendance.date == d)
                .order_by(Attendance.created_at)
            )).scalars().all()
            survivor = _pick_survivor(rows)
            losers = [r for r in rows if r.id != survivor.id]

            check_outs = [r.check_out for r in rows if r.check_out is not None]
            new_out = max(check_outs) if check_outs else None

            print(f"\n  {rows[0].username}  {d}   ({len(rows)} rows -> 1)")
            for r in rows:
                mark = "KEEP  " if r.id == survivor.id else "DELETE"
                print(f"    {mark} id={str(r.id)[:8]} in={r.check_in} out={r.check_out} "
                      f"status={r.status} notes={r.notes!r} marked_by={r.marked_by}")
            print(f"    AFTER  id={str(survivor.id)[:8]} in={survivor.check_in} out={new_out} "
                  f"status={survivor.status}")

            if APPLY:
                survivor.check_out = new_out
                survivor.check_in_ip = survivor.check_in_ip or _first(rows, "check_in_ip")
                survivor.check_out_ip = survivor.check_out_ip or _first(rows, "check_out_ip")
                survivor.notes = survivor.notes or _first(rows, "notes")
                survivor.marked_by = survivor.marked_by or _first(rows, "marked_by")
                await db.execute(delete(Attendance).where(
                    Attendance.id.in_([r.id for r in losers])))
                merged += 1
                deleted += len(losers)

        if APPLY:
            await db.commit()
            print(f"\nmerged {merged} group(s), deleted {deleted} redundant row(s)")

            await db.execute(text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} "
                f"ON attendance (user_id, date)"))
            await db.commit()
            print(f"created unique index {INDEX_NAME} on attendance (user_id, date)")
        else:
            print("\ndry run — nothing written. Re-run with --apply to perform the merge.")

        # Post-state (accurate in both modes)
        left = (await db.execute(
            select(func.count()).select_from(
                select(Attendance.user_id, Attendance.date)
                .group_by(Attendance.user_id, Attendance.date)
                .having(func.count() > 1).subquery())
        )).scalar()
        idx = (await db.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename='attendance'"))).scalars().all()
        total = (await db.execute(select(func.count()).select_from(Attendance))).scalar()
        print(f"\nattendance rows: {total}   duplicate groups remaining: {left}")
        print(f"indexes: {', '.join(sorted(idx))}")

asyncio.run(main())
