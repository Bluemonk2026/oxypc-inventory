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
from models.location import DeviceLocationLog, StorageLocation, LocationAction, UNIT_TYPE_LABELS
from models.iqc_inspection import IQCInspection
from models.part_request import PartRequest
from models.work_order import WorkOrder
from models.engines import DeviceCosting
from models.sales import Sale
from services.parts_required import compute_required, LEGACY_LABELS
from auth.dependencies import get_current_user, require_roles, verify_csrf
from utils.warranty import warranty_from_sold_at, warranty_status_for_sale
from utils.master_data import master_values

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
    device = (await db.execute(
        select(Device).where(or_(Device.barcode.ilike(bc), Device.serial_no.ilike(bc)))
    )).scalar_one_or_none()
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
    sold_grade = device.grade or "—"
    sold_on = sale.sold_at.strftime("%d-%m-%Y") if sale and sale.sold_at else "—"
    if sale and w:
        warranty_status = "Within Warranty" if w["status"] == "active" else "Out of Warranty"
    elif sale:
        warranty_status = "Out of Warranty"
    else:
        warranty_status = "Not Sold Yet"

    # ── Sale warranty_type fields (Phase 1a/1b RMA capture) ──────────────────────
    rma_warranty_type = getattr(sale, "warranty_type", None) if sale else None
    rma_warranty_expires_at = getattr(sale, "warranty_expires_at", None) if sale else None
    rma_warranty_status = warranty_status_for_sale(sale)  # in_warranty/out_of_warranty/no_warranty

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
        "warranty_status": warranty_status,
        "sold_grade": sold_grade,
        "sold_on": sold_on,
        "return_status": "Yes" if device.return_status else "No",
        "rma_warranty_type": rma_warranty_type or "none",
        "rma_warranty_expires_at": rma_warranty_expires_at.strftime("%d-%m-%Y") if rma_warranty_expires_at else None,
        "rma_warranty_status": rma_warranty_status,
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
    device_type: str = "",
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
    if device_type:
        filters.append(Device.device_type == device_type)

    for f in filters:
        query = query.where(f)

    query = query.order_by(Device.updated_at.desc())
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

    model_summary = await _build_model_summary(db, filters)
    lot_summary = await _build_lot_summary(db)

    # Scrap Products from Repair Line — moved here from Production Manager
    # (that page now only handles active repair-line devices).
    scrap_devices = (await db.execute(
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.current_stage == DeviceStage.scrapped, Device.is_active == True)
        .order_by(Device.updated_at.desc())
    )).all()

    return templates.TemplateResponse("devices/list.html", {
        "request": request, "current_user": current_user,
        "devices": devices, "lots": lots,
        "stages": DeviceStage, "stage_labels": STAGE_LABELS,
        "q": q, "stage": stage, "lot": lot, "grade": grade, "category": category,
        "device_type": device_type,
        "device_type_options": await master_values(db, "device_type"),
        "stage_options": [(s.value, STAGE_LABELS.get(s, s.value)) for s in DeviceStage],
        "total": len(devices),
        "location_map": location_map,
        "stock_price_map": stock_price_map, "sale_price_map": sale_price_map,
        "model_summary": model_summary,
        "lot_summary": lot_summary,
        "scrap_devices": scrap_devices,
    })


async def _build_lot_summary(db: AsyncSession) -> list:
    """Lot Based table (below the Model Based table on Inventory Search):
    one row per Lot with GRN/supplier/vendor/financial details plus
    'Actual Selling' — the sum of Sale.sale_price for devices in that lot."""
    lots = (await db.execute(select(Lot).where(Lot.is_trashed == False).order_by(Lot.lot_number))).scalars().all()
    if not lots:
        return []

    actual_selling_rows = (await db.execute(
        select(Device.lot_id, func.sum(Sale.sale_price))
        .join(Sale, Sale.device_id == Device.id)
        .where(Device.lot_id.in_([l.id for l in lots]))
        .group_by(Device.lot_id)
    )).all()
    actual_selling_map = {str(lot_id): float(total or 0) for lot_id, total in actual_selling_rows}

    # Per-lot tag numbers (Device -> barcode/qty) for the View modal, plus
    # the distinct Device Type(s) present in each lot for the summary column.
    device_rows = (await db.execute(
        select(Device.lot_id, Device.barcode, Device.qty, Device.device_type)
        .where(Device.lot_id.in_([l.id for l in lots]), Device.is_trashed == False)
    )).all()
    tags_by_lot: dict = {}
    device_types_by_lot: dict = {}
    for lot_id, barcode, qty, device_type in device_rows:
        tags_by_lot.setdefault(str(lot_id), []).append({"barcode": barcode, "qty": qty or 1})
        if device_type:
            device_types_by_lot.setdefault(str(lot_id), set()).add(device_type)

    summary = []
    for l in lots:
        summary.append({
            "lot_number": l.lot_number,
            "purchase_date": l.purchase_date,
            "supplier_name": l.supplier_name,
            "grn_date": l.grn_date,
            "vendor_name": l.vendor_name or "—",
            "qty": l.qty,
            "condition": l.condition or "—",
            "device_type": ", ".join(sorted(device_types_by_lot.get(str(l.id), []))) or "—",
            "buying_price": float(l.buying_price or 0),
            "selling_price": float(l.selling_price) if l.selling_price is not None else None,
            "actual_selling": actual_selling_map.get(str(l.id), 0.0),
            "notes": l.notes or "—",
            "tags": tags_by_lot.get(str(l.id), []),
        })
    return summary


async def _build_model_summary(db: AsyncSession, filters: list) -> list:
    """Model Based table (below the main Devices table on Inventory Search):
    one row per distinct (model, brand), aggregated across ALL matching
    devices (not capped at 500 like the on-screen table), with Total Count,
    Total Price, Repaired count, and per-tag detail for the view modal."""
    query = (
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.is_trashed == False)
    )
    for f in filters:
        query = query.where(f)
    rows = (await db.execute(query)).all()
    if not rows:
        return []

    device_ids = [d.id for d, _ in rows]

    # Stock Price (P&L total cost) per device — same source as the main table
    price_map = {}
    for c in (await db.execute(
        select(DeviceCosting).where(DeviceCosting.device_id.in_(device_ids))
    )).scalars().all():
        price_map[str(c.device_id)] = float(c.total_cost or 0)
    for d, _ in rows:
        did = str(d.id)
        if did not in price_map and d.device_price:
            price_map[did] = float(d.device_price) * (d.qty or 1)

    # Assigned Storage Location (Location ID / Location Type) per device,
    # via the device's own location_id FK — same source as Device Detail.
    loc_rows = (await db.execute(
        select(Device.id, StorageLocation.unit_id, StorageLocation.unit_type)
        .outerjoin(StorageLocation, Device.location_id == StorageLocation.id)
        .where(Device.id.in_(device_ids))
    )).all()
    device_location = {str(did): (unit_id, unit_type) for did, unit_id, unit_type in loc_rows}

    # Devices with at least one part consumed ("Repaired")
    repaired_ids = {
        str(did) for (did,) in (await db.execute(
            select(SparePartConsumption.device_id)
            .where(SparePartConsumption.device_id.in_(device_ids))
            .distinct()
        )).all()
    }

    groups: dict = {}
    for d, _lot_number in rows:
        key = (d.model or "Unknown Model", d.brand or "Unknown Make")
        g = groups.setdefault(key, {
            "model": key[0], "make": key[1], "device_type": d.device_type or "—",
            "total_count": 0, "total_price": 0.0, "repaired_count": 0,
            "grade_counts": {"A": 0, "B": 0, "C": 0},
            "tags": [],
        })
        did = str(d.id)
        price = price_map.get(did, 0.0)
        unit_id, unit_type = device_location.get(did, (None, None))
        grade_val = d.grade.value if d.grade else None
        g["total_count"] += 1
        g["total_price"] += price
        if did in repaired_ids:
            g["repaired_count"] += 1
        if grade_val in g["grade_counts"]:
            g["grade_counts"][grade_val] += 1
        g["tags"].append({
            "barcode": d.barcode,
            "location_id": unit_id or "—",
            "location_type": UNIT_TYPE_LABELS.get(unit_type, unit_type) if unit_type else "—",
            "grade": grade_val or "—",
        })

    summary = []
    for g in groups.values():
        g["unit_price"] = round(g["total_price"] / g["total_count"], 2) if g["total_count"] else 0
        g["total_price"] = round(g["total_price"], 2)
        summary.append(g)
    summary.sort(key=lambda g: g["total_count"], reverse=True)
    return summary


@router.get("/export")
async def export_devices(
    q: str = "",
    stage: str = "",
    lot: str = "",
    grade: str = "",
    category: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(view_allowed),
):
    """Export device search results as CSV.

    Filters mirror the main /devices search route exactly (same is_trashed
    exclusion, same outer join, same category filter) so what's on screen
    is always what gets exported — a previous version silently diverged
    from the list route (missing category filter, missing is_trashed
    filter, and an inner join that dropped devices with no lot assigned
    yet), which could make the export look "empty" relative to the list.
    """
    query = (
        select(Device, Lot.lot_number)
        .outerjoin(Lot, Device.lot_id == Lot.id)
        .where(Device.is_trashed == False)
    )
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
    if category:
        filters.append(Device.sub_category == category)
    for f in filters:
        query = query.where(f)
    query = query.order_by(Device.updated_at.desc())
    result = await db.execute(query)
    rows = result.all()

    # Full stage-history string per device (Tag Number -> every stage it has
    # passed through, in order) — a single current_stage column doesn't show
    # the path a device took to get there, which is what this export is for.
    device_ids = [device.id for device, _ in rows]
    movements_by_device = {}
    if device_ids:
        mv_result = await db.execute(
            select(StageMovement)
            .where(StageMovement.device_id.in_(device_ids))
            .order_by(StageMovement.moved_at.asc())
        )
        for mv in mv_result.scalars().all():
            movements_by_device.setdefault(mv.device_id, []).append(mv)

    def _stage_history(device):
        moves = movements_by_device.get(device.id)
        if not moves:
            return STAGE_LABELS.get(device.current_stage, device.current_stage)
        parts = []
        for mv in moves:
            label = STAGE_LABELS.get(mv.to_stage, mv.to_stage)
            when = mv.moved_at.strftime("%d-%b-%Y") if mv.moved_at else ""
            parts.append(f"{label} ({when})" if when else label)
        return " -> ".join(parts)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Barcode", "Lot", "GRN", "Invoice No", "Sub-Category", "Brand", "Model", "Device Type",
        "Serial No", "CPU", "CPU Make", "Generation", "RAM GB", "RAM", "Total RAM Count", "Total RAM Size",
        "SSD GB", "Storage Type", "Hard Drive",
        "HDD GB", "Total HDD Count", "Total HDD Size", "Screen Size", "Battery %", "BIOS Pwd", "Color",
        "Grade", "Stage", "Stage History", "Floor", "Warehouse", "Notes", "Created", "Updated"
    ])
    for device, lot_number in rows:
        writer.writerow([
            device.barcode, lot_number, device.grn_number, device.invoice_number, device.sub_category,
            device.brand, device.model, device.device_type, device.serial_no,
            device.cpu, device.cpu_make, device.generation, device.ram_gb, device.ram_summary,
            device.total_ram_count, device.total_ram_size, device.storage_gb,
            device.storage_type, device.hdd_summary, device.hdd_capacity_gb,
            device.total_hdd_count, device.total_hdd_size, device.screen_size,
            device.battery_health_pct, "Yes" if device.bios_password else "No",
            device.color, device.grade,
            STAGE_LABELS.get(device.current_stage, device.current_stage),
            _stage_history(device),
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

    # Assigned Storage Location (Location ID / Location Type / Zone) — the
    # device's own location_id FK, distinct from current_location above
    # (which is derived from the most recent DeviceLocationLog entry).
    assigned_location = None
    if device.location_id:
        assigned_location = (await db.execute(
            select(StorageLocation).where(StorageLocation.id == device.location_id)
        )).scalar_one_or_none()

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
    req_by_partid = {}
    for r in pr_rows:
        req_by_part.setdefault(r.part_name, r)  # latest per part (rows ordered desc)
        if r.part_id:
            req_by_partid.setdefault(str(r.part_id), r)  # latest per resolved SparePart

    # ── Parts Consumed table (#33): every Part Request row whose Action
    #    flipped to "Part Changed" (status == "received"), priced from the
    #    live Part Master unit price × the qty actually handed over/verified.
    changed_part_ids = {r.part_id for r in pr_rows if r.status == "received" and r.part_id}
    changed_spare_parts = {}
    if changed_part_ids:
        sp_rows = (await db.execute(select(SparePart).where(SparePart.id.in_(changed_part_ids)))).scalars().all()
        changed_spare_parts = {sp.id: sp for sp in sp_rows}
    changed_parts_consumed = []
    for r in pr_rows:
        if r.status != "received":
            continue
        sp = changed_spare_parts.get(r.part_id)
        unit_price = float(sp.unit_price) if sp else 0.0
        qty = r.qty_handed_over or 0
        changed_parts_consumed.append({
            "part_name": r.part_name, "unit_price": unit_price,
            "qty": qty, "total": unit_price * qty,
        })
    total_changed_parts_cost = sum(row["total"] for row in changed_parts_consumed)

    # Net "In Stock" mirrors the Parts Dashboard: qty_in_stock minus the qty
    # already handed over (status="handed_over") but not yet deducted from raw
    # stock, so Stock Status here equals the Part Master In Stock column.
    consumed_rows = (await db.execute(
        select(PartRequest.part_id, func.sum(PartRequest.qty_handed_over))
        .where(PartRequest.status == "handed_over", PartRequest.part_id.isnot(None))
        .group_by(PartRequest.part_id)
    )).all()
    consumed_by_part = {str(pid): int(total or 0) for pid, total in consumed_rows}

    # Resolve every Parts Consumption row to its Part Master row by NAME in a
    # single query. Two reasons this is one query and not one-per-row: the DB
    # lives in a different region from the app, so a per-row loop pays the
    # round-trip latency N times; and matching by name (not category/keyword)
    # is what makes this table agree with the Parts Dashboard, which keys its
    # In Stock column off the Part Master row itself.
    # is_trashed==False mirrors the dashboard's own filter — a trashed part is
    # not "stock you can use", and including it here would over-report.
    wanted_names = {row["label"].strip().lower() for row in required_rows}
    sp_by_name = {}
    if wanted_names:
        name_rows = (await db.execute(
            select(SparePart).where(
                SparePart.is_trashed == False,
                func.lower(func.trim(SparePart.name)).in_(wanted_names),
            ).order_by(SparePart.qty_in_stock.desc())
        )).scalars().all()
        for sp_row in name_rows:
            # Ordered by stock desc, so setdefault keeps the best-stocked row
            # when a name is duplicated in Part Master.
            sp_by_name.setdefault((sp_row.name or "").strip().lower(), sp_row)

    # Category roll-up for the labels with no exact name match.
    #
    # PARTS_MATRIX labels are generic component types ("Keyboard", "Display");
    # Part Master rows are specific SKUs ("HP UK Keyboard", "15.6-inch HD Panel").
    # That is one-to-many, so an exact name match resolves for almost none of them
    # and there is no single "correct" SKU to show. Summing the category answers
    # the question the engineer is actually asking — do we have a keyboard on the
    # shelf — and every SKU in the sum is netted the same way the Parts Dashboard
    # nets it, so the two pages still reconcile.
    wanted_cats = {row["category"] for row in required_rows if row.get("category")}
    cat_totals: dict[str, int] = {}
    if wanted_cats:
        cat_rows = (await db.execute(
            select(SparePart).where(
                SparePart.is_trashed == False,
                SparePart.category.in_(wanted_cats),
            )
        )).scalars().all()
        for sp_row in cat_rows:
            net = max(0, int(sp_row.qty_in_stock or 0)
                         - consumed_by_part.get(str(sp_row.id), 0))
            cat_totals[sp_row.category] = cat_totals.get(sp_row.category, 0) + net

    parts_consumption = []
    for row in required_rows:
        sp = sp_by_name.get(row["label"].strip().lower())
        rolled_up = False
        if sp is not None:
            raw_stock = int(sp.qty_in_stock or 0)
            stock = max(0, raw_stock - consumed_by_part.get(str(sp.id), 0))
        elif row.get("category") in cat_totals:
            # Flagged as a category total in the UI rather than shown bare — it
            # answers a broader question than "how many of this exact part", and
            # presenting it as the latter is how the old code went wrong.
            stock = cat_totals[row["category"]]
            rolled_up = True
        else:
            # Nothing in that category either. Showing 0 would read as "out of
            # stock" when the truth is "we have no record" — a purchasing
            # decision made on that is a wrong decision. Show "no match" instead.
            stock = None
        # Match an existing request either by the PARTS_MATRIX label (Faulty /
        # matched-part flow submits part_name == label) OR by the resolved
        # SparePart id (New/Replace via the category→name cascade submits the
        # SparePart's own name, which never equals the label). Without the id
        # fallback the "Requested" pill silently never appears for those.
        existing = req_by_part.get(row["label"])
        for _legacy in LEGACY_LABELS.get(row["label"], ()):
            # Requests raised before the "Screen / Display" -> "Display" and
            # "Adapter / Charger" -> "Adapter" renames stored the OLD label in
            # part_name. Without this the Requested/Verify pill would silently
            # vanish for every in-flight request on those two parts.
            if existing:
                break
            existing = req_by_part.get(_legacy)
        if not existing and sp:
            existing = req_by_partid.get(str(sp.id))
        parts_consumption.append({
            "label": row["label"],
            "category": sp.category if sp else row["category"],
            "required": row["required"],
            "matched": sp is not None,
            "rolled_up": rolled_up,
            "in_stock": stock is not None and stock > 0,
            "stock_qty": stock,
            "part_id": str(sp.id) if sp else "",
            "part_code": sp.part_code if sp else None,
            "request": existing,
        })

    # ── All active spare parts, for the New Request/Replace modal's
    #    Part Category -> Part Name cascade (client-side filtered). ──────────
    all_parts_result = await db.execute(
        select(SparePart).order_by(SparePart.category, SparePart.name)
    )
    all_spare_parts = [
        {"id": str(sp.id), "name": sp.name, "category": sp.category, "model": sp.model}
        for sp in all_parts_result.scalars().all()
    ]

    # ── Work ID History — all WorkOrders assigned to this device ──────────────
    work_orders = (await db.execute(
        select(WorkOrder).where(WorkOrder.device_id == device.id)
        .order_by(WorkOrder.assigned_at.desc())
    )).scalars().all()

    # ── Warranty Status for device detail ────────────────────────────────────
    _sale_for_warranty = (await db.execute(
        select(Sale).where(Sale.device_id == device.id).order_by(Sale.sold_at.desc()).limit(1)
    )).scalars().first()
    _w = warranty_from_sold_at(_sale_for_warranty.sold_at if _sale_for_warranty else None)
    if device.current_stage != DeviceStage.sold:
        warranty_label = "Not Sold Yet"
    elif _w and _w["status"] == "active":
        warranty_label = "Within Warranty"
    else:
        warranty_label = "Out of Warranty"

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
        "warranty_label": warranty_label,
        "stage_labels": STAGE_LABELS,
        "current_location": current_location,
        "assigned_location": assigned_location,
        "iqc_inspection": iqc_inspection,
        "stress_data": stress_data,
        "parts_consumption": parts_consumption,
        "changed_parts_consumed": changed_parts_consumed,
        "total_changed_parts_cost": total_changed_parts_cost,
        "all_spare_parts": all_spare_parts,
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
    current_lot = next((l for l in lots if l.id == device.lot_id), None)
    return templates.TemplateResponse("devices/edit.html", {
        "request": request, "current_user": current_user,
        "device": device, "lots": lots,
        "current_lot": current_lot,
        "storage_locations": storage_locations,
        "movements": movements,
        "iqc_inspection": iqc_inspection,
        "success": request.query_params.get("success"),
    })


@router.post("/{barcode}/edit")
async def device_edit_save(
    barcode: str,
    request: Request,
    lot_id: str = Form(""),
    sub_category: str = Form(""),
    brand: str = Form(""),
    model: str = Form(""),
    device_type: str = Form(""),
    serial_no: str = Form(""),
    grn_number: str = Form(""),
    cpu: str = Form(""),
    cpu_make: str = Form(""),
    generation: str = Form(""),
    ram_gb: str = Form(""),
    storage_gb: str = Form(""),
    total_ram_count: str = Form(""),
    total_ram_size: str = Form(""),
    ram_summary: str = Form(""),
    total_hdd_count: str = Form(""),
    total_hdd_size: str = Form(""),
    hdd_summary: str = Form(""),
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
    location_id: str = Form(""),
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

    if (lot_id or "").strip():
        device.lot_id = lot_id
    else:
        from utils.lot_helpers import get_or_create_unassigned_lot
        unassigned = await get_or_create_unassigned_lot(db)
        device.lot_id = unassigned.id
    device.sub_category = sub_category or None
    device.brand = brand or None
    device.model = model or None
    device.device_type = device_type or None
    device.serial_no = serial_no or None
    device.grn_number = grn_number or None
    device.cpu = cpu or None
    device.cpu_make = cpu_make or None
    device.generation = generation or None
    # ram_gb/storage_gb inputs were replaced on the Edit form by the IQC-style
    # RAM/Hard Drive (summary) fields; keep them non-destructive — only overwrite
    # the legacy numeric columns when a value is actually submitted.
    if (ram_gb or "").strip():
        device.ram_gb = int(ram_gb) if ram_gb.strip().isdigit() else None
    if (storage_gb or "").strip():
        device.storage_gb = int(storage_gb) if storage_gb.strip().isdigit() else None
    # IQC-style hardware fields (plain summed size in RAM / Hard Drive)
    device.total_ram_count = total_ram_count.strip() or None
    device.total_ram_size = total_ram_size.strip() or None
    device.ram_summary = ram_summary.strip() or None
    device.total_hdd_count = total_hdd_count.strip() or None
    device.total_hdd_size = total_hdd_size.strip() or None
    device.hdd_summary = hdd_summary.strip() or None
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
    # ── Resolve Location ID -> StorageLocation (Floor/Zone -> Location ID cascade). ──
    # warehouse is legacy free-text; best-effort mirror the resolved location's
    # display_name into it for backward-compat display in older reports/exports.
    resolved_location_id = None
    resolved_warehouse = warehouse or None
    if location_id:
        try:
            uuid_module.UUID(str(location_id))
            loc = (await db.execute(
                select(StorageLocation).where(StorageLocation.id == location_id)
            )).scalar_one_or_none()
            if loc:
                resolved_location_id = loc.id
                resolved_warehouse = loc.display_name
        except ValueError:
            pass
    device.location_id = resolved_location_id
    device.warehouse = resolved_warehouse
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
        "screen_dot", "screen_line", "screen_discoloration", "screen_patch",
        "screen_broken", "screen_flickering", "screen_scratch", "screen_loose", "screen_missing",
        "screen_hinge_broken", "screen_colour_spread", "screen_keyboard_mark",
        "panel_a_scratch", "panel_a_broken", "panel_a_missing", "panel_a_dent", "panel_a_colour_fade",
        "panel_b_scratch", "panel_b_colour_fade", "panel_b_rubber_cut", "panel_b_broken", "panel_b_missing",
        "panel_c_scratch", "panel_c_broken", "panel_c_missing", "panel_c_dent", "panel_c_colour_fade",
        "panel_d_dent", "panel_d_colour_fade", "panel_d_scratch", "panel_d_broken", "panel_d_missing",
        "keyboard_colour_fade", "keyboard_key_missing", "keyboard_hard_press",
        "touchpad_click_working", "touchpad_scratch", "touchpad_colour_fade", "touchpad_missing",
        "cover_ram", "cover_dvd", "cover_storage",
        "hinge_condition", "hinge_cover", "touchpad_logicboard", "fan_working",
    ]
    _IQC_INT_FIELDS = ["usb_a_ports", "usb_c_ports", "ethernet_ports", "storage_health_pct", "fan_sound_dba"]
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
