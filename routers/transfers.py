import uuid
from datetime import datetime
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func

from templates_config import templates
from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceStage, StageMovement
from models.lot import Lot
from models.stock_transfer import StockTransfer
from models.work_order import WorkOrder
from auth.dependencies import get_current_user, require_roles, verify_csrf, require_module_perm
from models.master import MasterData
from services.audit_engine import audit
from services.notifications import create_notification

router = APIRouter(tags=["transfers"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.inventory_manager)

FALLBACK_WAREHOUSES = [
    "TRC 1st Floor",
    "TRC 2nd Floor",
    "TRC 3rd Floor",
    "Bluemonk House Showroom",
    "Bluemonk Showroom",
    "Other",
]

DEPARTMENTS = [
    "IQC Inspector",
    "L1 Engineer",
    "L2 Engineer",
    "L3 Engineer",
    "QC Inspector",
    "Inventory Manager",
    "Sales Manager",
    "Spare Parts Manager",
]

# Departments that map to a repair stage + create a WorkOrder when a user is assigned
DEPT_TO_STAGE = {"L1 Engineer": "l1", "L2 Engineer": "l2", "L3 Engineer": "l3"}
DEPT_TO_ROLE = {
    "IQC Inspector": "iqc_inspector", "L1 Engineer": "l1_engineer",
    "L2 Engineer": "l2_engineer", "L3 Engineer": "l3_engineer",
    "QC Inspector": "qc_inspector", "Inventory Manager": "inventory_manager",
    "Sales Manager": "sales_manager", "Spare Parts Manager": "spare_parts_manager",
}
STAGE_ENUM = {"l1": DeviceStage.l1, "l2": DeviceStage.l2, "l3": DeviceStage.l3}


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
    result = await db.execute(stmt.limit(500))
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
    users_by_role = await _engineers_by_role(db)
    return templates.TemplateResponse("transfers/form.html", {
        "request": request, "device": device, "barcode": barcode,
        "warehouses": warehouses, "departments": DEPARTMENTS,
        "users_by_role": users_by_role, "dept_to_role": DEPT_TO_ROLE,
        "current_user": current_user, "error": None,
        "now": app_now(),
    })


@router.post("/transfers/new")
async def create_transfer(
    request: Request,
    barcode: str = Form(...),
    transfer_type: str = Form(...),
    from_warehouse: str = Form(""),
    to_warehouse: str = Form(""),
    transferred_by: str = Form(""),
    received_by: str = Form(""),
    department: str = Form(""),
    transfer_date: str = Form(""),
    assigned_user_id: str = Form(""),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    _perm: User = Depends(require_module_perm("transfers", "add")),
):
    # Lookup device
    result = await db.execute(
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id, isouter=True)
        .where(Device.barcode == barcode)
    )
    row = result.first()
    if not row:
        return templates.TemplateResponse("transfers/form.html", {
            "request": request, "device": None, "barcode": barcode,
            "warehouses": FALLBACK_WAREHOUSES, "departments": DEPARTMENTS,
            "current_user": current_user, "error": f"Device '{barcode}' not found",
        })
    device, lot_number = row

    try:
        t_date = datetime.strptime(transfer_date, "%Y-%m-%d") if transfer_date else app_now()
    except Exception:
        t_date = app_now()

    # from/to_warehouse are NOT NULL. For a department/engineer assignment the user
    # picks no destination warehouse → fall back so we never insert NULL (was a 500).
    _from_wh = from_warehouse or getattr(device, "warehouse", None) or "—"
    _to_wh = to_warehouse or _from_wh
    transfer = StockTransfer(
        device_id=device.id,
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
    # Update device warehouse field if it exists
    if hasattr(device, "warehouse") and to_warehouse:
        device.warehouse = to_warehouse
        device.updated_at = app_now()

    db.add(transfer)

    # ── Work assignment: assigning to an L1/L2/L3 engineer creates a 12-digit
    #    WorkID and moves the device into that repair stage so the barcode shows
    #    in the engineer's repair Pending list (with WorkID + Timeline). ─────────
    work_id = None
    target_stage = DEPT_TO_STAGE.get(department)
    if target_stage and assigned_user_id:
        try:
            uid = uuid.UUID(assigned_user_id)
        except Exception:
            uid = None
        u = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none() if uid else None
        if u:
            new_stage = STAGE_ENUM[target_stage]
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
                notes=f"Assigned to {u.full_name or u.username} via Stock Transfer",
            ))
            work_id = await _gen_work_id(db)
            db.add(WorkOrder(
                work_id=work_id, device_id=device.id, barcode=device.barcode,
                stage=target_stage, assigned_role=DEPT_TO_ROLE.get(department),
                assigned_user_id=u.id, assigned_username=u.username,
                assigned_name=u.full_name, status="pending",
                source_transfer_id=transfer.id, created_by=current_user.username,
            ))
            # Notify the assigned engineer
            _device_label = f"{device.brand or ''} {device.model or ''}".strip()
            await create_notification(
                db,
                user_id=u.id,
                title="Device Assigned to You",
                message=(
                    f"{device.barcode}"
                    + (f" ({_device_label})" if _device_label else "")
                    + f" has been assigned to you for {department} (WorkID: {work_id})."
                ),
                notification_type="info",
                barcode=device.barcode,
                brand=device.brand,
                model=device.model,
                stage=new_stage.value if hasattr(new_stage, "value") else str(new_stage),
            )

    await audit(db, user=current_user, action="STOCK_TRANSFER",
                table_name="stock_transfers",
                record_id=None,
                new_value={
                    "barcode": barcode,
                    "transfer_type": transfer_type,
                    "from_warehouse": from_warehouse,
                    "to_warehouse": to_warehouse,
                },
                request=request)
    await db.commit()
    if work_id:
        msg = f"Moved+{barcode}+to+{department}+—+WorkID+{work_id}"
    else:
        msg = f"Transfer+recorded+for+{barcode}"
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
