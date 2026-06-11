from templates_config import templates
from datetime import datetime, date, timedelta
from utils.timezone import app_now
import calendar
import io
import csv

from fastapi import APIRouter, Depends, Form, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, extract
from database import get_db
from models.attendance import Attendance
from models.user import User, UserRole
from auth.dependencies import get_current_user, require_roles, verify_csrf

router = APIRouter(prefix="/attendance", tags=["attendance"], dependencies=[Depends(verify_csrf)])

ADMIN_ROLES = (UserRole.admin, UserRole.inventory_manager)


def _is_privileged(user: User) -> bool:
    return user.role in (UserRole.admin, UserRole.inventory_manager)


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
    result = await db.execute(
        select(Attendance).where(
            Attendance.user_id == current_user.id,
            Attendance.date == today,
        )
    )
    record = result.scalar_one_or_none()
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
    own_result = await db.execute(
        select(Attendance).where(
            Attendance.user_id == current_user.id,
            Attendance.date == target_date,
        )
    )
    own_record = own_result.scalar_one_or_none()

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

    # Active user list for admin "mark attendance" modal
    users = []
    if _is_privileged(current_user):
        users_result = await db.execute(
            select(User).where(User.status == True).order_by(User.full_name)
        )
        users = users_result.scalars().all()

    today = app_now().date()
    return templates.TemplateResponse(
        "attendance/index.html",
        {
            "request": request,
            "current_user": current_user,
            "target_date": target_date,
            "today": today,
            "own_record": own_record,
            "records": records,
            "users": users,
            "is_privileged": _is_privileged(current_user),
            "status_choices": ["present", "absent", "half_day", "late", "wfh"],
        },
    )


# ---------------------------------------------------------------------------
# POST /attendance/checkin
# ---------------------------------------------------------------------------
@router.post("/checkin")
async def checkin(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = app_now().date()
    result = await db.execute(
        select(Attendance).where(
            Attendance.user_id == current_user.id,
            Attendance.date == today,
        )
    )
    existing = result.scalar_one_or_none()

    if existing and existing.check_in is not None:
        return RedirectResponse(
            url="/attendance?error=Already+checked+in+today", status_code=302
        )

    now = app_now()

    # Determine late status using IST (UTC+5:30)
    ist_offset_minutes = 330
    ist_now = now + timedelta(minutes=ist_offset_minutes)
    if ist_now.hour > 9 or (ist_now.hour == 9 and ist_now.minute > 30):
        status = "late"
    else:
        status = "present"

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
    result = await db.execute(
        select(Attendance).where(
            Attendance.user_id == current_user.id,
            Attendance.date == today,
        )
    )
    record = result.scalar_one_or_none()

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

    # Half day if worked less than 4.5 hours (unless WFH)
    if record.status not in ("wfh", "absent"):
        duration_h = (now - record.check_in).total_seconds() / 3600
        if duration_h < 4.5:
            record.status = "half_day"

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
# GET /attendance/report  – admin only
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
    current_user: User = Depends(require_roles(UserRole.admin)),
):
    today = app_now().date()

    if not date_from:
        date_from = date(today.year, today.month, 1).isoformat()
    if not date_to:
        date_to = today.isoformat()

    try:
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
    except ValueError:
        d_from = date(today.year, today.month, 1)
        d_to = today
        date_from = d_from.isoformat()
        date_to = d_to.isoformat()

    filters = [
        Attendance.date >= d_from,
        Attendance.date <= d_to,
    ]
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

    # Enrich with duration
    report_rows = []
    total_hours = 0.0
    for r in records:
        if r.check_in and r.check_out:
            dur_h = (r.check_out - r.check_in).total_seconds() / 3600
            total_hours += dur_h
            duration_str = f"{dur_h:.1f}h"
        elif r.check_in:
            duration_str = "In progress"
        else:
            duration_str = "-"
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

    # Users for filter dropdown
    u_res = await db.execute(
        select(User).where(User.status == True).order_by(User.full_name)
    )
    users = u_res.scalars().all()

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

    r_res = await db.execute(
        select(Attendance).where(
            Attendance.user_id == target_user.id,
            Attendance.date == target_date,
        )
    )
    record = r_res.scalar_one_or_none()

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
