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
from sqlalchemy import select, or_, func, and_, update
from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceGrade, DeviceStage, StageMovement, STAGE_LABELS
from models.lot import Lot
from models.repair import RepairJob, RepairStatus
from models.qc import QCCheck
from models.spare_parts import SparePartConsumption, SparePart
from models.location import DeviceLocationLog, StorageLocation, LocationAction
from models.iqc_inspection import IQCInspection
from models.part_request import PartRequest
from models.work_order import WorkOrder
from models.engines import DeviceCosting
from models.sales import Sale
from services.parts_required import compute_required
from auth.dependencies import get_current_user, require_roles, verify_csrf
from utils.warranty import warranty_from_sold_at

router = APIRouter(prefix="/devices", tags=["devices"], dependencies=[Depends(verify_csrf)])
# All logged-in users can search/view; only admin+invmgr can edit
view_allowed = get_current_user
edit_allowed = require_roles(UserRole.admin, UserRole.inventory_manager)


@router.get("/api/brief")
async def device_brief(barcode: str, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(view_allowed)):
    """Brief device info for live tag lookups (Process Return + L3 'Replace Device
    with'). Returns Make/Model/RAM/Storage/Location/Status/Warranty as JSON."""
    from fastapi.responses import JSONResponse
    bc = (barcode or "").strip()
    if not bc:
        return JSONResponse({"found": False})
    device = (await db.execute(select(Device).where(Device.barcode == bc))).scalar_one_or_none()
    if not device:
        return JSONResponse({"found": False})
    sale = (await db.execute(
        select(Sale).where(Sale.device_id == device.id).order_by(Sale.sold_at.desc()).limit(1)
    )).scalars().first()
    w = warranty_from_sold_at(sale.sold_at if sale else None)
    loc = None
    info = (await _build_location_map(db, [str(device.id)])).get(str(device.id))
    if info and info.get("unit_id"):
        loc = info["unit_id"]
    if not loc:
        loc = device.warehouse or device.floor or "—"
    ram = f"{device.ram_gb} GB" if device.ram_gb else "—"
    if device.storage_gb:
        storage = f"{device.storage_gb} GB" + (f" {device.storage_type}" if device.storage_type else "")
    else:
        storage = "—"
    return JSONResponse({
        "found": True,
        "barcode": device.barcode,
        "make": device.brand or "—",
        "model": device.model or "—",
        "ram": ram,
        "storage": storage,
        "location": loc,
        "status": str(device.stage_label),
        "warranty": w["label"] if w else "No warranty",
        "return_status": "Yes" if device.return_status else "No",
    })


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

    # Stock Price (P&L total cost) + Sale Price (from Sales) per device
    stock_price_map, sale_price_map = {}, {}
    if device_ids:
        for c in (await db.execute(
            select(DeviceCosting).where(DeviceCosting.device_id.in_(device_ids))
        )).scalars().all():
            stock_price_map[str(c.device_id)] = c.total_cost
        for d, _ in devices:
            did = str(d.id)
            if did not in stock_price_map and d.device_price:
                stock_price_map[did] = d.device_price * (d.qty or 1)
        sale_rows = (await db.execute(
            select(Sale.device_id, func.max(Sale.sale_price))
            .where(Sale.device_id.in_(device_ids)).group_by(Sale.device_id)
        )).all()
        for did, sp in sale_rows:
            sale_price_map[str(did)] = sp

    return templates.TemplateResponse("devices/list.html", {
        "request": request, "current_user": current_user,
        "devices": devices, "lots": lots,
        "stages": DeviceStage, "stage_labels": STAGE_LABELS,
        "q": q, "stage": stage, "lot": lot, "grade": grade, "category": category,
        "total": len(devices),
        "location_map": location_map,
        "stock_price_map": stock_price_map, "sale_price_map": sale_price_map,
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

    # ── Parts Consumption (#10): fixed parts list, IQC-driven Required flag,
    #    live stock status, and any existing engineer part-request state. ───────
    required_rows = compute_required(iqc_inspection, device)
    pr_rows = (await db.execute(
        select(PartRequest).where(PartRequest.device_id == device.id)
        .order_by(PartRequest.created_at.desc())
    )).scalars().all()
    req_by_part = {}
    for r in pr_rows:
        req_by_part.setdefault(r.part_name, r)  # latest per part (rows ordered desc)
    parts_consumption = []
    for row in required_rows:
        sp = (await db.execute(
            select(SparePart).where(or_(
                SparePart.category == row["category"],
                SparePart.name.ilike(f"%{row['keyword']}%"),
            )).order_by(SparePart.qty_in_stock.desc())
        )).scalars().first()
        stock = int(sp.qty_in_stock) if sp and sp.qty_in_stock else 0
        existing = req_by_part.get(row["label"])
        parts_consumption.append({
            "label": row["label"],
            "required": row["required"],
            "in_stock": stock > 0,
            "stock_qty": stock,
            "part_id": str(sp.id) if sp else "",
            "part_code": sp.part_code if sp else None,
            "request": existing,
        })

    # ── Work ID History — all WorkOrders assigned to this device ──────────────
    work_orders = (await db.execute(
        select(WorkOrder).where(WorkOrder.device_id == device.id)
        .order_by(WorkOrder.assigned_at.desc())
    )).scalars().all()

    # ── Repair Status (item 9): derived from current stage + repair jobs ──────
    repair_status = None
    _lvl = {DeviceStage.l1: 1, DeviceStage.l2: 2, DeviceStage.l3: 3}.get(device.current_stage)
    if _lvl:
        _REQ = ("Request to L2", "Request to L3", "Escalate to L2", "Escalate to L3")
        in_prog = any(r.stage == f"L{_lvl}" and r.status == RepairStatus.in_progress for r in repairs)
        latest = repairs[0] if repairs else None
        if latest and (latest.final_status or "") in _REQ and not in_prog:
            repair_status = f"Request to L{_lvl}"
        elif in_prog:
            repair_status = f"In Progress at L{_lvl}"
        else:
            repair_status = f"Pending at L{_lvl}"

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
        "parts_consumption": parts_consumption,
        "work_orders": work_orders,
        "repair_status": repair_status,
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
    iqc_inspection = (await db.execute(
        select(IQCInspection).where(IQCInspection.device_id == device.id)
    )).scalar_one_or_none()
    return templates.TemplateResponse("devices/edit.html", {
        "request": request, "current_user": current_user,
        "device": device, "lots": lots,
        "storage_locations": storage_locations,
        "movements": movements,
        "iqc_inspection": iqc_inspection,
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
    battery_present: str = Form(""),
    bios_password: str = Form("no"),
    color: str = Form(""),
    grade: str = Form(""),
    floor: str = Form(""),
    warehouse: str = Form(""),
    notes: str = Form(""),
    qty: str = Form(""),
    device_price_input: str = Form(""),
    barcode_new: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(edit_allowed),
):
    device = await _get_device_or_404(barcode, db)

    # ── Editable Tag Number (up to 100 chars). Check uniqueness BEFORE mutating
    #    anything, so a clash returns without a partial commit. ────────────────
    new_bc = (barcode_new or "").strip()
    if new_bc and new_bc != device.barcode:
        clash = (await db.execute(
            select(Device.id).where(Device.barcode == new_bc, Device.id != device.id)
        )).scalar_one_or_none()
        if clash:
            import urllib.parse
            return RedirectResponse(
                url=f"/devices/{barcode}/edit?error=Tag+Number+{urllib.parse.quote(new_bc)}+already+exists",
                status_code=302)
        device.barcode = new_bc
        # keep WorkOrder display snapshots consistent with the new tag
        await db.execute(update(WorkOrder).where(WorkOrder.device_id == device.id).values(barcode=new_bc))

    device.lot_id = lot_id
    device.sub_category = sub_category or None
    device.brand = brand or None
    device.model = model or None
    device.device_type = device_type or None
    device.serial_no = serial_no or None
    device.grn_number = grn_number or None
    device.cpu = cpu or None
    device.generation = generation or None
    # int-or-None: tolerates non-numeric dropdown values like "Not Available" / "Not Checked"
    device.ram_gb = int(ram_gb) if (ram_gb or "").strip().isdigit() else None
    device.storage_gb = int(storage_gb) if (storage_gb or "").strip().isdigit() else None
    device.storage_type = storage_type or None
    device.hdd_capacity_gb = int(hdd_capacity_gb) if (hdd_capacity_gb or "").strip().isdigit() else None
    device.screen_size = screen_size or None
    device.battery_health_pct = int(battery_health_pct) if (battery_health_pct or "").strip().isdigit() else None
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

    # ── IQC condition fields → update (or create) the device's IQC inspection. ──
    # The Edit Device form mirrors the IQC Entry form, so all condition / panel /
    # port fields are submitted here and persisted on IQCInspection (Device holds
    # the hardware-spec fields handled above).
    iqc_inspection = (await db.execute(
        select(IQCInspection).where(IQCInspection.device_id == device.id)
    )).scalar_one_or_none()
    if iqc_inspection is None:
        iqc_inspection = IQCInspection(device_id=device.id)
        db.add(iqc_inspection)
    _form = await request.form()
    _IQC_STR_FIELDS = [
        "battery_present", "battery_cable", "charging_port", "power_on", "status", "all_ok", "r2v3_grade_category",
        "keyboard_working", "touchpad_working", "port_hdmi", "port_usb_working", "port_audio_jack",
        "speaker_status", "wifi_status", "webcam_status", "hdd_connector", "hdd_casing", "dvd_drive",
        "screen_dot", "screen_line", "screen_functional", "screen_discoloration", "screen_patch",
        "screen_broken", "screen_flickering", "screen_scratch", "screen_loose", "screen_missing",
        "screen_hinge_broken", "screen_colour_spread", "screen_keyboard_mark",
        "panel_a_scratch", "panel_a_broken", "panel_a_missing", "panel_a_dent", "panel_a_colour_fade",
        "panel_b_scratch", "panel_b_colour_fade", "panel_b_rubber_cut", "panel_b_broken", "panel_b_missing",
        "panel_c_scratch", "panel_c_broken", "panel_c_missing", "panel_c_dent", "panel_c_colour_fade",
        "panel_d_dent", "panel_d_colour_fade", "panel_d_scratch", "panel_d_broken", "panel_d_missing",
        "keyboard_colour_fade", "keyboard_key_missing", "keyboard_hard_press",
        "touchpad_click_working", "touchpad_scratch", "touchpad_colour_fade", "touchpad_missing",
    ]
    _IQC_INT_FIELDS = ["usb_a_ports", "usb_c_ports", "ethernet_ports"]
    for _f in _IQC_STR_FIELDS:
        if _f in _form:
            setattr(iqc_inspection, _f, (_form.get(_f) or None))
    for _f in _IQC_INT_FIELDS:
        if _f in _form:
            _v = (_form.get(_f) or "").strip()
            try:
                setattr(iqc_inspection, _f, int(_v) if _v else None)
            except (ValueError, TypeError):
                setattr(iqc_inspection, _f, None)

    await db.commit()
    return RedirectResponse(
        url=f"/devices/{device.barcode}?success=Device+updated+successfully",
        status_code=302
    )
