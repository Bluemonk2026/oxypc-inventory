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
from sqlalchemy import select, func, and_, or_
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
from services.notifications import create_notification
from models.spare_parts import SparePartConsumption as SPC, SparePart
from models.work_order import WorkOrder
from models.part_request import PartRequest
from models.iqc_inspection import IQCInspection
from models.bucket import Bucket
from services.parts_required import compute_required

router = APIRouter(prefix="/repair", tags=["repair"], dependencies=[Depends(verify_csrf)])

# "l2"/"l3" retired: the /repair/l2 and /repair/l3 pages are withdrawn, so the
# catch-all GET /{stage} 404s on them. L1 work now completes straight to Stress
# Test; deeper repair is handled by the separate /repair/l3l4 endpoints.
STAGE_MAP  = {"l1": DeviceStage.l1}

# Roles that see the entire repair queue instead of just their own work.
# Everyone else sees the tags assigned to them plus the unclaimed pool — an
# engineer has no reason to see a colleague's bench, but hiding unclaimed tags
# from everyone is how devices go missing: most tags in L1 have no work order
# yet, and a strict own-only filter would make them invisible to every engineer
# at once, visible only to a supervisor who happens to look.
#
# "production_manager" is NOT a role in this system — it is a module/page name.
# inventory_manager already serves as the Production Manager for TRC and bucket
# work (see the note in routers/buckets.py::production_manager), which is what
# actually grants that oversight here. The string is listed anyway so that if a
# custom role by that name is ever created in the permission matrix, it inherits
# the full queue without needing a code change.
FULL_QUEUE_ROLES = {"admin", "trc_manager", "inventory_manager", "production_manager"}


def _sees_full_queue(user) -> bool:
    """True for supervisors. Custom roles (trc_manager) are plain strings, not
    UserRole members, so read the value defensively rather than assuming an enum."""
    role = user.role.value if hasattr(user.role, "value") else str(user.role or "")
    return role in FULL_QUEUE_ROLES
# Forward move out of repair is always Stress Test. The old l1→l2→l3 ladder is gone:
# /repair/l1 is the merged L1/L2 queue and L3/L4 runs on WorkOrders, not stages.
# l2/l3 keys are kept so any legacy device still sitting in those stages can move on.
NEXT_STAGE = {DeviceStage.l1: DeviceStage.qc_check,
              DeviceStage.l2: DeviceStage.qc_check,
              DeviceStage.l3: DeviceStage.qc_check}
LEVEL_MAP  = {"l1": 1, "l2": 2, "l3": 3}


def stage_allowed(stage: str):
    role_map = {
        "l1": require_roles(UserRole.admin, UserRole.inventory_manager, UserRole.l1_engineer,
                             UserRole.qc_inspector, UserRole.sales_manager),
        "l2": require_roles(UserRole.admin, UserRole.inventory_manager, UserRole.l2_engineer,
                             UserRole.qc_inspector, UserRole.sales_manager),
        "l3": require_roles(UserRole.admin, UserRole.inventory_manager, UserRole.l3_engineer,
                             UserRole.qc_inspector, UserRole.sales_manager),
    }
    return role_map.get(stage, require_roles(UserRole.admin))


# ── WorkID generation for the status-driven L1/L2 ↔ L3/L4 hand-off flow ────────
# work_orders.work_id is VARCHAR(12). "L3L4-"/"L1L2-" prefixes (5 chars) leave 7
# digits → 12 chars total, which fits the column without a widening migration.
async def _gen_prefixed_work_id(db: AsyncSession, prefix: str) -> str:
    width = 12 - len(prefix)
    base = (await db.execute(
        select(func.count(WorkOrder.id)).where(WorkOrder.work_id.like(f"{prefix}%"))
    )).scalar() or 0
    n = base + 1
    for _ in range(100000):
        wid = f"{prefix}{str(n).zfill(width)}"
        taken = (await db.execute(
            select(WorkOrder.id).where(WorkOrder.work_id == wid)
        )).scalar_one_or_none()
        if not taken:
            return wid
        n += 1
    raise HTTPException(500, "Could not allocate a WorkID")


async def _close_open_movement(db, device):
    """Mark the device's current open StageMovement as exited (mirrors the
    existing pattern used throughout complete_repair)."""
    prev_mv = (await db.execute(
        select(StageMovement)
        .where(StageMovement.device_id == device.id,
               StageMovement.to_stage == device.current_stage,
               StageMovement.exited_at == None)
        .order_by(StageMovement.moved_at.desc())
    )).scalars().first()
    if prev_mv:
        prev_mv.exited_at = app_now()


@router.post("/l1l2-start")
async def l1l2_start(
    request: Request,
    device_id: str = Form(...),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lightweight status-only Start Repair for the reworked L1/L2 page.

    Also creates a RepairJob for the device at its current L1/L2 stage so it
    surfaces in `open_jobs` — the "Complete L1/L2 Repair Job" side panel's
    Open-Job dropdown is populated from RepairJob rows, so without this the
    panel is unusable (BUG 1)."""
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
    device.l1l2_status = "Repair Started"
    device.updated_at = app_now()

    # Stage label ("L1"/"L2") derived from the device's current stage — this is
    # exactly what repair_list's open_jobs query filters on (RepairJob.stage).
    stage_label = (device.current_stage.value if device.current_stage else "l1").upper()
    existing_job = (await db.execute(
        select(RepairJob).where(
            RepairJob.device_id == device.id,
            RepairJob.stage == stage_label,
            RepairJob.status != RepairStatus.completed,
        )
    )).scalars().first()
    if not existing_job:
        db.add(RepairJob(
            device_id=device.id, stage=stage_label,
            engineer_id=current_user.id, engineer_name=current_user.full_name,
            assigned_engineer=current_user.full_name,
            status=RepairStatus.in_progress,
        ))
    await audit(db, user=current_user, action="L1L2_REPAIR_STARTED",
                table_name="devices", record_id=str(device.id),
                notes=f"L1/L2 repair started on {device.barcode}", request=request)
    await db.commit()
    return RedirectResponse(url="/repair/l1?success=Repair+started", status_code=302)


@router.post("/request-l3l4")
async def request_l3l4(
    request: Request,
    device_id: str = Form(...),
    assigned_l3l4_username: str = Form(...),
    repair_notes: str = Form(""),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Raise an L3/L4 request: device stays in L1/L2, a NEW (L3L4-prefixed)
    WorkOrder is created for the chosen L3/L4 engineer. The existing L1/L2
    WorkOrder is left untouched (a device can hold two open WorkOrders)."""
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
    eng = (await db.execute(
        select(User).where(User.username == assigned_l3l4_username)
    )).scalar_one_or_none()
    if not eng:
        raise HTTPException(404, "Selected L3/L4 engineer not found")

    device.l1l2_status = "Requested to L3/L4"
    # Blank box = leave any existing note alone
    if repair_notes.strip():
        device.repair_notes = repair_notes.strip()
    device.updated_at = app_now()

    work_id = await _gen_prefixed_work_id(db, "L3L4-")
    db.add(WorkOrder(
        work_id=work_id, device_id=device.id, barcode=device.barcode,
        stage="l3", assigned_role="l3_engineer",
        assigned_user_id=eng.id, assigned_username=eng.username,
        assigned_name=eng.full_name, status="pending",
        requested_by_name=current_user.full_name or current_user.username,
        created_by=current_user.username,
    ))
    await create_notification(
        db, user_id=eng.id, title="L3/L4 Repair Requested",
        message=(f"{device.barcode} was sent to you for L3/L4 repair by "
                 f"{current_user.full_name or current_user.username} (WorkID: {work_id})."),
        notification_type="info", barcode=device.barcode,
        brand=device.brand, model=device.model, stage="l3",
    )
    await audit(db, user=current_user, action="REQUEST_L3L4",
                table_name="work_orders", record_id=str(device.id),
                new_value={"work_id": work_id, "assigned": eng.username}, request=request)
    await db.commit()
    return RedirectResponse(url="/repair/l1?success=Requested+to+L3/L4", status_code=302)


@router.post("/l1l2-complete-to-stress")
async def l1l2_complete_to_stress(
    request: Request,
    device_id: str = Form(...),
    stress_engineer_username: str = Form(""),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Complete L1/L2: move the device to Stress Test (qc_check). An engineer is
    optional — with none the STRS- WorkOrder is still raised, unassigned, so the
    WorkID Status board keeps full traceability."""
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
    eng = None
    if stress_engineer_username:
        eng = (await db.execute(
            select(User).where(User.username == stress_engineer_username)
        )).scalar_one_or_none()
        if not eng:
            raise HTTPException(404, "Selected Stress Test engineer not found")

    prev = device.current_stage
    await _close_open_movement(db, device)
    # Close any open L1/L2 WorkOrders for this device
    from sqlalchemy import update as sa_update
    await db.execute(
        sa_update(WorkOrder)
        .where(WorkOrder.device_id == device.id,
               or_(WorkOrder.work_id.like("L1L2-%"), WorkOrder.stage.in_(["l1", "l2"])),
               WorkOrder.status != "completed")
        .values(status="completed", completed_at=app_now())
    )
    # Also close any open RepairJobs so the device drops out of the side
    # "Complete Job" panel's dropdown — otherwise a stale job entry lets the
    # engineer submit /repair/complete after the device already moved to
    # qc_check, which 409s with a STAGE CONFLICT.
    await db.execute(
        sa_update(RepairJob)
        .where(RepairJob.device_id == device.id,
               RepairJob.status == RepairStatus.in_progress)
        .values(status=RepairStatus.completed, completed_at=app_now())
    )
    device.current_stage = DeviceStage.qc_check
    device.l1l2_status = "Completed"
    device.updated_at = app_now()
    db.add(StageMovement(device_id=device.id, from_stage=prev, to_stage=DeviceStage.qc_check,
                         moved_by=current_user.username,
                         notes=(f"L1/L2 completed — assigned to Stress Test ({eng.full_name or eng.username})"
                                if eng else "L1/L2 completed — moved to Stress Test (unassigned)")))
    # A WorkOrder makes the assignment visible on the WorkID Status board
    work_id = await _gen_prefixed_work_id(db, "STRS-")
    db.add(WorkOrder(
        work_id=work_id, device_id=device.id, barcode=device.barcode,
        stage="qc", assigned_role="qc_inspector",
        assigned_user_id=eng.id if eng else None,
        assigned_username=eng.username if eng else None,
        assigned_name=eng.full_name if eng else None, status="pending",
        requested_by_name=current_user.full_name or current_user.username,
        created_by=current_user.username,
    ))
    if eng:
        await create_notification(
            db, user_id=eng.id, title="Device Assigned for Stress Test",
            message=(f"{device.barcode} was moved to Stress Test and assigned to you by "
                     f"{current_user.full_name or current_user.username}."),
            notification_type="info", barcode=device.barcode,
            brand=device.brand, model=device.model, stage="qc_check",
        )
    await audit(db, user=current_user, action="L1L2_COMPLETE_TO_STRESS",
                table_name="devices", record_id=str(device.id),
                new_value={"assigned": eng.username if eng else None}, request=request)
    await db.commit()
    return RedirectResponse(url="/repair/l1?success=Moved+to+Stress+Test", status_code=302)


@router.post("/back-to-production")
async def back_to_production(
    request: Request,
    device_id: str = Form(...),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """After an L3/L4 scrap decision, push the device into the Production
    Manager's 'Scrap Products from Repair Line' table (current_stage=scrapped)."""
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
    prev = device.current_stage
    await _close_open_movement(db, device)
    # Close open RepairJobs so the device drops out of the Complete-Job panel
    # (a stale entry would 409 with STAGE CONFLICT after the device leaves L1/L2).
    from sqlalchemy import update as sa_update
    await db.execute(
        sa_update(RepairJob)
        .where(RepairJob.device_id == device.id,
               RepairJob.status == RepairStatus.in_progress)
        .values(status=RepairStatus.completed, completed_at=app_now())
    )
    device.current_stage = DeviceStage.scrapped
    device.updated_at = app_now()
    db.add(StageMovement(device_id=device.id, from_stage=prev, to_stage=DeviceStage.scrapped,
                         moved_by=current_user.username,
                         notes=f"Back to Production — {device.l34_status or 'Scrap'} from repair line"))
    await audit(db, user=current_user, action="BACK_TO_PRODUCTION",
                table_name="devices", record_id=str(device.id),
                notes=f"{device.l34_status or 'Scrap'} → Scrap Products", request=request)
    await db.commit()
    return RedirectResponse(url="/repair/l1?success=Sent+to+Scrap+Products", status_code=302)


# ── L3/L4 Repair page (WorkOrder-driven, per assigned engineer) ────────────────
@router.get("/l3l4", response_class=HTMLResponse)
async def l3l4_list(request: Request,
                    db: AsyncSession = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    full_queue = _sees_full_queue(current_user)
    stmt = (select(WorkOrder, Device, Lot.lot_number)
            .join(Device, WorkOrder.device_id == Device.id)
            .join(Lot, Device.lot_id == Lot.id, isouter=True)
            .where(WorkOrder.work_id.like("L3L4-%"),
                   WorkOrder.status != "completed")
            .order_by(WorkOrder.assigned_at.desc()))
    if not full_queue:
        stmt = stmt.where(WorkOrder.assigned_user_id == current_user.id)
    rows = (await db.execute(stmt)).all()

    today = app_now().date()
    bucket_map: dict = {}
    bucket_ids = [d.bucket_id for _, d, _ in rows if d.bucket_id]
    if bucket_ids:
        bkt_rows = (await db.execute(select(Bucket).where(Bucket.id.in_(bucket_ids)))).scalars().all()
        bkt_by_id = {str(b.id): b.bucket_number for b in bkt_rows}
        for _, d, _ln in rows:
            if d.bucket_id:
                bucket_map[str(d.id)] = bkt_by_id.get(str(d.bucket_id), "")

    items = []
    for wo, dev, lot_number in rows:
        aging = max(0, (today - wo.assigned_at.date()).days) if wo.assigned_at else 0
        items.append({
            "work_id": wo.work_id,
            "device_id": str(dev.id),
            "barcode": dev.barcode,
            "status": dev.l34_status or "New",
            "bucket": bucket_map.get(str(dev.id), ""),
            "notes": wo.requested_by_name or "—",
            "repair_notes": dev.repair_notes or "—",
            "aging": aging,
        })

    # Available parts for the on-page "Request Part" modal (same query
    # repair_list uses) — the modal defaults its Part select to the
    # "Motherboard Parts" category.
    available_parts = (await db.execute(
        select(SparePart).where(SparePart.qty_in_stock > 0).order_by(SparePart.name)
    )).scalars().all()

    return templates.TemplateResponse("repair/l3l4.html", {
        "request": request, "current_user": current_user,
        "items": items, "total": len(items),
        "available_parts": available_parts,
    })


@router.post("/l3l4-start")
async def l3l4_start(
    request: Request,
    device_id: str = Form(...),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
    from sqlalchemy import update as sa_update
    await db.execute(
        sa_update(WorkOrder)
        .where(WorkOrder.device_id == device.id, WorkOrder.work_id.like("L3L4-%"),
               WorkOrder.status != "completed")
        .values(status="in_progress", started_at=app_now())
    )
    device.l34_status = "Repair Started"
    device.updated_at = app_now()
    await audit(db, user=current_user, action="L3L4_REPAIR_STARTED",
                table_name="devices", record_id=str(device.id),
                notes=f"L3/L4 repair started on {device.barcode}", request=request)
    await db.commit()
    return RedirectResponse(url="/repair/l3l4?success=Repair+started", status_code=302)


@router.post("/l3l4-complete")
async def l3l4_complete(
    request: Request,
    device_id: str = Form(...),
    activity: str = Form(""),
    repair_notes: str = Form(""),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
    from sqlalchemy import update as sa_update
    await db.execute(
        sa_update(WorkOrder)
        .where(WorkOrder.device_id == device.id, WorkOrder.work_id.like("L3L4-%"),
               WorkOrder.status != "completed")
        .values(status="completed", completed_at=app_now())
    )
    device.l34_status = "Completed"
    if activity.strip():
        device.l34_activity = activity.strip()
    if repair_notes.strip():
        device.repair_notes = repair_notes.strip()
    # L1/L2's own status column was still stuck on "Requested to L3/L4" once
    # L3/L4 finished — nothing told the L1/L2 queue the device was actually
    # back and awaiting further action there.
    device.l1l2_status = "Returned from L3/L4"
    device.updated_at = app_now()
    await audit(db, user=current_user, action="L3L4_COMPLETE",
                table_name="devices", record_id=str(device.id),
                notes=f"L3/L4 completed on {device.barcode}", request=request)
    await db.commit()
    return RedirectResponse(url="/repair/l3l4?success=Repair+completed", status_code=302)


@router.post("/l3l4-scrap")
async def l3l4_scrap(
    request: Request,
    device_id: str = Form(...),
    scrap_type: str = Form(...),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if scrap_type not in ("Normal Scrap", "Replacement Scrap"):
        raise HTTPException(400, "Invalid scrap type")
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
    from sqlalchemy import update as sa_update
    await db.execute(
        sa_update(WorkOrder)
        .where(WorkOrder.device_id == device.id, WorkOrder.work_id.like("L3L4-%"),
               WorkOrder.status != "completed")
        .values(status="completed", completed_at=app_now())
    )
    device.l34_status = scrap_type
    device.updated_at = app_now()
    await audit(db, user=current_user, action="L3L4_SCRAP",
                table_name="devices", record_id=str(device.id),
                notes=f"{scrap_type} on {device.barcode}", request=request)
    await db.commit()
    return RedirectResponse(url="/repair/l3l4?success=Scrap+recorded", status_code=302)


@router.get("/{stage}", response_class=HTMLResponse)
async def repair_list(stage: str, request: Request,
                      db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    if stage not in STAGE_MAP:
        raise HTTPException(404)
    device_stage = STAGE_MAP[stage]

    result = await db.execute(
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.current_stage == device_stage, Device.is_active == True)
        .order_by(Device.updated_at.desc())
    )
    devices = result.all()

    # ── Scope to this engineer's own bench ───────────────────────────────────
    # Only the MOST RECENT assignment counts. A device can carry several open
    # work orders, so a tag reassigned away from me leaves my older work order
    # behind; treating any assignment-to-me as ownership kept the tag on the
    # previous engineer's list forever. Latest assignment wins, full stop.
    # Filtering here, before the maps below, means every downstream count and
    # lookup is scoped automatically rather than each one needing to remember.
    if not _sees_full_queue(current_user):
        dev_ids = [d.id for d, _ in devices]
        current_owner: dict[str, object] = {}
        if dev_ids:
            wo_rows = (await db.execute(
                select(WorkOrder.device_id, WorkOrder.assigned_user_id)
                .where(WorkOrder.device_id.in_(dev_ids),
                       WorkOrder.stage == stage,
                       WorkOrder.status != "completed",
                       WorkOrder.assigned_user_id.isnot(None))
                # created_at breaks ties: two work orders can share an
                # assigned_at when a reassignment happens in the same second.
                .order_by(WorkOrder.device_id, WorkOrder.assigned_at.desc(),
                          WorkOrder.created_at.desc())
            )).all()
            for did, uid in wo_rows:
                current_owner.setdefault(str(did), uid)
        # A device with no open assignment is unclaimed and stays visible to
        # everyone — that is how work reaches a bench in the first place.
        devices = [(d, ln) for d, ln in devices
                   if current_owner.get(str(d.id), current_user.id) == current_user.id]

    total = len(devices)
    visible_ids = {str(d.id) for d, _ in devices}
    jobs_result = await db.execute(
        select(RepairJob, Device.barcode, Device.brand, Device.model)
        .join(Device, RepairJob.device_id == Device.id)
        .where(RepairJob.stage == stage.upper(), RepairJob.status != RepairStatus.completed,
               # Only devices still physically in this stage — a job whose device
               # already moved (stress fail, transfer, scrap) must not be offered
               # in the Complete-Job dropdown or /repair/complete 409s on it.
               Device.current_stage == device_stage, Device.is_active == True)
        .order_by(RepairJob.started_at.desc())
    )
    open_jobs = jobs_result.all()
    # Same scope as the table above — otherwise the Complete-Job dropdown would
    # still list a colleague's device even though its row is hidden.
    open_jobs = [r for r in open_jobs if str(r.RepairJob.device_id) in visible_ids]

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

    # ── Work orders (WorkID + assignment + timeline) for assigned devices ─────
    wo_by_device: dict = {}
    if device_ids:
        wo_rows = (await db.execute(
            select(WorkOrder).where(
                WorkOrder.device_id.in_(device_ids),
                WorkOrder.stage == stage,
                WorkOrder.status != "completed",
            ).order_by(WorkOrder.assigned_at.desc())
        )).scalars().all()
        for wo in wo_rows:
            key = str(wo.device_id)
            if key in wo_by_device:
                continue  # keep the latest (rows ordered desc)
            wo_by_device[key] = wo

    # ── Part-request 'not in stock' alerts to surface on the Pending list (#12) ─
    parts_alert_map: dict = {}
    if device_ids:
        na_rows = (await db.execute(
            select(PartRequest.device_id).where(
                PartRequest.device_id.in_(device_ids),
                PartRequest.status == "not_in_stock",
            )
        )).all()
        for (did,) in na_rows:
            parts_alert_map[str(did)] = True

    # ── Parts Required (IQC-driven count) + Parts Requested (requested + handed over) ─
    parts_required_map: dict = {}
    parts_requested_map: dict = {}
    if device_ids:
        # Required count: from each device's IQC inspection via the fixed parts matrix
        iqc_rows = (await db.execute(
            select(IQCInspection).where(IQCInspection.device_id.in_(device_ids))
        )).scalars().all()
        iqc_by_dev = {}
        for iqc in iqc_rows:
            iqc_by_dev.setdefault(str(iqc.device_id), iqc)  # one per device
        dev_by_id = {str(d.id): d for d, _ in devices}
        for did_str, dev in dev_by_id.items():
            iqc = iqc_by_dev.get(did_str)
            parts_required_map[did_str] = sum(
                1 for r in compute_required(iqc, dev) if r["required"]
            )
        # Requested count: PartRequests in requested / handed_over state
        pr_rows = (await db.execute(
            select(PartRequest.device_id, func.count(PartRequest.id))
            .where(PartRequest.device_id.in_(device_ids),
                   PartRequest.status.in_(["requested", "handed_over"]))
            .group_by(PartRequest.device_id)
        )).all()
        for did, cnt in pr_rows:
            parts_requested_map[str(did)] = cnt

    # ── Timeline pause/resume (item 32): a device is "blocked" while any of
    # its required parts currently has 0 live stock in Part Master. While
    # blocked, the WorkOrder's elapsed-days clock freezes; once every required
    # part has stock again, it resumes counting from today (past pause time is
    # banked in paused_days_total so it's never counted against the engineer).
    work_map: dict = {}
    if device_ids and wo_by_device:
        now = app_now()
        today = now.date()
        # Stock lookups are memoised per (category, keyword). PARTS_MATRIX has 20
        # fixed rows, so every device asks the same handful of questions — running
        # the query per device per part meant ~1000 sequential round-trips on a
        # 99-device queue and the page never finished loading.
        stock_cache: dict = {}

        async def _has_stock(category, keyword):
            key = (category, keyword)
            if key not in stock_cache:
                sp = (await db.execute(
                    select(SparePart).where(or_(
                        SparePart.category == category,
                        SparePart.name.ilike(f"%{keyword}%"),
                    )).order_by(SparePart.qty_in_stock.desc())
                )).scalars().first()
                stock_cache[key] = bool(sp and sp.qty_in_stock)
            return stock_cache[key]

        for did_str, dev in dev_by_id.items():
            wo = wo_by_device.get(did_str)
            if not wo:
                continue
            iqc = iqc_by_dev.get(did_str)
            blocked = False
            for row in compute_required(iqc, dev):
                if not row["required"]:
                    continue
                if not await _has_stock(row["category"], row["keyword"]):
                    blocked = True
                    break

            if blocked and not wo.paused_since:
                wo.paused_since = now
            elif not blocked and wo.paused_since:
                wo.paused_days_total += max(0, (now - wo.paused_since).days)
                wo.paused_since = None

            paused_days = wo.paused_days_total + (
                max(0, (now - wo.paused_since).days) if wo.paused_since else 0
            )
            raw_days = (today - wo.assigned_at.date()).days if wo.assigned_at else 0
            work_map[did_str] = {
                "work_id": wo.work_id,
                "assigned_name": wo.assigned_name or wo.assigned_username or "—",
                "days_pending": max(0, raw_days - paused_days),
                "paused": bool(wo.paused_since),
            }
        await db.commit()

    # ── Returned-device job ids (item 7): L3 shows a "Replace Device with" field
    #    only for jobs whose device has Return Status = Yes ─────────────────────
    returned_job_ids: set = set()
    open_dev_ids = [j.device_id for j, *_ in open_jobs]
    if open_dev_ids:
        ret_rows = (await db.execute(
            select(Device.id).where(Device.id.in_(open_dev_ids),
                                    Device.return_status == True)
        )).all()
        ret_dev = {str(r[0]) for r in ret_rows}
        returned_job_ids = {str(j.id) for j, *_ in open_jobs if str(j.device_id) in ret_dev}

    # ── Bucket map: device_id → bucket_number ────────────────────────────────
    bucket_map: dict = {}
    bucket_ids = [d.bucket_id for d, _ in devices if d.bucket_id]
    if bucket_ids:
        bkt_rows = (await db.execute(
            select(Bucket).where(Bucket.id.in_(bucket_ids))
        )).scalars().all()
        bkt_by_id = {str(b.id): b.bucket_number for b in bkt_rows}
        for device, _ in devices:
            if device.bucket_id:
                bucket_map[str(device.id)] = bkt_by_id.get(str(device.bucket_id), "")

    # ── Engineer dropdowns for the L1/L2 hand-off modals ──────────────────────
    l3l4_engineers = (await db.execute(
        select(User).where(User.role == "l3_engineer", User.status == True)
        .order_by(User.full_name)
    )).scalars().all()
    stress_engineers = (await db.execute(
        select(User).where(User.role == "qc_inspector", User.status == True)
        .order_by(User.full_name)
    )).scalars().all()

    return templates.TemplateResponse(f"repair/{stage}.html", {
        "request": request, "devices": devices, "open_jobs": open_jobs,
        "l3l4_engineers": l3l4_engineers, "stress_engineers": stress_engineers,
        "stage": stage.upper(), "current_user": current_user,
        "returned_job_ids": returned_job_ids,
        "location_map": location_map,
        "scrap_warning_map": scrap_warning_map,
        "suggest_qc_ids": suggest_qc_ids,
        "available_parts": available_parts,
        "work_map": work_map,
        "parts_alert_map": parts_alert_map,
        "parts_required_map": parts_required_map,
        "parts_requested_map": parts_requested_map,
        "bucket_map": bucket_map,
        "started_ids": {str(j.device_id) for j, *_ in open_jobs},
        "total": total,
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

    # NOTE: a hard "requested >= required parts" gate was tried here and on the
    # Start Repair button, but compute_required()'s fallback (no IQC record on
    # a device) treats nearly every part category as "required" — with no
    # devices in this dataset carrying an IQC record, that made Start Repair
    # permanently blocked for everything. Reverted; parts_required_map /
    # parts_requested_map are still shown as informational columns on the
    # list page so an engineer can see what's outstanding without being
    # locked out of starting the job.

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
                     team_name=team_name or None,
                     # Assigned To defaults to whoever is starting this stage — the
                     # form doesn't expose an override input, so the current
                     # logged-in engineer is the sensible default per stage.
                     assigned_engineer=assigned_engineer or current_user.full_name,
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
    replace_with_barcode: str = Form(""),
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

    # ── L3 device replacement (items 7 & 8) ──────────────────────────────────
    # When a returned device is swapped for a good one, cross-reference both
    # devices' "Replaced" field so the trail is traceable from either tag.
    rwb = (replace_with_barcode or "").strip()
    if stage == "l3" and rwb and rwb != device.barcode:
        repl = (await db.execute(
            select(Device).where(Device.barcode == rwb)
        )).scalar_one_or_none()
        if repl:
            device.replaced = f"Replaced by {repl.barcode}"
            repl.replaced = f"Replaced from {device.barcode}"
            await audit(db, user=current_user, action="DEVICE_REPLACED",
                        table_name="devices", record_id=str(device.id),
                        new_value={"replaced_by": repl.barcode, "from": device.barcode},
                        request=request)

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

    elif final_status in ("Escalate to L3", "Escalate to L2",
                          "Request to L3", "Request to L2") and device:
        from sqlalchemy import update as sa_update
        # The l2/l3 stages are retired, so escalation no longer moves the device: L1 and L2
        # share the /repair/l1 queue, and L3/L4 is raised as a separate WorkOrder via
        # /repair/request-l3l4. Sending it to l2/l3 here would strand it in a stage with no page.
        escalate_to = DeviceStage.l1
        is_admin    = current_user.role.value == "admin"
        current     = device.current_stage
        if current != escalate_to:
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
            db.add(StageMovement(device_id=device.id, from_stage=current, to_stage=escalate_to,
                                 moved_by=current_user.username,
                                 notes=f"{job.stage} escalated — {final_status}"))
            device.current_stage = escalate_to
        # Close any other open repair jobs at this stage
        await db.execute(
            sa_update(RepairJob)
            .where(RepairJob.device_id == device.id,
                   RepairJob.stage     == job.stage,
                   RepairJob.status    == RepairStatus.in_progress)
            .values(status=RepairStatus.completed, completed_at=app_now())
        )
        device.l1l2_status = "New"
        device.updated_at  = app_now()
        # Carry the same WorkID forward (re-stage the open WorkOrder)
        await db.execute(
            sa_update(WorkOrder)
            .where(WorkOrder.device_id == device.id, WorkOrder.status != "completed")
            .values(stage=escalate_to.value)
        )

    elif final_status == "PNA" and device:
        # Parts Not Available — keep device in current stage; job status already saved above
        await audit(db, user=current_user, action="REPAIR_PNA",
                    table_name="repair_jobs", record_id=str(job.id),
                    new_value={"stage": job.stage, "barcode": device.barcode,
                               "status": "PNA", "resolution": resolution or ""},
                    request=request)

    elif final_status == "Back to Inventory" and device:
        # Move the device back to the Stock Inward table
        from sqlalchemy import update as sa_update
        current = device.current_stage
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
        db.add(StageMovement(device_id=device.id, from_stage=current, to_stage=DeviceStage.stock_in,
                             moved_by=current_user.username,
                             notes=f"{job.stage} completed — moved back to Stock Inward"))
        device.current_stage = DeviceStage.stock_in
        device.updated_at    = app_now()
        await create_notification(
            db,
            user_id=None,
            title="Device Returned to Stock Inward",
            message=(
                f"{device.barcode} was moved back to Stock Inward from {current.value} "
                f"by {current_user.full_name or current_user.username}."
            ),
            notification_type="warning",
            barcode=device.barcode,
            brand=device.brand,
            model=device.model,
            stage=DeviceStage.stock_in.value,
        )

    elif (final_status.strip() == "Completed" and device
          and device.current_stage in (DeviceStage.l1, DeviceStage.l2)):
        # Side "Complete Job" panel on the L1/L2 pages. A Completed L1/L2 job
        # moves the tag straight to Stress Test (qc_check). Movement bookkeeping
        # mirrors l1l2_complete_to_stress; unlike that endpoint this path
        # deliberately does NOT pick a Stress Test engineer and does NOT create a
        # STRS- WorkOrder — the tag lands unassigned in the Stress Test queue.
        # assert_device_in_stage already ran above against the job's own stage.
        from sqlalchemy import update as sa_update
        current = device.current_stage
        await _close_open_movement(db, device)
        # Close any other open repair jobs at this stage before moving
        await db.execute(
            sa_update(RepairJob)
            .where(RepairJob.device_id == device.id,
                   RepairJob.stage     == job.stage,
                   RepairJob.status    == RepairStatus.in_progress)
            .values(status=RepairStatus.completed, completed_at=app_now())
        )
        device.current_stage = DeviceStage.qc_check
        device.l1l2_status   = "Completed"
        device.updated_at    = app_now()
        db.add(StageMovement(device_id=device.id, from_stage=current,
                             to_stage=DeviceStage.qc_check,
                             moved_by=current_user.username,
                             notes=f"{job.stage} completed — moved to Stress Test"))
        await create_notification(
            db, user_id=None, title="Device Stage Changed",
            message=(f"{device.barcode} moved from {current.value} to "
                     f"{DeviceStage.qc_check.value} by "
                     f"{current_user.full_name or current_user.username}."),
            notification_type="alert", barcode=device.barcode,
            brand=device.brand, model=device.model,
            stage=DeviceStage.qc_check.value,
        )

    elif (move_to_next == "yes"
          or final_status.strip().lower() in ("completed", "ok")) and device:
        # A successful completion always advances to the next stage
        # (L1→L2, L2→L3, L3→QC) — the checkbox is a manual override for the
        # case where final_status is left blank.
        from sqlalchemy import update as sa_update
        is_admin = current_user.role.value == "admin"
        current  = device.current_stage
        # Per business rule: a Completed repair at L1/L2/L3 goes straight to Stress Test (qc_check)
        if final_status.strip().lower() in ("completed", "ok"):
            next_s = DeviceStage.qc_check
        else:
            next_s = NEXT_STAGE.get(current)
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
            # Keep the L1/L2 status column consistent when completing via the
            # side Complete-Job panel (the old path predates l1l2_status).
            if current in (DeviceStage.l1, DeviceStage.l2):
                device.l1l2_status = "Completed"
            # Broadcast stage-change alert to all managers/admins (user_id=None = all users)
            await create_notification(
                db,
                user_id=None,
                title="Device Stage Changed",
                message=(
                    f"{device.barcode} moved from {current.value} to {next_s.value} "
                    f"by {current_user.full_name or current_user.username}."
                ),
                notification_type="alert",
                barcode=device.barcode,
                brand=device.brand,
                model=device.model,
                stage=next_s.value,
            )

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
