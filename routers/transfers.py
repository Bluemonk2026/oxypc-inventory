import uuid
from datetime import datetime
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func

from templates_config import templates
from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceStage, StageMovement, DeviceGrade
from models.lot import Lot
from models.bucket import Bucket
from models.location import StorageLocation
from models.sales import Sale
from models.stock_transfer import StockTransfer
from models.work_order import WorkOrder
from auth.dependencies import get_current_user, require_roles, verify_csrf, require_module_perm
from models.master import MasterData
from services.audit_engine import audit
from services.notifications import create_notification
from utils.warranty import warranty_status_for_sale

router = APIRouter(tags=["transfers"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.inventory_manager,
                         UserRole.qc_inspector, UserRole.sales_manager)

FALLBACK_WAREHOUSES = [
    "TRC 1st Floor",
    "TRC 2nd Floor",
    "TRC 3rd Floor",
    "Bluemonk House Showroom",
    "Bluemonk Showroom",
    "Other",
]

DEPARTMENTS = [
    "IQC Handler",
    "L1 Engineer",
    "L2 Engineer",
    "L3 Engineer",
    "QC Handler",
    "Inventory Manager",
    "Sales Manager",
    "Parts Manager",
]

# Departments that map to a repair stage + create a WorkOrder when a user is assigned
# All repair assignment lands in the merged L1/L2 queue (/repair/l1). The l2/l3 stages are
# retired and have no page, so mapping a department to them would strand the device.
DEPT_TO_STAGE = {"L1 Engineer": "l1", "L2 Engineer": "l1", "L3 Engineer": "l1"}
DEPT_TO_ROLE = {
    "IQC Handler": "iqc_inspector", "L1 Engineer": "l1_engineer",
    "L2 Engineer": "l2_engineer", "L3 Engineer": "l3_engineer",
    "QC Handler": "qc_inspector", "Inventory Manager": "inventory_manager",
    "Sales Manager": "sales_manager", "Parts Manager": "spare_parts_manager",
}
STAGE_ENUM = {"l1": DeviceStage.l1}


async def _gen_work_id(db: AsyncSession) -> str:
    """Generate a unique 12-digit numeric WorkID."""
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


async def _resolve_assigned_user(db: AsyncSession, assigned_user_id: str):
    """Resolve the 'Assign To Employee' selection to a User, or None."""
    if not assigned_user_id:
        return None
    try:
        uid = uuid.UUID(assigned_user_id)
    except Exception:
        return None
    return (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()


async def _engineers_by_role(db: AsyncSession) -> dict:
    """{role_value: [{id, name, username}]} for active L1/L2/L3 engineers."""
    rows = (await db.execute(
        select(User).where(
            User.role.in_([UserRole.l1_engineer, UserRole.l2_engineer, UserRole.l3_engineer]),
            User.status == True,
        ).order_by(User.full_name)
    )).scalars().all()
    out = {"l1_engineer": [], "l2_engineer": [], "l3_engineer": []}
    for u in rows:
        out.setdefault(u.role.value, []).append(
            {"id": str(u.id), "name": u.full_name or u.username, "username": u.username}
        )
    return out


@router.get("/transfers", response_class=HTMLResponse)
async def list_transfers(
    request: Request,
    q: str = "",
    transfer_type: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(StockTransfer).order_by(desc(StockTransfer.transfer_date))
    if q:
        stmt = stmt.where(StockTransfer.barcode.ilike(f"%{q}%"))
    if transfer_type:
        stmt = stmt.where(StockTransfer.transfer_type == transfer_type)
    result = await db.execute(stmt)
    transfers = result.scalars().all()
    return templates.TemplateResponse("transfers/list.html", {
        "request": request, "transfers": transfers, "q": q,
        "transfer_type": transfer_type, "current_user": current_user,
    })


@router.get("/transfers/new", response_class=HTMLResponse)
async def new_transfer_form(
    request: Request,
    barcode: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    device = None
    if barcode:
        result = await db.execute(
            select(Device, Lot.lot_number)
            .join(Lot, Device.lot_id == Lot.id, isouter=True)
            .where(Device.barcode == barcode)
        )
        row = result.first()
        if row:
            device, lot_number = row
            device._lot_number = lot_number
    # Load warehouses from Master Data (category='warehouse', active only)
    wh_result = await db.execute(
        select(MasterData.value)
        .where(MasterData.category == "warehouse", MasterData.is_active == True)
        .order_by(MasterData.display_order, MasterData.value)
    )
    warehouses = [r[0] for r in wh_result.all()] or FALLBACK_WAREHOUSES
    all_users = (await db.execute(
        select(User).where(User.status == True).order_by(User.full_name)
    )).scalars().all()
    return templates.TemplateResponse("transfers/form.html", {
        "request": request, "device": device, "barcode": barcode,
        "warehouses": warehouses, "departments": DEPARTMENTS,
        "all_users": all_users,
        "current_user": current_user, "error": None,
        "now": app_now(),
    })


# ─────────────────────────────────────────────────────────────────────────────
#  Bucket / Lot lookup APIs — power the "Move Bucket" / "Move Lot" tabs
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/transfers/api/bucket-lookup")
async def bucket_lookup(
    unit_id: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Look up a StorageLocation by unit_id (the 'Bucket ID' the user scans/types),
    then summarize the devices currently sitting at that location: count of tag
    numbers and grade (homogeneous grade shown, else 'Mixed')."""
    if not unit_id:
        return JSONResponse({"found": False})
    loc = (await db.execute(
        select(StorageLocation).where(StorageLocation.unit_id.ilike(unit_id.strip()))
    )).scalar_one_or_none()
    if not loc:
        return JSONResponse({"found": False})

    devices = (await db.execute(
        select(Device).where(Device.location_id == loc.id, Device.is_active == True)
    )).scalars().all()

    grades = {d.grade.value for d in devices if d.grade}
    if len(grades) == 1:
        grade_display = grades.pop()
    elif len(grades) == 0:
        grade_display = "—"
    else:
        grade_display = "Mixed"

    return JSONResponse({
        "found": True,
        "location_id": str(loc.id),
        "unit_id": loc.unit_id,
        "location_type": loc.unit_type_label,
        "zone": loc.zone.value,
        "tag_count": len(devices),
        "grade": grade_display,
        "barcodes": [d.barcode for d in devices],
    })


@router.get("/transfers/api/lot-lookup")
async def lot_lookup(
    lot_number: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Look up a Lot by lot_number and summarize its member devices: dates
    (stock-in / final QC / sold), Model, Grade, and Warranty Status. If devices
    are heterogeneous, Model/Grade fall back to 'Mixed' and Warranty Status
    reflects the most recent sale among lot devices (or 'Mixed' if inconsistent)."""
    if not lot_number:
        return JSONResponse({"found": False})
    lot = (await db.execute(
        select(Lot).where(Lot.lot_number.ilike(lot_number.strip()))
    )).scalar_one_or_none()
    if not lot:
        return JSONResponse({"found": False})

    devices = (await db.execute(
        select(Device).where(Device.lot_id == lot.id, Device.is_active == True)
    )).scalars().all()

    models = {d.model for d in devices if d.model}
    model_display = models.pop() if len(models) == 1 else ("Mixed" if len(models) > 1 else "—")

    grades = {d.grade.value for d in devices if d.grade}
    grade_display = grades.pop() if len(grades) == 1 else ("Mixed" if len(grades) > 1 else "—")

    # Representative dates: earliest stock-in movement, earliest final_qc movement,
    # most recent sale among this lot's devices.
    device_ids = [d.id for d in devices]
    stock_in_date = None
    final_qc_date = None
    sold_on_date = None
    warranty_display = "—"

    if device_ids:
        stock_in_row = (await db.execute(
            select(func.min(StageMovement.moved_at)).where(
                StageMovement.device_id.in_(device_ids),
                StageMovement.to_stage == DeviceStage.stock_in,
            )
        )).scalar()
        stock_in_date = stock_in_row

        final_qc_row = (await db.execute(
            select(func.min(StageMovement.moved_at)).where(
                StageMovement.device_id.in_(device_ids),
                StageMovement.to_stage == DeviceStage.final_qc,
            )
        )).scalar()
        final_qc_date = final_qc_row

        sales = (await db.execute(
            select(Sale).where(Sale.device_id.in_(device_ids)).order_by(desc(Sale.sold_at))
        )).scalars().all()
        if sales:
            sold_on_date = sales[0].sold_at
            statuses = {warranty_status_for_sale(s) for s in sales}
            warranty_display = statuses.pop() if len(statuses) == 1 else "Mixed"

    return JSONResponse({
        "found": True,
        "lot_id": str(lot.id),
        "lot_number": lot.lot_number,
        "tag_count": len(devices),
        "model": model_display,
        "grade": grade_display,
        "stock_in_date": stock_in_date.strftime("%Y-%m-%d") if stock_in_date else "—",
        "final_qc_date": final_qc_date.strftime("%Y-%m-%d") if final_qc_date else "—",
        "sold_on_date": sold_on_date.strftime("%Y-%m-%d") if sold_on_date else "—",
        "warranty_status": warranty_display,
        "barcodes": [d.barcode for d in devices],
    })


@router.post("/transfers/new")
async def create_transfer(
    request: Request,
    barcode: list[str] = Form(...),
    transfer_type: str = Form(...),
    from_warehouse: str = Form(""),
    to_warehouse: str = Form(""),
    transferred_by: str = Form(""),
    received_by: str = Form(""),
    department: str = Form(""),
    transfer_date: str = Form(""),
    assigned_user_id: str = Form(""),
    notes: str = Form(""),
    to_location_id: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    _perm: User = Depends(require_module_perm("transfers", "add")),
):
    """Move Item tab — scanned barcodes are accumulated client-side into a
    list (see stockScan-style multi-scan JS); one StockTransfer row is
    created per barcode with the same transfer options applied to all."""
    barcodes = [b.strip() for b in barcode if b and b.strip()]
    if not barcodes:
        return RedirectResponse(url="/transfers/new?error=No+tag+numbers+scanned", status_code=302)

    try:
        t_date = datetime.strptime(transfer_date, "%Y-%m-%d") if transfer_date else app_now()
    except Exception:
        t_date = app_now()

    assign_uid = None
    if assigned_user_id:
        try:
            assign_uid = uuid.UUID(assigned_user_id)
        except Exception:
            assign_uid = None
    assigned_user = (
        (await db.execute(select(User).where(User.id == assign_uid))).scalar_one_or_none()
        if assign_uid else None
    )
    if not assigned_user:
        return RedirectResponse(url="/transfers/new?error=Select+an+employee+to+assign", status_code=302)

    moved, not_found, work_ids = [], [], []
    for bc in barcodes:
        result = await db.execute(
            select(Device, Lot.lot_number)
            .join(Lot, Device.lot_id == Lot.id, isouter=True)
            .where(Device.barcode == bc)
        )
        row = result.first()
        if not row:
            not_found.append(bc)
            continue
        device, lot_number = row

        _from_wh = from_warehouse or getattr(device, "warehouse", None) or "—"
        _to_wh = to_warehouse or _from_wh
        transfer = StockTransfer(
            device_id=device.id,
            move_kind="device",
            to_location_id=None,
            transfer_type=transfer_type,
            from_warehouse=_from_wh,
            to_warehouse=_to_wh,
            transferred_by=transferred_by or current_user.username,
            received_by=received_by or None,
            department=department or None,
            barcode=device.barcode,
            serial_no=device.serial_no,
            make=device.brand,
            model=device.model,
            cpu=getattr(device, "cpu", None),
            generation=getattr(device, "generation", None),
            ram=str(device.ram_gb) + " GB" if device.ram_gb else None,
            hdd=str(device.storage_gb) + " GB" if device.storage_gb else None,
            category=device.sub_category,
            lot_number=lot_number,
            product_stage=device.current_stage.value if device.current_stage else None,
            transfer_date=t_date,
            notes=notes or None,
            created_by=current_user.username,
        )
        if hasattr(device, "warehouse") and to_warehouse:
            device.warehouse = to_warehouse
            device.updated_at = app_now()
        db.add(transfer)
        await db.flush()

        # ── Assignment only: record the device against the chosen employee via a
        #    WorkOrder. No device stage move and no repair-stage logic. ─────────
        u = assigned_user
        work_id = await _gen_work_id(db)
        db.add(WorkOrder(
            work_id=work_id, device_id=device.id, barcode=device.barcode,
            stage="asgn", assigned_role=u.role.value if u.role else None,
            assigned_user_id=u.id, assigned_username=u.username,
            assigned_name=u.full_name, status="pending",
            source_transfer_id=transfer.id, created_by=current_user.username,
        ))
        work_ids.append(work_id)
        _device_label = f"{device.brand or ''} {device.model or ''}".strip()
        await create_notification(
            db, user_id=u.id, title="Device Assigned to You",
            message=(
                f"{device.barcode}"
                + (f" ({_device_label})" if _device_label else "")
                + f" has been assigned to you (WorkID: {work_id})."
            ),
            notification_type="info",
            barcode=device.barcode, brand=device.brand, model=device.model,
        )
        moved.append(bc)

    await audit(db, user=current_user, action="STOCK_TRANSFER",
                table_name="stock_transfers", record_id=None,
                new_value={
                    "barcodes": moved, "transfer_type": transfer_type,
                    "from_warehouse": from_warehouse, "to_warehouse": to_warehouse,
                },
                request=request)
    await db.commit()

    if not moved:
        return RedirectResponse(
            url=f"/transfers/new?error=None+of+the+scanned+tag+numbers+were+found:+{','.join(not_found)}",
            status_code=302)
    msg = f"Moved+{len(moved)}+tag+number(s)"
    if work_ids:
        msg += f"+—+{len(work_ids)}+WorkID(s)+created"
    if not_found:
        msg += f"+({len(not_found)}+not+found)"
    return RedirectResponse(url=f"/transfers?success={msg}", status_code=302)


async def _move_devices_bulk(
    db: AsyncSession, request: Request, current_user: User,
    devices: list, move_kind: str, bucket_id, lot_id, group_label: str,
    transfer_type: str, assigned_user: User, transfer_date: str,
    transferred_by: str, received_by: str, notes: str,
):
    """Shared bulk-assign logic for Move Bucket / Move Lot tabs — creates one
    StockTransfer row per member device and a WorkOrder recording the device
    against the chosen employee. No device stage move, no repair-stage logic."""
    try:
        t_date = datetime.strptime(transfer_date, "%Y-%m-%d") if transfer_date else app_now()
    except Exception:
        t_date = app_now()

    moved = []
    for device in devices:
        lot_number = None
        if getattr(device, "lot_id", None):
            lot_row = (await db.execute(select(Lot.lot_number).where(Lot.id == device.lot_id))).scalar()
            lot_number = lot_row

        _from_wh = getattr(device, "warehouse", None) or "—"
        transfer = StockTransfer(
            device_id=device.id,
            move_kind=move_kind,
            bucket_id=bucket_id,
            lot_id=lot_id,
            to_location_id=None,
            transfer_type=transfer_type,
            from_warehouse=_from_wh,
            to_warehouse=_from_wh,
            transferred_by=transferred_by or current_user.username,
            received_by=received_by or None,
            department=None,
            barcode=device.barcode,
            serial_no=device.serial_no,
            make=device.brand,
            model=device.model,
            cpu=getattr(device, "cpu", None),
            generation=getattr(device, "generation", None),
            ram=str(device.ram_gb) + " GB" if device.ram_gb else None,
            hdd=str(device.storage_gb) + " GB" if device.storage_gb else None,
            category=device.sub_category,
            lot_number=lot_number,
            product_stage=device.current_stage.value if device.current_stage else None,
            transfer_date=t_date,
            notes=notes or None,
            created_by=current_user.username,
        )
        db.add(transfer)
        await db.flush()

        work_id = await _gen_work_id(db)
        db.add(WorkOrder(
            work_id=work_id, device_id=device.id, barcode=device.barcode,
            stage="asgn", assigned_role=assigned_user.role.value if assigned_user.role else None,
            assigned_user_id=assigned_user.id, assigned_username=assigned_user.username,
            assigned_name=assigned_user.full_name, status="pending",
            source_transfer_id=transfer.id, created_by=current_user.username,
        ))
        _device_label = f"{device.brand or ''} {device.model or ''}".strip()
        await create_notification(
            db, user_id=assigned_user.id, title="Device Assigned to You",
            message=(
                f"{device.barcode}"
                + (f" ({_device_label})" if _device_label else "")
                + f" has been assigned to you (WorkID: {work_id})."
            ),
            notification_type="info",
            barcode=device.barcode, brand=device.brand, model=device.model,
        )
        moved.append(device.barcode)

    await audit(db, user=current_user, action="STOCK_TRANSFER_BULK",
                table_name="stock_transfers", record_id=None,
                new_value={
                    "move_kind": move_kind, "group": group_label,
                    "transfer_type": transfer_type, "device_count": len(moved),
                },
                request=request)
    await db.commit()
    return moved


@router.post("/transfers/new/bucket")
async def create_bucket_transfer(
    request: Request,
    unit_id: list[str] = Form(...),
    transfer_type: str = Form(...),
    assigned_user_id: str = Form(""),
    department: str = Form(""),
    transfer_date: str = Form(""),
    transferred_by: str = Form(""),
    received_by: str = Form(""),
    notes: str = Form(""),
    to_location_id: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    _perm: User = Depends(require_module_perm("transfers", "add")),
):
    """Move Bucket tab — one or more scanned bucket/location unit IDs; assigns
    every active device at those locations to the chosen employee."""
    unit_ids = [u.strip() for u in unit_id if u and u.strip()]
    if not unit_ids:
        return RedirectResponse(url="/transfers/new?error=No+bucket+IDs+scanned", status_code=302)

    assigned_user = await _resolve_assigned_user(db, assigned_user_id)
    if not assigned_user:
        return RedirectResponse(url="/transfers/new?error=Select+an+employee+to+assign", status_code=302)

    total_moved, not_found = [], []
    for uid in unit_ids:
        loc = (await db.execute(
            select(StorageLocation).where(StorageLocation.unit_id.ilike(uid))
        )).scalar_one_or_none()
        if not loc:
            not_found.append(uid)
            continue
        devices = (await db.execute(
            select(Device).where(Device.location_id == loc.id, Device.is_active == True)
        )).scalars().all()
        if not devices:
            continue
        moved = await _move_devices_bulk(
            db, request, current_user, devices, "bucket", None, None, uid,
            transfer_type, assigned_user, transfer_date, transferred_by, received_by,
            notes,
        )
        total_moved.extend(moved)

    if not total_moved:
        return RedirectResponse(
            url=f"/transfers/new?error=No+active+devices+found+for+bucket(s):+{','.join(unit_ids)}",
            status_code=302)
    msg = f"Moved+{len(total_moved)}+device(s)+from+{len(unit_ids) - len(not_found)}+bucket(s)"
    if not_found:
        msg += f"+({len(not_found)}+bucket(s)+not+found)"
    return RedirectResponse(url=f"/transfers?success={msg}", status_code=302)


@router.post("/transfers/new/lot")
async def create_lot_transfer(
    request: Request,
    lot_number: list[str] = Form(...),
    transfer_type: str = Form(...),
    assigned_user_id: str = Form(""),
    department: str = Form(""),
    transfer_date: str = Form(""),
    transferred_by: str = Form(""),
    received_by: str = Form(""),
    notes: str = Form(""),
    to_location_id: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    _perm: User = Depends(require_module_perm("transfers", "add")),
):
    """Move Lot tab — one or more scanned lot numbers; assigns every active
    member device of each lot to the chosen employee."""
    lot_numbers = [n.strip() for n in lot_number if n and n.strip()]
    if not lot_numbers:
        return RedirectResponse(url="/transfers/new?error=No+lot+numbers+scanned", status_code=302)

    assigned_user = await _resolve_assigned_user(db, assigned_user_id)
    if not assigned_user:
        return RedirectResponse(url="/transfers/new?error=Select+an+employee+to+assign", status_code=302)

    total_moved, not_found = [], []
    for ln in lot_numbers:
        lot = (await db.execute(
            select(Lot).where(Lot.lot_number.ilike(ln))
        )).scalar_one_or_none()
        if not lot:
            not_found.append(ln)
            continue
        devices = (await db.execute(
            select(Device).where(Device.lot_id == lot.id, Device.is_active == True)
        )).scalars().all()
        if not devices:
            continue
        moved = await _move_devices_bulk(
            db, request, current_user, devices, "lot", None, lot.id, ln,
            transfer_type, assigned_user, transfer_date, transferred_by, received_by,
            notes,
        )
        total_moved.extend(moved)

    if not total_moved:
        return RedirectResponse(
            url=f"/transfers/new?error=No+active+devices+found+for+lot(s):+{','.join(lot_numbers)}",
            status_code=302)
    msg = f"Moved+{len(total_moved)}+device(s)+from+{len(lot_numbers) - len(not_found)}+lot(s)"
    if not_found:
        msg += f"+({len(not_found)}+lot(s)+not+found)"
    return RedirectResponse(url=f"/transfers?success={msg}", status_code=302)


@router.get("/transfers/{transfer_id}", response_class=HTMLResponse)
async def transfer_detail(
    transfer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(StockTransfer).where(StockTransfer.id == transfer_id))
    transfer = result.scalar_one_or_none()
    if not transfer:
        raise HTTPException(404)
    return templates.TemplateResponse("transfers/detail.html", {
        "request": request, "transfer": transfer, "current_user": current_user,
    })
