"""Attendance Config (Application Settings) — admin sets up groups of users
with a designated manager. That manager can then view /attendance/report
scoped to just their group's members (see routers/attendance.py). Also the
sole place that sets Application Timezone (moved here from the Company
Setting page — that page can now hold multiple company profiles instead)."""
import uuid
from templates_config import templates
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models.user import User, UserRole
from models.settings import AppSetting
from models.attendance_group import AttendanceGroup, AttendanceGroupMember
from auth.dependencies import require_roles, verify_csrf
from services.audit_engine import audit
from utils.timezone import set_app_timezone

router = APIRouter(prefix="/admin/attendance-config", tags=["attendance_config"],
                   dependencies=[Depends(verify_csrf)])
admin_only = require_roles(UserRole.admin)

TZ_OPTIONS = [
    ("Asia/Kolkata",   "Asia/Kolkata — IST (UTC+5:30)"),
    ("Asia/Colombo",   "Asia/Colombo — Sri Lanka (UTC+5:30)"),
    ("Asia/Kathmandu", "Asia/Kathmandu — Nepal (UTC+5:45)"),
    ("Asia/Dubai",     "Asia/Dubai — GST (UTC+4:00)"),
    ("Asia/Singapore", "Asia/Singapore — SGT (UTC+8:00)"),
    ("Asia/Bangkok",   "Asia/Bangkok — ICT (UTC+7:00)"),
    ("UTC",            "UTC — Coordinated Universal Time"),
    ("US/Eastern",     "US/Eastern — EST/EDT"),
    ("Europe/London",  "Europe/London — GMT/BST"),
]


@router.get("", response_class=HTMLResponse)
async def attendance_config_list(request: Request, db: AsyncSession = Depends(get_db),
                                 current_user: User = Depends(admin_only)):
    groups = (await db.execute(
        select(AttendanceGroup).where(AttendanceGroup.is_active == True)
        .order_by(AttendanceGroup.name)
    )).scalars().all()

    users = (await db.execute(
        select(User).where(User.status == True).order_by(User.full_name)
    )).scalars().all()

    member_map = {}
    for g in groups:
        rows = (await db.execute(
            select(AttendanceGroupMember).where(AttendanceGroupMember.group_id == g.id)
        )).scalars().all()
        member_map[str(g.id)] = [r.username for r in rows]

    tz_row = await db.get(AppSetting, "app_timezone")
    current_tz = (tz_row.value if tz_row and tz_row.value else "Asia/Kolkata")

    return templates.TemplateResponse("admin/attendance_config.html", {
        "request": request, "current_user": current_user,
        "groups": groups, "users": users, "member_map": member_map,
        "tz_options": TZ_OPTIONS, "current_tz": current_tz,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@router.post("/timezone")
async def save_timezone(
    request: Request,
    app_timezone: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    tz_val = app_timezone.strip() or "Asia/Kolkata"
    existing = await db.get(AppSetting, "app_timezone")
    if existing:
        existing.value = tz_val
        existing.updated_by = current_user.username
    else:
        db.add(AppSetting(key="app_timezone", value=tz_val,
                          description="Application Timezone", updated_by=current_user.username))
    await db.commit()
    set_app_timezone(tz_val)
    return RedirectResponse(url="/admin/attendance-config?success=Timezone+updated", status_code=302)


@router.post("/create")
async def create_group(
    request: Request,
    name: str = Form(...),
    manager_username: str = Form(...),
    members: list[str] = Form(default=[]),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    name = name.strip()
    if not name:
        return RedirectResponse(url="/admin/attendance-config?error=Group+name+required", status_code=302)
    existing = (await db.execute(select(AttendanceGroup).where(AttendanceGroup.name == name))).scalar_one_or_none()
    if existing:
        return RedirectResponse(url="/admin/attendance-config?error=Group+name+already+exists", status_code=302)

    group = AttendanceGroup(name=name, manager_username=manager_username.strip(),
                            created_by=current_user.username)
    db.add(group)
    await db.flush()
    for uname in {m.strip() for m in members if m and m.strip()}:
        db.add(AttendanceGroupMember(group_id=group.id, username=uname))

    await audit(db, action="ATTENDANCE_GROUP_CREATE", user=current_user,
                table_name="attendance_groups", record_id=str(group.id))
    await db.commit()
    return RedirectResponse(url="/admin/attendance-config?success=Group+created", status_code=302)


@router.post("/{group_id}/update")
async def update_group(
    group_id: str,
    request: Request,
    name: str = Form(...),
    manager_username: str = Form(...),
    members: list[str] = Form(default=[]),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    try:
        gid = uuid.UUID(group_id)
    except ValueError:
        raise HTTPException(404, "Group not found")
    group = (await db.execute(select(AttendanceGroup).where(AttendanceGroup.id == gid))).scalar_one_or_none()
    if not group:
        raise HTTPException(404, "Group not found")

    group.name = name.strip()
    group.manager_username = manager_username.strip()

    old_members = (await db.execute(
        select(AttendanceGroupMember).where(AttendanceGroupMember.group_id == gid)
    )).scalars().all()
    for m in old_members:
        await db.delete(m)
    for uname in {m.strip() for m in members if m and m.strip()}:
        db.add(AttendanceGroupMember(group_id=gid, username=uname))

    await audit(db, action="ATTENDANCE_GROUP_UPDATE", user=current_user,
                table_name="attendance_groups", record_id=str(gid))
    await db.commit()
    return RedirectResponse(url="/admin/attendance-config?success=Group+updated", status_code=302)


@router.post("/{group_id}/delete")
async def delete_group(group_id: str, request: Request,
                       db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(admin_only)):
    try:
        gid = uuid.UUID(group_id)
    except ValueError:
        raise HTTPException(404, "Group not found")
    group = (await db.execute(select(AttendanceGroup).where(AttendanceGroup.id == gid))).scalar_one_or_none()
    if not group:
        raise HTTPException(404, "Group not found")
    group.is_active = False
    await audit(db, action="ATTENDANCE_GROUP_DELETE", user=current_user,
                table_name="attendance_groups", record_id=str(gid))
    await db.commit()
    return RedirectResponse(url="/admin/attendance-config?success=Group+deleted", status_code=302)
