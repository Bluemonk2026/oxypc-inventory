"""
Buckets Router — Carton/bucket grouping for Stock Inward → TRC Production flow
"""
import uuid
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceStage, StageMovement
from models.bucket import Bucket, _new_bucket_number
from models.master import MasterData
from models.stock_transfer import StockTransfer
from models.work_order import WorkOrder
from models.location import StorageLocation
from auth.dependencies import get_current_user, require_roles, verify_csrf
from services.notifications import create_notification
from services.audit_engine import audit

router = APIRouter(tags=["buckets"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.inventory_manager)

FALLBACK_WAREHOUSES = [
    "TRC 1st Floor", "TRC 2nd Floor", "TRC 3rd Floor",
    "Bluemonk House Showroom", "Bluemonk Showroom", "Other",
]

# L1 and L2 engineers share the merged /repair/l1 queue and the l2 stage is retired, so an
# L2 assignment lands in l1 — routing it to DeviceStage.l2 would strand the whole bucket.
DEPT_TO_STAGE = {"L1 Engineer": "l1", "L2 Engineer": "l1"}
DEPT_TO_ROLE  = {"L1 Engineer": "l1_engineer", "L2 Engineer": "l2_engineer"}
STAGE_ENUM    = {"l1": DeviceStage.l1}


async def _gen_work_id(db: AsyncSession) -> str:
    base = (await db.execute(select(func.count(WorkOrder.id)))).scalar() or 0
    n = base + 1
    for _ in range(10000):
        wid = str(n).zfill(12)
        taken = (await db.execute(
            select(WorkOrder.id).where(WorkOrder.work_id == wid)
        )).scalar_one_or_none()
        if not taken:
            return wid
        n += 1
    return str(n).zfill(12)


# ── API helpers (GET — no CSRF check) ────────────────────────────────────────

@router.get("/api/buckets")
async def list_buckets(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status: str = "stock_in",
):
    statuses = [s.strip() for s in status.split(",") if s.strip()]
    rows = (await db.execute(
        select(Bucket).where(Bucket.status.in_(statuses)).order_by(Bucket.created_at.desc())
    )).scalars().all()

    if not rows:
        return JSONResponse([])

    bucket_ids = [b.id for b in rows]
    count_rows = (await db.execute(
        select(Device.bucket_id, func.count(Device.id))
        .where(Device.bucket_id.in_(bucket_ids), Device.is_active == True)
        .group_by(Device.bucket_id)
    )).all()
    count_map = {str(r[0]): r[1] for r in count_rows}

    # Total Pass / Total Fail — count of tag numbers per bucket by Final QC
    # decision (Device.final_qc_status), shown as extra Movement table columns
    # on both the Inventory Manager and Production Manager pages.
    qc_rows = (await db.execute(
        select(Device.bucket_id, Device.final_qc_status, func.count(Device.id))
        .where(Device.bucket_id.in_(bucket_ids), Device.is_active == True,
               Device.final_qc_status.isnot(None))
        .group_by(Device.bucket_id, Device.final_qc_status)
    )).all()
    pass_map, fail_map = {}, {}
    for bkt_id, qc_status, cnt in qc_rows:
        target = pass_map if qc_status == "pass" else fail_map
        target[str(bkt_id)] = target.get(str(bkt_id), 0) + cnt

    loc_map = {}
    loc_ids = {b.location_id for b in rows if b.location_id}
    if loc_ids:
        loc_rows = (await db.execute(
            select(StorageLocation).where(StorageLocation.id.in_(loc_ids))
        )).scalars().all()
        loc_map = {l.id: l for l in loc_rows}

    return JSONResponse([{
        "id": str(b.id),
        "bucket_number": b.bucket_number,
        "name": b.name or "",
        "location": b.location or "",
        "location_unit_id": loc_map[b.location_id].unit_id if b.location_id in loc_map else "",
        "location_type": loc_map[b.location_id].unit_type_label if b.location_id in loc_map else "",
        "category": b.category or "",
        "status": b.status,
        "device_count": count_map.get(str(b.id), 0),
        "received_qty": b.received_qty,
        "assigned_to_production": bool(b.assigned_to_production),
        "total_pass": pass_map.get(str(b.id), 0),
        "total_fail": fail_map.get(str(b.id), 0),
    } for b in rows])


@router.get("/api/buckets/device-map")
async def bucket_device_map(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status: str = "stock_in",
):
    """Returns {barcode: bucket_number} for all devices in buckets of given status."""
    statuses = [s.strip() for s in status.split(",") if s.strip()]
    buckets = (await db.execute(
        select(Bucket).where(Bucket.status.in_(statuses))
    )).scalars().all()
    if not buckets:
        return JSONResponse({})

    bucket_num_map = {b.id: b.bucket_number for b in buckets}
    devices = (await db.execute(
        select(Device.barcode, Device.bucket_id)
        .where(Device.bucket_id.in_(list(bucket_num_map.keys())), Device.is_active == True)
    )).all()
    return JSONResponse({d.barcode: bucket_num_map[d.bucket_id] for d in devices})


@router.get("/api/buckets/{bucket_id}/tags")
async def bucket_tags(
    bucket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        uid = uuid.UUID(bucket_id)
    except Exception:
        raise HTTPException(400, "Invalid bucket ID")
    devices = (await db.execute(
        select(Device).where(Device.bucket_id == uid, Device.is_active == True)
    )).scalars().all()
    return JSONResponse([{
        "barcode": d.barcode,
        "brand": d.brand or "",
        "model": d.model or "",
        "grade": d.grade.value if d.grade else "",
    } for d in devices])


@router.get("/api/bucket-engineers")
async def bucket_engineers(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns L1 and L2 engineers for the Assign Bucket modal."""
    rows = (await db.execute(
        select(User).where(
            User.role.in_([UserRole.l1_engineer, UserRole.l2_engineer]),
            User.status == True,
        ).order_by(User.full_name)
    )).scalars().all()
    return JSONResponse([{
        "id": str(u.id),
        "name": u.full_name or u.username,
        "role": str(u.role),
    } for u in rows])


@router.get("/api/production-manager")
async def production_manager(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns the current Production Manager for the Assign-to-Production modal.
    Judgment call: this system has no dedicated 'production_manager' UserRole —
    routers/stock.py already treats UserRole.inventory_manager as the Production
    Manager role for TRC/bucket operations (see `allowed = require_roles(admin,
    inventory_manager)` at the top of stock.py and buckets.py), so we reuse it
    here rather than inventing a new role that would require a schema-review
    approval for a new enum value."""
    mgr = (await db.execute(
        select(User).where(User.role == UserRole.inventory_manager, User.status == True)
        .order_by(User.full_name).limit(1)
    )).scalar_one_or_none()
    if not mgr:
        return JSONResponse({"id": None, "name": None})
    return JSONResponse({"id": str(mgr.id), "name": mgr.full_name or mgr.username})


@router.get("/api/bucket-warehouses")
async def bucket_warehouses(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    wh = (await db.execute(
        select(MasterData.value)
        .where(MasterData.category == "warehouse", MasterData.is_active == True)
        .order_by(MasterData.display_order, MasterData.value)
    )).scalars().all()
    return JSONResponse(list(wh) or FALLBACK_WAREHOUSES)


# ── Write endpoints (POST — CSRF verified) ───────────────────────────────────

@router.post("/buckets/create")
async def create_bucket(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    barcodes: str = Form(...),
    name: str = Form(default=""),
    location: str = Form(default=""),
    location_id: str = Form(default=""),
):
    barcode_list = [b.strip() for b in barcodes.split(",") if b.strip()]
    if not barcode_list:
        raise HTTPException(400, "No barcodes provided")

    devices = (await db.execute(
        select(Device).where(Device.barcode.in_(barcode_list), Device.is_active == True)
    )).scalars().all()
    if not devices:
        raise HTTPException(404, "No matching devices found")

    # Derive category from first device brand
    category = devices[0].brand if devices else None

    loc_uuid = None
    loc = None
    if location_id and location_id.strip():
        try:
            loc_uuid = uuid.UUID(location_id.strip())
        except Exception:
            loc_uuid = None
        if loc_uuid:
            loc = (await db.execute(
                select(StorageLocation).where(StorageLocation.id == loc_uuid)
            )).scalar_one_or_none()

    bucket = Bucket(
        bucket_number=_new_bucket_number(),
        name=name.strip() or None,
        location=(loc.display_name if loc else (location.strip() or None)),
        location_id=loc.id if loc else None,
        category=category,
        status="stock_in",
        created_by=current_user.username,
    )
    db.add(bucket)
    await db.flush()

    for d in devices:
        d.bucket_id = bucket.id
        if loc:
            d.location_id = loc.id
        # Task 2(c): mark devices as Stock Inward stage on bucket assignment
        d.current_stage = DeviceStage.stock_in
        d.updated_at = app_now()

    await db.commit()
    return JSONResponse({"ok": True, "bucket_number": bucket.bucket_number, "bucket_id": str(bucket.id), "count": len(devices)})


@router.post("/buckets/{bucket_id}/edit")
async def edit_bucket(
    bucket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    name: str = Form(default=""),
    location: str = Form(default=""),
):
    try:
        uid = uuid.UUID(bucket_id)
    except Exception:
        raise HTTPException(400, "Invalid bucket ID")
    bucket = (await db.execute(select(Bucket).where(Bucket.id == uid))).scalar_one_or_none()
    if not bucket:
        raise HTTPException(404, "Bucket not found")
    bucket.name = name.strip() or bucket.name
    bucket.location = location.strip() or bucket.location
    bucket.updated_at = app_now()
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/buckets/{bucket_id}/rename")
async def rename_bucket(
    bucket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    name: str = Form(default=""),
):
    """Inventory Manager bucket table 'Edit' action — renames the bucket only.
    Kept separate from /buckets/{id}/edit because that endpoint treats a blank
    field as 'keep existing', so it can never clear a name; this one sets the
    value explicitly (blank → NULL), which the name-only modal needs."""
    try:
        uid = uuid.UUID(bucket_id)
    except Exception:
        raise HTTPException(400, "Invalid bucket ID")
    bucket = (await db.execute(select(Bucket).where(Bucket.id == uid))).scalar_one_or_none()
    if not bucket:
        raise HTTPException(404, "Bucket not found")

    old_name = bucket.name
    bucket.name = name.strip() or None
    bucket.updated_at = app_now()
    await audit(
        db, action="BUCKET_RENAMED", user=current_user,
        table_name="buckets", record_id=str(bucket.id),
        old_value={"name": old_name}, new_value={"name": bucket.name},
        notes=f"Bucket {bucket.bucket_number} renamed", request=request,
    )
    await db.commit()
    return JSONResponse({"ok": True, "name": bucket.name or ""})


@router.post("/buckets/{bucket_id}/move-to-trc")
async def move_bucket_to_trc(
    bucket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    try:
        uid = uuid.UUID(bucket_id)
    except Exception:
        raise HTTPException(400, "Invalid bucket ID")
    bucket = (await db.execute(select(Bucket).where(Bucket.id == uid))).scalar_one_or_none()
    if not bucket:
        raise HTTPException(404, "Bucket not found")
    bucket.status = "trc_pending"
    bucket.updated_at = app_now()
    # Also mark allocated so it appears in the Inventory Manager's
    # "Allocation — Buckets in Production" table — that table filters on
    # assigned_to_production, and "Move to Production" is exactly the action
    # that should populate it.
    if not bucket.assigned_to_production:
        bucket.assigned_to_production = True
        bucket.assigned_to_production_by = current_user.username
        bucket.assigned_to_production_at = app_now()
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/buckets/{bucket_id}/validate")
async def validate_bucket(
    bucket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    qty_received: int = Form(...),
):
    try:
        uid = uuid.UUID(bucket_id)
    except Exception:
        raise HTTPException(400, "Invalid bucket ID")
    bucket = (await db.execute(select(Bucket).where(Bucket.id == uid))).scalar_one_or_none()
    if not bucket:
        raise HTTPException(404, "Bucket not found")
    bucket.received_qty = qty_received
    bucket.status = "validated"
    bucket.updated_at = app_now()
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/buckets/{bucket_id}/assign")
async def assign_bucket(
    bucket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    department: str = Form(...),
    assigned_user_id: str = Form(...),
):
    try:
        uid = uuid.UUID(bucket_id)
    except Exception:
        raise HTTPException(400, "Invalid bucket ID")
    bucket = (await db.execute(select(Bucket).where(Bucket.id == uid))).scalar_one_or_none()
    if not bucket:
        raise HTTPException(404, "Bucket not found")

    try:
        user_uid = uuid.UUID(assigned_user_id)
    except Exception:
        raise HTTPException(400, "Invalid user ID")
    engineer = (await db.execute(select(User).where(User.id == user_uid))).scalar_one_or_none()
    if not engineer:
        raise HTTPException(404, "Engineer not found")

    devices = (await db.execute(
        select(Device).where(Device.bucket_id == uid, Device.is_active == True)
    )).scalars().all()

    target_stage = DEPT_TO_STAGE.get(department)
    new_stage = STAGE_ENUM.get(target_stage) if target_stage else None

    for device in devices:
        _from_wh = getattr(device, "warehouse", None) or "—"
        transfer = StockTransfer(
            device_id=device.id,
            transfer_type="transfer_to_trc",
            from_warehouse=_from_wh,
            to_warehouse=_from_wh,
            transferred_by=current_user.username,
            department=department,
            barcode=device.barcode,
            serial_no=device.serial_no,
            make=device.brand,
            model=device.model,
            ram=str(device.ram_gb) + " GB" if device.ram_gb else None,
            hdd=str(device.storage_gb) + " GB" if device.storage_gb else None,
            category=device.sub_category,
            product_stage=device.current_stage.value if device.current_stage else None,
            transfer_date=app_now(),
            notes=f"Assigned via Bucket {bucket.bucket_number}",
            created_by=current_user.username,
        )
        db.add(transfer)
        await db.flush()

        if new_stage:
            prev_stage = device.current_stage
            prev_mv = (await db.execute(
                select(StageMovement).where(
                    StageMovement.device_id == device.id,
                    StageMovement.to_stage == prev_stage,
                    StageMovement.exited_at == None,
                ).order_by(StageMovement.moved_at.desc())
            )).scalars().first()
            if prev_mv:
                prev_mv.exited_at = app_now()

            device.current_stage = new_stage
            device.updated_at = app_now()
            db.add(StageMovement(
                device_id=device.id, from_stage=prev_stage, to_stage=new_stage,
                moved_by=current_user.username,
                notes=f"Bucket {bucket.bucket_number} assigned to {engineer.full_name or engineer.username}",
            ))
            work_id = await _gen_work_id(db)
            db.add(WorkOrder(
                work_id=work_id, device_id=device.id, barcode=device.barcode,
                stage=target_stage, assigned_role=DEPT_TO_ROLE.get(department),
                assigned_user_id=engineer.id, assigned_username=engineer.username,
                assigned_name=engineer.full_name, status="pending",
                source_transfer_id=transfer.id, created_by=current_user.username,
            ))
            _label = f"{device.brand or ''} {device.model or ''}".strip()
            await create_notification(
                db, user_id=engineer.id,
                title="Device Assigned to You",
                message=(
                    f"{device.barcode}"
                    + (f" ({_label})" if _label else "")
                    + f" assigned from Bucket {bucket.bucket_number} for {department} (WorkID: {work_id})."
                ),
                notification_type="info",
                barcode=device.barcode,
                brand=device.brand,
                model=device.model,
                stage=new_stage.value if hasattr(new_stage, "value") else str(new_stage),
            )

    # Mark the bucket allocated so it appears in the Production Manager's
    # "Allocation — Buckets in L1/L2 Repair" table (that table filters on
    # assigned_to_production, the same flag the Inventory Manager side's
    # Assign-to-Production action sets — this endpoint is the L1/L2-specific
    # equivalent, so submitting this Assign Bucket modal should populate the
    # same allocation view).
    if devices and not bucket.assigned_to_production:
        bucket.assigned_to_production = True
        bucket.assigned_to_production_by = current_user.username
        bucket.assigned_to_production_at = app_now()

    await db.commit()
    return JSONResponse({"ok": True, "assigned": len(devices)})


@router.post("/devices/{barcode}/assign")
async def assign_device(
    barcode: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    department: str = Form(...),
    assigned_user_id: str = Form(...),
):
    """Production Manager's first table (item 23) — same Assign functionality
    and modal as the Allocation table's bucket-level Assign, scoped to one
    device instead of a whole bucket."""
    device = (await db.execute(select(Device).where(Device.barcode == barcode))).scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")

    try:
        user_uid = uuid.UUID(assigned_user_id)
    except Exception:
        raise HTTPException(400, "Invalid user ID")
    engineer = (await db.execute(select(User).where(User.id == user_uid))).scalar_one_or_none()
    if not engineer:
        raise HTTPException(404, "Engineer not found")

    target_stage = DEPT_TO_STAGE.get(department)
    new_stage = STAGE_ENUM.get(target_stage) if target_stage else None
    if not new_stage:
        raise HTTPException(400, "Invalid repair level")

    _from_wh = getattr(device, "warehouse", None) or "—"
    transfer = StockTransfer(
        device_id=device.id, transfer_type="transfer_to_trc",
        from_warehouse=_from_wh, to_warehouse=_from_wh,
        transferred_by=current_user.username, department=department,
        barcode=device.barcode, serial_no=device.serial_no,
        make=device.brand, model=device.model,
        ram=str(device.ram_gb) + " GB" if device.ram_gb else None,
        hdd=str(device.storage_gb) + " GB" if device.storage_gb else None,
        category=device.sub_category,
        product_stage=device.current_stage.value if device.current_stage else None,
        transfer_date=app_now(), notes=f"Assigned via Production Manager — {device.barcode}",
        created_by=current_user.username,
    )
    db.add(transfer)
    await db.flush()

    prev_stage = device.current_stage
    prev_mv = (await db.execute(
        select(StageMovement).where(
            StageMovement.device_id == device.id,
            StageMovement.to_stage == prev_stage,
            StageMovement.exited_at == None,
        ).order_by(StageMovement.moved_at.desc())
    )).scalars().first()
    if prev_mv:
        prev_mv.exited_at = app_now()

    device.current_stage = new_stage
    device.updated_at = app_now()
    db.add(StageMovement(
        device_id=device.id, from_stage=prev_stage, to_stage=new_stage,
        moved_by=current_user.username,
        notes=f"Assigned to {engineer.full_name or engineer.username}",
    ))
    work_id = await _gen_work_id(db)
    db.add(WorkOrder(
        work_id=work_id, device_id=device.id, barcode=device.barcode,
        stage=target_stage, assigned_role=DEPT_TO_ROLE.get(department),
        assigned_user_id=engineer.id, assigned_username=engineer.username,
        assigned_name=engineer.full_name, status="pending",
        source_transfer_id=transfer.id, created_by=current_user.username,
    ))
    _label = f"{device.brand or ''} {device.model or ''}".strip()
    await create_notification(
        db, user_id=engineer.id,
        title="Device Assigned to You",
        message=(f"{device.barcode}" + (f" ({_label})" if _label else "")
                 + f" assigned for {department} (WorkID: {work_id})."),
        notification_type="info",
        barcode=device.barcode, brand=device.brand, model=device.model,
        stage=new_stage.value if hasattr(new_stage, "value") else str(new_stage),
    )
    await db.commit()
    return JSONResponse({"ok": True, "work_id": work_id})


@router.post("/buckets/{bucket_id}/assign-to-production")
async def assign_bucket_to_production(
    bucket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Batch D Task 3 — Stock Inward Movement table 'Assign to Production' action.
    Marks the bucket assigned_to_production=True and moves all its devices'
    stage to DeviceStage.trc_production (the existing stage value for the
    TRC Production Manager page, reused rather than inventing a new one)."""
    try:
        uid = uuid.UUID(bucket_id)
    except Exception:
        raise HTTPException(400, "Invalid bucket ID")
    bucket = (await db.execute(select(Bucket).where(Bucket.id == uid))).scalar_one_or_none()
    if not bucket:
        raise HTTPException(404, "Bucket not found")
    if bucket.assigned_to_production:
        raise HTTPException(400, "Bucket already assigned to production")

    devices = (await db.execute(
        select(Device).where(Device.bucket_id == uid, Device.is_active == True)
    )).scalars().all()

    for device in devices:
        prev_stage = device.current_stage
        prev_mv = (await db.execute(
            select(StageMovement).where(
                StageMovement.device_id == device.id,
                StageMovement.to_stage == prev_stage,
                StageMovement.exited_at == None,
            ).order_by(StageMovement.moved_at.desc())
        )).scalars().first()
        if prev_mv:
            prev_mv.exited_at = app_now()
        device.current_stage = DeviceStage.trc_production
        device.updated_at = app_now()
        db.add(StageMovement(
            device_id=device.id, from_stage=prev_stage, to_stage=DeviceStage.trc_production,
            moved_by=current_user.username,
            notes=f"Bucket {bucket.bucket_number} assigned to Production by {current_user.username}",
        ))

    bucket.assigned_to_production = True
    bucket.assigned_to_production_by = current_user.username
    bucket.assigned_to_production_at = app_now()
    bucket.status = "trc_pending"
    bucket.updated_at = app_now()

    await db.commit()
    return JSONResponse({"ok": True, "assigned": len(devices)})


@router.post("/buckets/{bucket_id}/assign-to-engineer")
async def assign_bucket_to_engineer(
    bucket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Batch D Task 4 — Production Manager page Movement table 'Assign to
    Engineer' action. Moves all the bucket's devices into DeviceStage.l1 so
    they appear on templates/repair/l1.html's existing query
    (Device.current_stage == DeviceStage.l1), matching routers/repair.py's
    STAGE_MAP without any new plumbing on the L1 page."""
    try:
        uid = uuid.UUID(bucket_id)
    except Exception:
        raise HTTPException(400, "Invalid bucket ID")
    bucket = (await db.execute(select(Bucket).where(Bucket.id == uid))).scalar_one_or_none()
    if not bucket:
        raise HTTPException(404, "Bucket not found")

    devices = (await db.execute(
        select(Device).where(Device.bucket_id == uid, Device.is_active == True)
    )).scalars().all()

    for device in devices:
        prev_stage = device.current_stage
        prev_mv = (await db.execute(
            select(StageMovement).where(
                StageMovement.device_id == device.id,
                StageMovement.to_stage == prev_stage,
                StageMovement.exited_at == None,
            ).order_by(StageMovement.moved_at.desc())
        )).scalars().first()
        if prev_mv:
            prev_mv.exited_at = app_now()
        device.current_stage = DeviceStage.l1
        device.updated_at = app_now()
        db.add(StageMovement(
            device_id=device.id, from_stage=prev_stage, to_stage=DeviceStage.l1,
            moved_by=current_user.username,
            notes=f"Bucket {bucket.bucket_number} assigned to L1 Engineer by {current_user.username}",
        ))

    bucket.status = "validated"
    bucket.updated_at = app_now()

    await db.commit()
    return JSONResponse({"ok": True, "assigned": len(devices)})
