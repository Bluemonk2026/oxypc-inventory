"""
Repair Router - L1/L2/L3 with Control Engine, Cost Engine, Audit Engine, RepairAttempt
"""
from templates_config import templates
import uuid as uuid_module
from datetime import datetime
from utils.timezone import app_now
from decimal import Decimal
from fastapi import APIRouter, Depends, Form, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from models.location import DeviceLocationLog, StorageLocation

from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceStage, StageMovement
from models.lot import Lot
from models.repair import RepairJob, RepairStatus
from models.engines import RepairAttempt, DeviceCosting
from auth.dependencies import get_current_user, require_roles, verify_csrf
from models.role_permissions import has_perm
from services.control_engine import validate_transition, validate_repair_level, get_allowed_next_stages, assert_device_in_stage
from services.cost_engine import check_scrap_decision, auto_scrap_device, refresh_parts_cost, SCRAP_WARNING_RATIO
from services.audit_engine import audit
from models.spare_parts import SparePartConsumption as SPC, SparePart

router = APIRouter(prefix="/repair", tags=["repair"], dependencies=[Depends(verify_csrf)])

STAGE_MAP  = {"l1": DeviceStage.l1, "l2": DeviceStage.l2, "l3": DeviceStage.l3}
NEXT_STAGE = {DeviceStage.l1: DeviceStage.l2, DeviceStage.l2: DeviceStage.l3, DeviceStage.l3: DeviceStage.qc_check}
LEVEL_MAP  = {"l1": 1, "l2": 2, "l3": 3}


def stage_allowed(stage: str):
    role_map = {
        "l1": require_roles(UserRole.admin, UserRole.inventory_manager, UserRole.l1_engineer),
        "l2": require_roles(UserRole.admin, UserRole.inventory_manager, UserRole.l2_engineer),
        "l3": require_roles(UserRole.admin, UserRole.inventory_manager, UserRole.l3_engineer),
    }
    return role_map.get(stage, require_roles(UserRole.admin))


@router.get("/{stage}", response_class=HTMLResponse)
async def repair_list(stage: str, request: Request,
                      db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user),
                      page: int = Query(default=1, ge=1),
                      page_size: int = Query(default=50, ge=1, le=200)):
    if stage not in STAGE_MAP:
        raise HTTPException(404)
    device_stage = STAGE_MAP[stage]

    total_result = await db.execute(select(func.count()).select_from(
        select(Device.id)
        .where(Device.current_stage == device_stage, Device.is_active == True)
        .subquery()
    ))
    total = total_result.scalar() or 0
    total_pages = max(1, (total + page_size - 1) // page_size)

    result = await db.execute(
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.current_stage == device_stage, Device.is_active == True)
        .order_by(Device.updated_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    devices = result.all()
    jobs_result = await db.execute(
        select(RepairJob, Device.barcode, Device.brand, Device.model)
        .join(Device, RepairJob.device_id == Device.id)
        .where(RepairJob.stage == stage.upper(), RepairJob.status != RepairStatus.completed)
        .order_by(RepairJob.started_at.desc())
    )
    open_jobs = jobs_result.all()

    # Current location per device
    location_map = {}
    uuid_ids = [d.id for d, _ in devices]  # already UUID objects from SQLAlchemy
    if uuid_ids:
        sub = (
            select(DeviceLocationLog.device_id, func.max(DeviceLocationLog.logged_at).label("latest"))
            .group_by(DeviceLocationLog.device_id).subquery()
        )
        loc_rows = await db.execute(
            select(DeviceLocationLog.device_id, StorageLocation.unit_id, DeviceLocationLog.action)
            .join(sub, and_(DeviceLocationLog.device_id == sub.c.device_id,
                            DeviceLocationLog.logged_at == sub.c.latest))
            .outerjoin(StorageLocation, DeviceLocationLog.location_id == StorageLocation.id)
            .where(DeviceLocationLog.device_id.in_(uuid_ids))
        )
        for did, unit_id, action in loc_rows.all():
            location_map[str(did)] = {"unit_id": unit_id, "action": action.value if action else None}

    # ── Batch scrap-warning + suggest-QC (no N+1) ────────────────────────────
    device_ids = [d.id for d, _ in devices]
    scrap_warning_map: dict = {}
    suggest_qc_ids: set = set()

    if device_ids:
        costing_rows = (await db.execute(
            select(DeviceCosting).where(DeviceCosting.device_id.in_(device_ids))
        )).scalars().all()
        for costing in costing_rows:
            if (costing.expected_sale_value and costing.total_cost and
                    costing.total_cost >= costing.expected_sale_value * SCRAP_WARNING_RATIO):
                pct = int(costing.total_cost / costing.expected_sale_value * 100)
                scrap_warning_map[str(costing.device_id)] = (
                    f"Cost ₹{costing.total_cost:,.0f} is {pct}% of "
                    f"expected sale ₹{costing.expected_sale_value:,.0f} — consider scrapping"
                )

        open_device_ids = {str(j.device_id) for j, *_ in open_jobs}
        suggest_qc_ids = {str(did) for did in device_ids} - open_device_ids

    _parts_res = await db.execute(
        select(SparePart).where(SparePart.qty_in_stock > 0).order_by(SparePart.name)
    )
    available_parts = _parts_res.scalars().all()

    return templates.TemplateResponse(f"repair/{stage}.html", {
        "request": request, "devices": devices, "open_jobs": open_jobs,
        "stage": stage.upper(), "current_user": current_user,
        "location_map": location_map,
        "scrap_warning_map": scrap_warning_map,
        "suggest_qc_ids": suggest_qc_ids,
        "available_parts": available_parts,
        "page": page, "page_size": page_size,
        "total": total, "total_pages": total_pages,
    })


@router.post("/start")
async def start_repair(
    request: Request,
    barcode: str = Form(...),
    stage: str = Form(...),
    issue_description: str = Form(""),
    problem_reported: str = Form(""),
    team_name: str = Form(""),
    assigned_engineer: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Device).where(Device.barcode == barcode))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
    device_stage = STAGE_MAP.get(stage.lower())
    if not device_stage:
        raise HTTPException(400, "Invalid repair stage")
    assert_device_in_stage(device, device_stage)
    level    = LEVEL_MAP.get(stage.lower(), 1)
    is_admin = current_user.role.value == "admin"

    # Check permission for this repair level
    repair_module = f"repair_l{level}"
    if not has_perm(current_user.role.value, repair_module, "add"):
        raise HTTPException(403, f"You do not have permission to add {repair_module} repairs")

    await validate_repair_level(device, level, db)
    await validate_transition(device, device_stage, db, override_admin=is_admin)

    prev_stage = device.current_stage
    prev_mv = (await db.execute(
        select(StageMovement)
        .where(StageMovement.device_id == device.id,
               StageMovement.to_stage  == prev_stage,
               StageMovement.exited_at == None)
        .order_by(StageMovement.moved_at.desc())
    )).scalars().first()
    if prev_mv:
        prev_mv.exited_at = app_now()

    device.current_stage = device_stage
    device.updated_at    = app_now()
    db.add(StageMovement(device_id=device.id, from_stage=prev_stage, to_stage=device_stage,
                         moved_by=current_user.username, notes=f"Started {stage.upper()} repair"))
    db.add(RepairJob(device_id=device.id, stage=stage.upper(),
                     engineer_id=current_user.id, engineer_name=current_user.full_name,
                     issue_description=issue_description or None,
                     problem_reported=problem_reported or None,
                     team_name=team_name or None, assigned_engineer=assigned_engineer or None,
                     status=RepairStatus.in_progress))
    await audit(db, user=current_user, action="REPAIR_STARTED",
                table_name="repair_jobs", record_id=str(device.id),
                notes=f"{stage.upper()} started on {barcode}", request=request)
    await db.commit()
    return RedirectResponse(url=f"/repair/{stage.lower()}?success=Repair+started", status_code=302)


@router.post("/complete")
async def complete_repair(
    request: Request,
    job_id: str = Form(...),
    resolution: str = Form(""),
    move_to_next: str = Form("no"),
    final_status: str = Form(""),
    cost: str = Form("0"),
    time_spent: str = Form(""),
    dust_cleaning: str = Form(""),
    cmos_battery_change: str = Form(""),
    thermal_paste: str = Form(""),
    ram_status: str = Form(""),
    ram_removed_gb: str = Form(""),
    ram_added_gb: str = Form(""),
    hdd_updated: str = Form(""),
    hdd_removed: str = Form(""),
    hdd_added: str = Form(""),
    action_taken: str = Form(""),
    problem_reported: str = Form(""),
    problem_observed: str = Form(""),
    scrap_reason: str = Form(""),
    received_from: str = Form(""),
    customer_internal: str = Form(""),
    part_ids: list[str] = Form(default=[]),
    part_qtys: list[str] = Form(default=[]),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(RepairJob).where(RepairJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404)

    # Check permission to edit this repair level
    repair_module = f"repair_{job.stage}"
    if not has_perm(current_user.role.value, repair_module, "edit"):
        raise HTTPException(403, f"You do not have permission to edit {repair_module} repairs")

    job.status = RepairStatus.completed; job.completed_at = app_now()
    job.resolution = resolution or None; job.final_status = final_status or None
    job.dust_cleaning = dust_cleaning or None; job.cmos_battery_change = cmos_battery_change or None
    job.thermal_paste = thermal_paste or None; job.ram_status = ram_status or None
    job.ram_removed_gb = ram_removed_gb or None; job.ram_added_gb = ram_added_gb or None
    job.hdd_updated = hdd_updated or None; job.hdd_removed = hdd_removed or None
    job.hdd_added = hdd_added or None; job.action_taken = action_taken or None
    job.problem_reported = problem_reported or None; job.problem_observed = problem_observed or None
    job.scrap_reason = scrap_reason or None; job.received_from = received_from or None
    job.customer_internal = customer_internal or None

    stage = job.stage.lower()
    level = LEVEL_MAP.get(stage, 1)
    dev_result = await db.execute(select(Device).where(Device.id == job.device_id))
    device = dev_result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device for repair job not found")
    expected_stage = STAGE_MAP.get(stage)
    if expected_stage:
        assert_device_in_stage(device, expected_stage)

    prev_att = (await db.execute(
        select(RepairAttempt).where(RepairAttempt.device_id == device.id, RepairAttempt.level == level)
    )).scalars().all()
    attempt_no  = len(prev_att) + 1
    repair_cost = Decimal(cost) if cost and cost.strip() else Decimal("0")
    time_mins   = int(time_spent) if time_spent and time_spent.strip() else None
    outcome     = ("scrapped" if final_status == "Scrap" else
                   "resolved" if move_to_next == "yes" else "escalated")

    db.add(RepairAttempt(device_id=device.id, repair_job_id=job.id, level=level,
                         attempt_no=attempt_no, cost=repair_cost, time_spent=time_mins,
                         outcome=outcome, notes=resolution or None, created_by=current_user.username))
    await refresh_parts_cost(device, db)  # keep DeviceCosting.labour_cost current

    scrap_result = await check_scrap_decision(device, db, current_user.username)
    force_scrap  = scrap_result["scrap"]
    warn_msg     = scrap_result.get("reason", "") if scrap_result.get("warning") else ""

    if final_status == "Scrap" or force_scrap:
        reason = scrap_reason or scrap_result.get("reason", "Scrapped")
        prev_mv = (await db.execute(
            select(StageMovement)
            .where(StageMovement.device_id == device.id,
                   StageMovement.to_stage  == device.current_stage,
                   StageMovement.exited_at == None)
            .order_by(StageMovement.moved_at.desc())
        )).scalars().first()
        if prev_mv:
            prev_mv.exited_at = app_now()
        await auto_scrap_device(device, reason, db, current_user.username)
        await audit(db, user=current_user,
                    action="AUTO_SCRAP" if force_scrap else "MANUAL_SCRAP",
                    table_name="devices", record_id=str(device.id), notes=reason, request=request)

    elif final_status in ("Escalate to L3", "Escalate to L2") and device:
        from sqlalchemy import update as sa_update
        escalate_to = DeviceStage.l3 if "L3" in final_status else DeviceStage.l2
        is_admin    = current_user.role.value == "admin"
        current     = device.current_stage
        await validate_transition(device, escalate_to, db, override_admin=is_admin)
        prev_mv = (await db.execute(
            select(StageMovement)
            .where(StageMovement.device_id == device.id,
                   StageMovement.to_stage  == current,
                   StageMovement.exited_at == None)
            .order_by(StageMovement.moved_at.desc())
        )).scalars().first()
        if prev_mv:
            prev_mv.exited_at = app_now()
        # Close any other open repair jobs at this stage
        await db.execute(
            sa_update(RepairJob)
            .where(RepairJob.device_id == device.id,
                   RepairJob.stage     == job.stage,
                   RepairJob.status    == RepairStatus.in_progress)
            .values(status=RepairStatus.completed, completed_at=app_now())
        )
        db.add(StageMovement(device_id=device.id, from_stage=current, to_stage=escalate_to,
                             moved_by=current_user.username,
                             notes=f"{job.stage} escalated — {final_status}"))
        device.current_stage = escalate_to
        device.updated_at    = app_now()

    elif final_status == "PNA" and device:
        # Parts Not Available — keep device in current stage; job status already saved above
        await audit(db, user=current_user, action="REPAIR_PNA",
                    table_name="repair_jobs", record_id=str(job.id),
                    new_value={"stage": job.stage, "barcode": device.barcode,
                               "status": "PNA", "resolution": resolution or ""},
                    request=request)

    elif (move_to_next == "yes"
          or final_status.strip().lower() in ("completed", "ok")) and device:
        # A successful completion always advances to the next stage
        # (L1→L2, L2→L3, L3→QC) — the checkbox is a manual override for the
        # case where final_status is left blank.
        from sqlalchemy import update as sa_update
        is_admin = current_user.role.value == "admin"
        current  = device.current_stage
        next_s   = NEXT_STAGE.get(current)
        if next_s:
            await validate_transition(device, next_s, db, override_admin=is_admin)
            prev_mv = (await db.execute(
                select(StageMovement)
                .where(StageMovement.device_id == device.id,
                       StageMovement.to_stage  == current,
                       StageMovement.exited_at == None)
                .order_by(StageMovement.moved_at.desc())
            )).scalars().first()
            if prev_mv:
                prev_mv.exited_at = app_now()
            # Close any other open repair jobs at this stage before moving
            await db.execute(
                sa_update(RepairJob)
                .where(RepairJob.device_id == device.id,
                       RepairJob.stage     == job.stage,
                       RepairJob.status    == RepairStatus.in_progress)
                .values(status=RepairStatus.completed, completed_at=app_now())
            )
            db.add(StageMovement(device_id=device.id, from_stage=current, to_stage=next_s,
                                 moved_by=current_user.username,
                                 notes=f"{job.stage} completed — {final_status or 'OK'}"))
            device.current_stage = next_s; device.updated_at = app_now()

    await audit(db, user=current_user, action="REPAIR_COMPLETE",
                table_name="repair_jobs", record_id=str(job.id),
                notes=f"{job.stage} complete — {outcome}", request=request)

    # Record spare parts used in this repair
    from decimal import Decimal as _Dec
    # Batch-fetch all referenced parts in one query
    import uuid as _uuid
    valid_part_ids = []
    for _pid in part_ids:
        try:
            valid_part_ids.append(_uuid.UUID(_pid))
        except (ValueError, AttributeError):
            pass

    _parts_map: dict = {}
    if valid_part_ids:
        _parts_res = await db.execute(
            select(SparePart).where(SparePart.id.in_(valid_part_ids))
        )
        _parts_map = {str(p.id): p for p in _parts_res.scalars().all()}

    for pid, qty_str in zip(part_ids, part_qtys):
        if not pid or not qty_str:
            continue
        try:
            qty = int(qty_str)
            if qty <= 0:
                continue
        except (ValueError, TypeError):
            continue
        _part = _parts_map.get(pid)
        if not _part:
            continue
        _part.qty_in_stock = max(0, (_part.qty_in_stock or 0) - qty)
        _total = _Dec(str(_part.unit_price)) * qty
        db.add(SPC(
            device_id=device.id if device else None,
            lot_id=device.lot_id if device else None,
            repair_job_id=job.id,
            part_id=_part.id,
            qty_used=qty,
            unit_cost=_part.unit_price,
            total_cost=_total,
            used_by=current_user.username,
            stage=job.stage,
            notes=f"Repair job {job.id}",
        ))

    await db.commit()
    import urllib.parse
    redirect = f"/repair/{stage}?success=Repair+completed"
    if warn_msg:
        redirect += f"&warning={urllib.parse.quote(warn_msg)}"
    return RedirectResponse(url=redirect, status_code=302)


@router.get("/move/form", response_class=HTMLResponse)
async def move_form(request: Request, barcode: str = None,
                    db: AsyncSession = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    device = None
    allowed_stages = []
    if barcode:
        r = await db.execute(select(Device).where(Device.barcode == barcode))
        device = r.scalar_one_or_none()
        if device:
            allowed_stages = await get_allowed_next_stages(device, db)
    return templates.TemplateResponse("repair/move.html", {
        "request": request, "current_user": current_user,
        "stages": [s for s in DeviceStage],
        "device": device, "allowed_stages": allowed_stages,
    })


@router.post("/move")
async def move_device(
    request: Request,
    barcode: str = Form(...),
    to_stage: str = Form(...),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Device).where(Device.barcode == barcode))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
    is_admin  = current_user.role.value == "admin"
    new_stage = DeviceStage(to_stage)
    await validate_transition(device, new_stage, db, override_admin=is_admin)
    prev = device.current_stage
    prev_mv = (await db.execute(
        select(StageMovement)
        .where(StageMovement.device_id == device.id,
               StageMovement.to_stage  == prev,
               StageMovement.exited_at == None)
        .order_by(StageMovement.moved_at.desc())
    )).scalars().first()
    if prev_mv:
        prev_mv.exited_at = app_now()
    device.current_stage = new_stage; device.updated_at = app_now()
    db.add(StageMovement(device_id=device.id, from_stage=prev, to_stage=new_stage,
                         moved_by=current_user.username, notes=notes or "Manual move"))
    await audit(db, user=current_user, action="STAGE_MOVED",
                table_name="devices", record_id=str(device.id),
                old_value={"stage": str(prev)}, new_value={"stage": to_stage}, request=request)
    await db.commit()
    return RedirectResponse(url=f"/repair/move/form?success=Device+moved+to+{to_stage}", status_code=302)
