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
from auth.dependencies import get_current_user, require_roles, verify_csrf
from services.notifications import create_notification

router = APIRouter(tags=["buckets"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.inventory_manager)

FALLBACK_WAREHOUSES = [
    "TRC 1st Floor", "TRC 2nd Floor", "TRC 3rd Floor",
    "Bluemonk House Showroom", "Bluemonk Showroom", "Other",
]

DEPT_TO_STAGE = {"L1 Engineer": "l1", "L2 Engineer": "l2"}
DEPT_TO_ROLE  = {"L1 Engineer": "l1_engineer", "L2 Engineer": "l2_engineer"}
STAGE_ENUM    = {"l1": DeviceStage.l1, "l2": DeviceStage.l2}


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

    return JSONResponse([{
        "id": str(b.id),
        "bucket_number": b.bucket_number,
        "name": b.name or "",
        "location": b.location or "",
        "category": b.category or "",
        "status": b.status,
        "device_count": count_map.get(str(b.id), 0),
        "received_qty": b.received_qty,
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

    bucket = Bucket(
        bucket_number=_new_bucket_number(),
        name=name.strip() or None,
        location=location.strip() or None,
        category=category,
        status="stock_in",
        created_by=current_user.username,
    )
    db.add(bucket)
    await db.flush()

    for d in devices:
        d.bucket_id = bucket.id
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

    await db.commit()
    return JSONResponse({"ok": True, "assigned": len(devices)})
