"""
Device Management — Search, Detail, Edit
Provides a global inventory browser and per-device history view.
"""
from templates_config import templates
import csv, io, uuid as uuid_module
from datetime import datetime
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func, and_
from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceGrade, DeviceStage, StageMovement, STAGE_LABELS
from models.lot import Lot
from models.repair import RepairJob
from models.qc import QCCheck
from models.spare_parts import SparePartConsumption, SparePart
from models.location import DeviceLocationLog, StorageLocation, LocationAction
from models.iqc_inspection import IQCInspection
from auth.dependencies import get_current_user, require_roles, verify_csrf

router = APIRouter(prefix="/devices", tags=["devices"], dependencies=[Depends(verify_csrf)])
# All logged-in users can search/view; only admin+invmgr can edit
view_allowed = get_current_user
edit_allowed = require_roles(UserRole.admin, UserRole.inventory_manager)


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _build_location_map(db: AsyncSession, device_ids: list) -> dict:
    """Return {str(device_id): {unit_id, action, actor_name}} for a batch of devices."""
    if not device_ids:
        return {}
    try:
        uuid_ids = [uuid_module.UUID(did) if isinstance(did, str) else did for did in device_ids]
    except (ValueError, AttributeError):
        return {}
    sub = (
        select(
            DeviceLocationLog.device_id,
            func.max(DeviceLocationLog.logged_at).label("latest"),
        )
        .group_by(DeviceLocationLog.device_id)
        .subquery()
    )
    rows = await db.execute(
        select(
            DeviceLocationLog.device_id,
            StorageLocation.unit_id,
            DeviceLocationLog.action,
            DeviceLocationLog.actor_name,
        )
        .join(sub, and_(
            DeviceLocationLog.device_id == sub.c.device_id,
            DeviceLocationLog.logged_at == sub.c.latest,
        ))
        .outerjoin(StorageLocation, DeviceLocationLog.location_id == StorageLocation.id)
        .where(DeviceLocationLog.device_id.in_(uuid_ids))
    )
    loc_map = {}
    for device_id, unit_id, action, actor_name in rows.all():
        loc_map[str(device_id)] = {
            "unit_id": unit_id,
            "action": action.value if action else None,
            "actor_name": actor_name,
        }
    return loc_map


async def _get_device_or_404(barcode: str, db: AsyncSession) -> Device:
    result = await db.execute(
        select(Device).where(Device.barcode == barcode)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(404, f"Device '{barcode}' not found")
    return device


# ── 1. INVENTORY SEARCH ──────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def device_search(
    request: Request,
    q: str = "",
    stage: str = "",
    lot: str = "",
    grade: str = "",
    category: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(view_allowed),
):
    """Global inventory browser — search across all stages."""
    query = (
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.is_trashed == False)
    )

    filters = []
    if q:
        q_like = f"%{q}%"
        filters.append(or_(
            Device.barcode.ilike(q_like),
            Device.brand.ilike(q_like),
            Device.model.ilike(q_like),
            Device.serial_no.ilike(q_like),
            Device.cpu.ilike(q_like),
            Device.grn_number.ilike(q_like),
        ))
    if stage:
        try:
            filters.append(Device.current_stage == DeviceStage(stage))
        except ValueError:
            pass
    if lot:
        filters.append(Lot.lot_number.ilike(f"%{lot}%"))
    if grade:
        filters.append(Device.grade == grade)
    if category:
        filters.append(Device.sub_category == category)

    for f in filters:
        query = query.where(f)

    query = query.order_by(Device.updated_at.desc()).limit(500)
    result = await db.execute(query)
    devices = result.all()

    # Lot list for filter dropdown
    lots_result = await db.execute(select(Lot).order_by(Lot.lot_number))
    lots = lots_result.scalars().all()

    # Current location per device (single batch query)
    device_ids = [d.id for d, _ in devices]  # UUID objects
    location_map = await _build_location_map(db, device_ids)

    return templates.TemplateResponse("devices/list.html", {
        "request": request, "current_user": current_user,
        "devices": devices, "lots": lots,
        "stages": DeviceStage, "stage_labels": STAGE_LABELS,
        "q": q, "stage": stage, "lot": lot, "grade": grade, "category": category,
        "total": len(devices),
        "location_map": location_map,
    })


@router.get("/export")
async def export_devices(
    q: str = "",
    stage: str = "",
    lot: str = "",
    grade: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(view_allowed),
):
    """Export device search results as CSV."""
    query = select(Device, Lot.lot_number).join(Lot, Device.lot_id == Lot.id)
    filters = []
    if q:
        q_like = f"%{q}%"
        filters.append(or_(
            Device.barcode.ilike(q_like), Device.brand.ilike(q_like),
            Device.model.ilike(q_like), Device.serial_no.ilike(q_like),
        ))
    if stage:
        try:
            filters.append(Device.current_stage == DeviceStage(stage))
        except ValueError:
            pass
    if lot:
        filters.append(Lot.lot_number.ilike(f"%{lot}%"))
    if grade:
        filters.append(Device.grade == grade)
    for f in filters:
        query = query.where(f)
    query = query.order_by(Device.updated_at.desc())
    result = await db.execute(query)
    rows = result.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Barcode", "Lot", "GRN", "Sub-Category", "Brand", "Model", "Device Type",
        "Serial No", "CPU", "Generation", "RAM GB", "SSD GB", "Storage Type",
        "HDD GB", "Screen Size", "Battery %", "BIOS Pwd", "Color",
        "Grade", "Stage", "Floor", "Warehouse", "Notes", "Created", "Updated"
    ])
    for device, lot_number in rows:
        writer.writerow([
            device.barcode, lot_number, device.grn_number, device.sub_category,
            device.brand, device.model, device.device_type, device.serial_no,
            device.cpu, device.generation, device.ram_gb, device.storage_gb,
            device.storage_type, device.hdd_capacity_gb, device.screen_size,
            device.battery_health_pct, "Yes" if device.bios_password else "No",
            device.color, device.grade,
            STAGE_LABELS.get(device.current_stage, device.current_stage),
            device.floor, device.warehouse, device.notes,
            device.created_at.strftime("%d-%m-%Y %H:%M") if device.created_at else "",
            device.updated_at.strftime("%d-%m-%Y %H:%M") if device.updated_at else "",
        ])
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=devices_export.csv"},
    )


# ── 2. DEVICE DETAIL ─────────────────────────────────────────────────────────

@router.get("/{barcode}", response_class=HTMLResponse)
async def device_detail(
    barcode: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(view_allowed),
):
    """Full device profile — specs, stage timeline, repairs, QC, parts consumed."""
    device = await _get_device_or_404(barcode, db)

    # Lot
    lot_result = await db.execute(select(Lot).where(Lot.id == device.lot_id))
    lot = lot_result.scalar_one_or_none()

    # Stage movements (chronological)
    movements_result = await db.execute(
        select(StageMovement)
        .where(StageMovement.device_id == device.id)
        .order_by(StageMovement.moved_at.asc())
    )
    movements = movements_result.scalars().all()

    # Repair jobs
    repairs_result = await db.execute(
        select(RepairJob)
        .where(RepairJob.device_id == device.id)
        .order_by(RepairJob.started_at.desc())
    )
    repairs = repairs_result.scalars().all()

    # QC checks
    qc_result = await db.execute(
        select(QCCheck)
        .where(QCCheck.device_id == device.id)
        .order_by(QCCheck.checked_at.desc())
    )
    qc_checks = qc_result.scalars().all()

    # Spare parts consumed
    parts_result = await db.execute(
        select(SparePartConsumption, SparePart.name, SparePart.category)
        .join(SparePart, SparePartConsumption.part_id == SparePart.id)
        .where(SparePartConsumption.device_id == device.id)
        .order_by(SparePartConsumption.used_at.desc())
    )
    parts_consumed = parts_result.all()
    total_parts_cost = sum(float(p.SparePartConsumption.total_cost or 0) for p in parts_consumed)

    # Avg lot cost per device (for device P&L)
    lot_cost_per_device = (
        float(lot.buying_price or 0) / max(lot.qty, 1) if lot else 0
    )

    # Current location for this device
    loc_map = await _build_location_map(db, [device.id])
    current_location = loc_map.get(str(device.id))

    # IQC inspection (for stress report display)
    iqc_result = await db.execute(
        select(IQCInspection).where(IQCInspection.device_id == device.id)
    )
    iqc_inspection = iqc_result.scalar_one_or_none()

    # Parse stress report JSON for template rendering
    stress_data = None
    if iqc_inspection and iqc_inspection.stress_report:
        try:
            import json as _json
            stress_data = _json.loads(iqc_inspection.stress_report)
        except Exception:
            stress_data = None

    return templates.TemplateResponse("devices/detail.html", {
        "request": request, "current_user": current_user,
        "device": device, "lot": lot,
        "movements": movements, "repairs": repairs,
        "qc_checks": qc_checks, "parts_consumed": parts_consumed,
        "total_parts_cost": total_parts_cost,
        "lot_cost_per_device": lot_cost_per_device,
        "stage_labels": STAGE_LABELS,
        "current_location": current_location,
        "iqc_inspection": iqc_inspection,
        "stress_data": stress_data,
    })


# ── 3. DEVICE EDIT ───────────────────────────────────────────────────────────

@router.get("/{barcode}/edit", response_class=HTMLResponse)
async def device_edit_form(
    barcode: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(edit_allowed),
):
    device = await _get_device_or_404(barcode, db)
    lots_result = await db.execute(select(Lot).order_by(Lot.lot_number))
    lots = lots_result.scalars().all()
    storage_locs_result = await db.execute(
        select(StorageLocation)
        .where(StorageLocation.is_active == True)
        .order_by(StorageLocation.zone, StorageLocation.unit_id)
    )
    storage_locations = storage_locs_result.scalars().all()
    movements_result = await db.execute(
        select(StageMovement)
        .where(StageMovement.device_id == device.id)
        .order_by(StageMovement.moved_at.desc())
    )
    movements = movements_result.scalars().all()
    return templates.TemplateResponse("devices/edit.html", {
        "request": request, "current_user": current_user,
        "device": device, "lots": lots,
        "storage_locations": storage_locations,
        "movements": movements,
        "success": request.query_params.get("success"),
    })


@router.post("/{barcode}/edit")
async def device_edit_save(
    barcode: str,
    request: Request,
    lot_id: str = Form(...),
    sub_category: str = Form(""),
    brand: str = Form(""),
    model: str = Form(""),
    device_type: str = Form(""),
    serial_no: str = Form(""),
    grn_number: str = Form(""),
    cpu: str = Form(""),
    generation: str = Form(""),
    ram_gb: str = Form(""),
    storage_gb: str = Form(""),
    storage_type: str = Form(""),
    hdd_capacity_gb: str = Form(""),
    screen_size: str = Form(""),
    battery_health_pct: str = Form(""),
    bios_password: str = Form("no"),
    color: str = Form(""),
    grade: str = Form(""),
    floor: str = Form(""),
    warehouse: str = Form(""),
    notes: str = Form(""),
    qty: str = Form(""),
    device_price_input: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(edit_allowed),
):
    device = await _get_device_or_404(barcode, db)

    device.lot_id = lot_id
    device.sub_category = sub_category or None
    device.brand = brand or None
    device.model = model or None
    device.device_type = device_type or None
    device.serial_no = serial_no or None
    device.grn_number = grn_number or None
    device.cpu = cpu or None
    device.generation = generation or None
    device.ram_gb = int(ram_gb) if ram_gb else None
    device.storage_gb = int(storage_gb) if storage_gb else None
    device.storage_type = storage_type or None
    device.hdd_capacity_gb = int(hdd_capacity_gb) if hdd_capacity_gb else None
    device.screen_size = screen_size or None
    device.battery_health_pct = int(battery_health_pct) if battery_health_pct else None
    device.bios_password = (bios_password == "yes")
    device.color = color or None
    if grade:
        try:
            device.grade = DeviceGrade(grade)
        except (ValueError, KeyError):
            device.grade = None
    else:
        device.grade = None
    device.floor = floor or None
    device.warehouse = warehouse or None
    device.notes = notes or None
    if qty:
        try:
            device.qty = int(qty)
        except ValueError:
            pass
    if device_price_input:
        try:
            device.device_price = float(device_price_input)
        except ValueError:
            pass
    device.updated_at = app_now()

    await db.commit()
    return RedirectResponse(
        url=f"/devices/{barcode}?success=Device+updated+successfully",
        status_code=302
    )
