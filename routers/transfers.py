from datetime import datetime
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from templates_config import templates
from database import get_db
from models.user import User, UserRole
from models.device import Device
from models.lot import Lot
from models.stock_transfer import StockTransfer
from auth.dependencies import get_current_user, require_roles, verify_csrf, require_module_perm
from models.master import MasterData
from services.audit_engine import audit

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
    "L1/L2 Engineer",
    "L3 Engineer",
    "QC",
    "Sales",
    "Cosmetic Refurb",
    "Management",
]


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
    return templates.TemplateResponse("transfers/form.html", {
        "request": request, "device": device, "barcode": barcode,
        "warehouses": warehouses, "departments": DEPARTMENTS,
        "current_user": current_user, "error": None,
        "now": app_now(),
    })


@router.post("/transfers/new")
async def create_transfer(
    request: Request,
    barcode: str = Form(...),
    transfer_type: str = Form(...),
    from_warehouse: str = Form(...),
    to_warehouse: str = Form(...),
    transferred_by: str = Form(""),
    received_by: str = Form(""),
    department: str = Form(""),
    transfer_date: str = Form(""),
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

    transfer = StockTransfer(
        device_id=device.id,
        transfer_type=transfer_type,
        from_warehouse=from_warehouse,
        to_warehouse=to_warehouse,
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
    return RedirectResponse(url=f"/transfers?success=Transfer+recorded+for+{barcode}", status_code=302)


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
