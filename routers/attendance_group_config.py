"""Attendance Config (Application Settings) — admin sets up groups of users
with a designated manager. That manager can then view /attendance/report
scoped to just their group's members (see routers/attendance.py)."""
import uuid
from templates_config import templates
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models.user import User, UserRole
from models.attendance_group import AttendanceGroup, AttendanceGroupMember
from auth.dependencies import require_roles, verify_csrf
from services.audit_engine import audit

router = APIRouter(prefix="/admin/attendance-config", tags=["attendance_config"],
                   dependencies=[Depends(verify_csrf)])
admin_only = require_roles(UserRole.admin)


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

    return templates.TemplateResponse("admin/attendance_config.html", {
        "request": request, "current_user": current_user,
        "groups": groups, "users": users, "member_map": member_map,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


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
