"""
Stage Control Admin Router
Admin can view / add / remove allowed stage transitions.
Also provides the aging dashboard.
"""
from templates_config import templates
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from models.user import User, UserRole
from models.device import DeviceStage
from models.stage_control import StageMaster, AllowedTransition
from models.engines import DeviceAging, AuditLog, DeviceCosting
from models.device import Device
from auth.dependencies import get_current_user, require_roles, verify_csrf
from services.aging_tracker import refresh_aging
from services.control_engine import invalidate_transitions_cache

router = APIRouter(prefix="/stage-control", tags=["stage_control"], dependencies=[Depends(verify_csrf)])
admin_only = require_roles(UserRole.admin)


@router.get("", response_class=HTMLResponse)
async def stage_control_index(request: Request,
                               db: AsyncSession = Depends(get_db),
                               current_user: User = Depends(admin_only)):
    stages_result = await db.execute(
        select(StageMaster).order_by(StageMaster.sequence)
    )
    stages = stages_result.scalars().all()

    trans_result = await db.execute(
        select(AllowedTransition).order_by(
            AllowedTransition.from_stage, AllowedTransition.to_stage
        )
    )
    transitions = trans_result.scalars().all()

    return templates.TemplateResponse("stage_control/index.html", {
        "request": request, "stages": stages, "transitions": transitions,
        "current_user": current_user,
    })


@router.post("/transition/add")
async def add_transition(
    request: Request,
    from_stage: str = Form(...),
    to_stage: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    # Check it doesn't exist
    existing = await db.execute(
        select(AllowedTransition).where(
            AllowedTransition.from_stage == from_stage,
            AllowedTransition.to_stage   == to_stage,
        )
    )
    if existing.scalar_one_or_none():
        return RedirectResponse(url="/stage-control?error=Transition+already+exists", status_code=302)

    db.add(AllowedTransition(from_stage=from_stage, to_stage=to_stage))
    db.add(AuditLog(username=current_user.username, action="TRANSITION_ADDED",
                    table_name="allowed_transitions",
                    notes=f"{from_stage} -> {to_stage}"))
    await db.commit()
    invalidate_transitions_cache()
    return RedirectResponse(url="/stage-control?success=Transition+added", status_code=302)


@router.post("/transition/remove")
async def remove_transition(
    request: Request,
    transition_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    result = await db.execute(
        select(AllowedTransition).where(AllowedTransition.id == transition_id)
    )
    transition = result.scalar_one_or_none()
    if not transition:
        raise HTTPException(404)
    db.add(AuditLog(username=current_user.username, action="TRANSITION_REMOVED",
                    table_name="allowed_transitions",
                    notes=f"{transition.from_stage} -> {transition.to_stage}"))
    await db.delete(transition)
    await db.commit()
    invalidate_transitions_cache()
    return RedirectResponse(url="/stage-control?success=Transition+removed", status_code=302)


@router.get("/aging", response_class=HTMLResponse)
async def aging_dashboard(request: Request,
                           db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    # Stuck devices (days_in_stage > 30)
    stuck_result = await db.execute(
        select(DeviceAging, Device.barcode, Device.brand, Device.model,
               Device.current_stage, Device.grade)
        .join(Device, DeviceAging.device_id == Device.id)
        .where(DeviceAging.is_stuck == True)
        .order_by(DeviceAging.days_in_stage.desc())
    )
    stuck = stuck_result.all()

    # Dead stock (total_days > 90)
    dead_result = await db.execute(
        select(DeviceAging, Device.barcode, Device.brand, Device.model,
               Device.current_stage, Device.grade)
        .join(Device, DeviceAging.device_id == Device.id)
        .where(DeviceAging.is_dead_stock == True)
        .order_by(DeviceAging.total_days.desc())
    )
    dead_stock = dead_result.all()

    # Cost warnings (total_cost > 70% of expected_sale_value)
    cost_result = await db.execute(
        select(DeviceCosting, Device.barcode, Device.brand, Device.model)
        .join(Device, DeviceCosting.device_id == Device.id)
        .where(DeviceCosting.expected_sale_value != None,
               DeviceCosting.total_cost > DeviceCosting.expected_sale_value * 0.7)
    )
    cost_warnings = cost_result.all()

    return templates.TemplateResponse("stage_control/aging.html", {
        "request": request, "stuck": stuck, "dead_stock": dead_stock,
        "cost_warnings": cost_warnings, "current_user": current_user,
    })


@router.post("/aging/refresh")
async def trigger_aging_refresh(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    summary = await refresh_aging(db)
    import urllib.parse
    msg = f"Aging refreshed: {summary['updated']} devices, {summary['stuck']} stuck, {summary['dead_stock']} dead stock"
    return RedirectResponse(url=f"/stage-control/aging?success={urllib.parse.quote(msg)}", status_code=302)


@router.get("/audit", response_class=HTMLResponse)
async def audit_log_view(request: Request, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(admin_only)):
    result = await db.execute(
        select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(500)
    )
    logs = result.scalars().all()
    return templates.TemplateResponse("stage_control/audit.html", {
        "request": request, "logs": logs, "current_user": current_user,
    })
