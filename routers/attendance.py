from templates_config import templates
from datetime import datetime, date, timedelta
from utils.timezone import app_now
import calendar
import io
import csv

from fastapi import APIRouter, Depends, Form, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, extract, text
from database import get_db
from models.attendance import Attendance
from models.user import User, UserRole
from models.attendance_group import AttendanceGroup, AttendanceGroupMember
from auth.dependencies import get_current_user, require_roles, verify_csrf

router = APIRouter(prefix="/attendance", tags=["attendance"], dependencies=[Depends(verify_csrf)])

ADMIN_ROLES = (UserRole.admin, UserRole.inventory_manager)


def _is_privileged(user: User) -> bool:
    return user.role in (UserRole.admin, UserRole.inventory_manager)


async def _day_record(db: AsyncSession, user_id, target_date: date):
    """The attendance row for one user on one date.

    There is no unique constraint on (user_id, date), and a double-submitted
    Check In used to insert two rows (both requests missed the existing-row
    check before either committed). scalar_one_or_none() then raised
    MultipleResultsFound on that user's day — which is what surfaced as a 500
    on My Attendance and on the Check In button itself.

    _lock_attendance_day below stops new duplicates. This picks a row
    deterministically so days that already have one degrade to "shows the
    first check-in" instead of erroring. nullslast keeps a real check-in ahead
    of an admin-created blank row for the same day.
    """
    return (await db.execute(
        select(Attendance)
        .where(Attendance.user_id == user_id, Attendance.date == target_date)
        .order_by(Attendance.check_in.asc().nullslast(), Attendance.created_at.asc())
    )).scalars().first()


async def _lock_attendance_day(db: AsyncSession, user_id, target_date: date):
    """Serialize check-in/check-out for one user+date across all workers.

    Transaction-scoped, so it releases on commit. Used instead of a unique
    constraint because adding one would first require deleting the duplicate
    rows already in production.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k)::bigint)"),
        {"k": f"attendance:{user_id}:{target_date.isoformat()}"},
    )


async def _attendance_report_scope(db: AsyncSession, current_user: User):
    """Returns (allowed, member_usernames) for /attendance/report access.
    Admin -> (True, None) sees everyone. A user configured as an Attendance
    Group manager (Application Settings -> Attendance Config) -> (True, [...])
    scoped to just that group's members. Anyone else -> (False, None)."""
    role_val = getattr(current_user.role, "value", None) or str(current_user.role)
    if role_val == "admin":
        return True, None
    groups = (await db.execute(
        select(AttendanceGroup).where(
            AttendanceGroup.manager_username == current_user.username,
            AttendanceGroup.is_active == True,
        )
    )).scalars().all()
    if not groups:
        return False, None
    group_ids = [g.id for g in groups]
    member_rows = (await db.execute(
        select(AttendanceGroupMember.username).where(AttendanceGroupMember.group_id.in_(group_ids))
    )).scalars().all()
    return True, list(set(member_rows))


# ---------------------------------------------------------------------------
# GET /attendance/api/status  – JSON: has current user checked in today?
# ---------------------------------------------------------------------------
@router.get("/api/status")
async def api_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = app_now().date()
    record = await _day_record(db, current_user.id, today)
    if record is None:
        return JSONResponse({
            "checked_in": False,
            "checked_out": False,
            "check_in_time": None,
            "check_out_time": None,
            "status": None,
        })
    return JSONResponse({
        "checked_in": record.check_in is not None,
        "checked_out": record.check_out is not None,
        "check_in_time": record.check_in.strftime("%H:%M") if record.check_in else None,
        "check_out_time": record.check_out.strftime("%H:%M") if record.check_out else None,
        "status": record.status,
    })


# ---------------------------------------------------------------------------
# GET /attendance  – today's attendance list
# ---------------------------------------------------------------------------
@router.get("", response_class=HTMLResponse)
async def attendance_index(
    request: Request,
    view_date: str = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if view_date:
        try:
            target_date = date.fromisoformat(view_date)
        except ValueError:
            target_date = app_now().date()
    else:
        target_date = app_now().date()

    # Own record for the target date (drives check-in/out buttons)
    own_record = await _day_record(db, current_user.id, target_date)

    # Table rows
    if _is_privileged(current_user):
        rows_result = await db.execute(
            select(Attendance)
            .where(Attendance.date == target_date)
            .order_by(Attendance.check_in.asc().nullslast())
        )
    else:
        rows_result = await db.execute(
            select(Attendance).where(
                Attendance.user_id == current_user.id,
                Attendance.date == target_date,
            )
        )
    records = rows_result.scalars().all()

    # Role per user_id, for the privileged table's "Role" column
    role_map = {}
    user_ids = {r.user_id for r in records if r.user_id}
    if user_ids:
        role_rows = (await db.execute(
            select(User.id, User.role).where(User.id.in_(user_ids))
        )).all()
        role_map = {str(uid): role for uid, role in role_rows}

    # Active user list for admin "mark attendance" modal
    users = []
    if _is_privileged(current_user):
        users_result = await db.execute(
            select(User).where(User.status == True).order_by(User.full_name)
        )
        users = users_result.scalars().all()

    duration_map = {str(r.id): compute_duration(r.check_in, r.check_out, r.date)[1] for r in records}
    own_duration = compute_duration(own_record.check_in, own_record.check_out, own_record.date)[1] if own_record else None

    today = app_now().date()
    return templates.TemplateResponse(
        "attendance/index.html",
        {
            "request": request,
            "current_user": current_user,
            "target_date": target_date,
            "today": today,
            "own_record": own_record,
            "own_duration": own_duration,
            "records": records,
            "duration_map": duration_map,
            "role_map": role_map,
            "users": users,
            "is_privileged": _is_privileged(current_user),
            "status_choices": ["present", "absent", "half_day", "late", "wfh"],
        },
    )


# ---------------------------------------------------------------------------
# POST /attendance/checkin
# ---------------------------------------------------------------------------
# Check-in time thresholds (app-local time, i.e. app_now() — already IST per
# utils/timezone.app_now, no additional UTC offset needed).
CHECKIN_LATE_MINUTES = 10 * 60        # after 10:00 AM -> late
CHECKIN_HALF_DAY_MINUTES = 13 * 60    # after 1:00 PM -> half_day
CHECKIN_ABSENT_MINUTES = 14 * 60      # after 2:00 PM -> absent
DUTY_CUTOFF_HOUR = 19                 # 7:00 PM — end of day for duration calc


def _checkin_status(now: datetime, mode: str) -> str:
    """Base status from the Check In modal choice (In-Office -> present,
    Work From Home -> wfh), overridden by how late the check-in was."""
    base_status = "wfh" if mode == "wfh" else "present"
    minutes = now.hour * 60 + now.minute
    if minutes > CHECKIN_ABSENT_MINUTES:
        return "absent"
    if minutes > CHECKIN_HALF_DAY_MINUTES:
        return "half_day"
    if minutes > CHECKIN_LATE_MINUTES:
        return "late"
    return base_status


def duty_cutoff_for(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time()).replace(hour=DUTY_CUTOFF_HOUR)


def compute_duration(check_in: datetime | None, check_out: datetime | None, d: date):
    """Total hours = check-in time to checkout time or the 7 PM cutoff,
    whichever is earlier (or 'In progress' if neither checkout nor cutoff
    has passed yet)."""
    if not check_in:
        return None, "-"
    cutoff = duty_cutoff_for(d)
    if check_out:
        end = min(check_out, cutoff)
    elif app_now() >= cutoff:
        end = cutoff
    else:
        return None, "In progress"
    hours = (end - check_in).total_seconds() / 3600
    return hours, f"{hours:.1f}h"


@router.post("/checkin")
async def checkin(
    request: Request,
    mode: str = Form(default="in_office"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = app_now().date()
    # Take the lock before reading: a second submit now waits here until the
    # first has committed, so it sees the row and is rejected below instead of
    # inserting a duplicate.
    await _lock_attendance_day(db, current_user.id, today)
    existing = await _day_record(db, current_user.id, today)

    if existing and existing.check_in is not None:
        return RedirectResponse(
            url="/attendance?error=Already+checked+in+today", status_code=302
        )

    now = app_now()
    status = _checkin_status(now, mode)
    client_ip = request.client.host if request.client else "unknown"

    if existing:
        # Record existed but check_in was None (admin pre-created absent record)
        existing.check_in = now
        existing.check_in_ip = client_ip
        existing.status = status
    else:
        record = Attendance(
            user_id=current_user.id,
            username=current_user.username,
            full_name=current_user.full_name,
            date=today,
            check_in=now,
            check_in_ip=client_ip,
            status=status,
        )
        db.add(record)

    await db.commit()
    return RedirectResponse(
        url="/attendance?success=Checked+in+successfully", status_code=302
    )


# ---------------------------------------------------------------------------
# POST /attendance/checkout
# ---------------------------------------------------------------------------
@router.post("/checkout")
async def checkout(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = app_now().date()
    await _lock_attendance_day(db, current_user.id, today)
    record = await _day_record(db, current_user.id, today)

    if not record or record.check_in is None:
        return RedirectResponse(
            url="/attendance?error=You+must+check+in+before+checking+out",
            status_code=302,
        )
    if record.check_out is not None:
        return RedirectResponse(
            url="/attendance?error=Already+checked+out+today", status_code=302
        )

    now = app_now()
    record.check_out = now
    record.check_out_ip = request.client.host if request.client else "unknown"
    # Status (present/wfh/late/half_day/absent) is fully determined at
    # check-in time per the configured thresholds — not re-derived here.

    await db.commit()
    return RedirectResponse(
        url="/attendance?success=Checked+out+successfully", status_code=302
    )


# ---------------------------------------------------------------------------
# GET /attendance/history  – calendar view
# ---------------------------------------------------------------------------
@router.get("/history", response_class=HTMLResponse)
async def history(
    request: Request,
    month: int = Query(default=None),
    year: int = Query(default=None),
    user_id: str = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = app_now().date()
    if not month:
        month = today.month
    if not year:
        year = today.year

    # Clamp month/year
    month = max(1, min(12, month))

    # Resolve target user
    if _is_privileged(current_user) and user_id:
        u_result = await db.execute(select(User).where(User.id == user_id))
        target_user = u_result.scalar_one_or_none() or current_user
    else:
        target_user = current_user

    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    rows_result = await db.execute(
        select(Attendance).where(
            Attendance.user_id == target_user.id,
            Attendance.date >= first_day,
            Attendance.date <= last_day,
        )
    )
    records = rows_result.scalars().all()
    day_map = {r.date.day: r for r in records}

    # Summary counts
    counts = {"present": 0, "absent": 0, "late": 0, "wfh": 0, "half_day": 0}
    for r in records:
        if r.status in counts:
            counts[r.status] += 1

    # Calendar grid (ISO week: Mon=0 ... Sun=6)
    cal = calendar.monthcalendar(year, month)
    weeks = []
    for week in cal:
        row = []
        for day in week:
            row.append((day, day_map.get(day) if day != 0 else None))
        weeks.append(row)

    # Nav months
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    # Users for admin selector
    users = []
    if _is_privileged(current_user):
        u_res = await db.execute(
            select(User).where(User.status == True).order_by(User.full_name)
        )
        users = u_res.scalars().all()

    return templates.TemplateResponse(
        "attendance/history.html",
        {
            "request": request,
            "current_user": current_user,
            "target_user": target_user,
            "month": month,
            "year": year,
            "month_name": calendar.month_name[month],
            "weeks": weeks,
            "day_names": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "counts": counts,
            "today": today,
            "users": users,
            "is_privileged": _is_privileged(current_user),
            "prev_month": prev_month,
            "prev_year": prev_year,
            "next_month": next_month,
            "next_year": next_year,
            "user_id_param": str(target_user.id),
            "total_working_days": last_day.day,
        },
    )


# ---------------------------------------------------------------------------
# GET /attendance/report  – admin, or a user configured as an Attendance
# Group manager (Application Settings -> Attendance Config), scoped to their
# group's members only.
# ---------------------------------------------------------------------------
@router.get("/report", response_class=HTMLResponse)
async def report(
    request: Request,
    date_from: str = Query(default=None),
    date_to: str = Query(default=None),
    user_id: str = Query(default=None),
    status_filter: str = Query(default=None),
    export: str = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    allowed, scope_usernames = await _attendance_report_scope(db, current_user)
    if not allowed:
        raise HTTPException(status_code=403, detail="Access denied")

    today = app_now().date()

    # Default view is today only — older history is opt-in via the date
    # range filter (previously defaulted to month-to-date).
    if not date_from:
        date_from = today.isoformat()
    if not date_to:
        date_to = today.isoformat()

    try:
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
    except ValueError:
        d_from = today
        d_to = today
        date_from = d_from.isoformat()
        date_to = d_to.isoformat()

    filters = [
        Attendance.date >= d_from,
        Attendance.date <= d_to,
    ]
    if scope_usernames is not None:
        # Group manager — restrict to just their group's members (empty group
        # means the manager sees nothing rather than everyone).
        filters.append(Attendance.username.in_(scope_usernames) if scope_usernames else Attendance.id.is_(None))
    if user_id:
        filters.append(Attendance.user_id == user_id)
    if status_filter:
        filters.append(Attendance.status == status_filter)

    rows_result = await db.execute(
        select(Attendance)
        .where(and_(*filters))
        .order_by(Attendance.date.desc(), Attendance.username)
    )
    records = rows_result.scalars().all()

    # Enrich with duration — checked-in time to checkout time or the 7 PM
    # duty cutoff, whichever is earlier.
    report_rows = []
    total_hours = 0.0
    for r in records:
        dur_h, duration_str = compute_duration(r.check_in, r.check_out, r.date)
        if dur_h is not None:
            total_hours += dur_h
        report_rows.append({"record": r, "duration": duration_str})

    # Status summary
    summary = {}
    for r in records:
        summary[r.status] = summary.get(r.status, 0) + 1

    # CSV export
    if export == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Date", "Username", "Full Name",
            "Check In (UTC)", "Check Out (UTC)",
            "Duration", "Status", "Notes", "Marked By",
        ])
        for row in report_rows:
            r = row["record"]
            writer.writerow([
                r.date.isoformat(),
                r.username,
                r.full_name or "",
                r.check_in.strftime("%H:%M") if r.check_in else "",
                r.check_out.strftime("%H:%M") if r.check_out else "",
                row["duration"],
                r.status,
                r.notes or "",
                r.marked_by or "",
            ])
        output.seek(0)
        filename = f"attendance_{d_from}_{d_to}.csv"
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    # Users for filter dropdown — scoped to the group's members for a group
    # manager, all active users for admin.
    user_filters = [User.status == True]
    if scope_usernames is not None:
        user_filters.append(User.username.in_(scope_usernames) if scope_usernames else User.id.is_(None))
    u_res = await db.execute(
        select(User).where(*user_filters).order_by(User.full_name)
    )
    users = u_res.scalars().all()

    # Role per user_id, for the report's "Role" column
    role_map = {}
    user_ids = {r.user_id for r in records if r.user_id}
    if user_ids:
        role_rows = (await db.execute(
            select(User.id, User.role).where(User.id.in_(user_ids))
        )).all()
        role_map = {str(uid): role for uid, role in role_rows}

    return templates.TemplateResponse(
        "attendance/report.html",
        {
            "request": request,
            "current_user": current_user,
            "report_rows": report_rows,
            "summary": summary,
            "date_from": date_from,
            "date_to": date_to,
            "user_id": user_id or "",
            "status_filter": status_filter or "",
            "users": users,
            "role_map": role_map,
            "status_choices": ["present", "absent", "half_day", "late", "wfh"],
            "total": len(records),
            "total_hours": round(total_hours, 1),
        },
    )


# ---------------------------------------------------------------------------
# POST /attendance/mark  – admin / inventory_manager marks attendance manually
# ---------------------------------------------------------------------------
@router.post("/mark")
async def mark_attendance(
    request: Request,
    user_id: str = Form(...),
    mark_date: str = Form(...),
    status: str = Form(...),
    check_in_time: str = Form(default=None),
    check_out_time: str = Form(default=None),
    notes: str = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(*ADMIN_ROLES)),
):
    try:
        target_date = date.fromisoformat(mark_date)
    except ValueError:
        return RedirectResponse(url="/attendance?error=Invalid+date", status_code=302)

    u_res = await db.execute(select(User).where(User.id == user_id))
    target_user = u_res.scalar_one_or_none()
    if not target_user:
        return RedirectResponse(url="/attendance?error=User+not+found", status_code=302)

    await _lock_attendance_day(db, target_user.id, target_date)
    record = await _day_record(db, target_user.id, target_date)

    def parse_time(time_str, ref_date):
        if not time_str:
            return None
        try:
            h, m = map(int, time_str.strip().split(":"))
            return datetime(ref_date.year, ref_date.month, ref_date.day, h, m)
        except (ValueError, AttributeError):
            return None

    check_in_dt = parse_time(check_in_time, target_date)
    check_out_dt = parse_time(check_out_time, target_date)

    if record:
        record.status = status
        if check_in_dt is not None:
            record.check_in = check_in_dt
        if check_out_dt is not None:
            record.check_out = check_out_dt
        record.notes = notes
        record.marked_by = current_user.username
    else:
        record = Attendance(
            user_id=target_user.id,
            username=target_user.username,
            full_name=target_user.full_name,
            date=target_date,
            check_in=check_in_dt,
            check_out=check_out_dt,
            status=status,
            notes=notes,
            marked_by=current_user.username,
        )
        db.add(record)

    await db.commit()

    name_encoded = (target_user.full_name or target_user.username).replace(" ", "+")
    return RedirectResponse(
        url=f"/attendance?success=Attendance+marked+for+{name_encoded}&view_date={mark_date}",
        status_code=302,
    )
