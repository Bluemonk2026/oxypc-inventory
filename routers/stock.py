from templates_config import templates
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Form, Query, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, update
from datetime import datetime as _dt
from utils.timezone import app_now
from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceStage, StageMovement
from models.lot import Lot, LotLineItem
from models.crm import CRMSourcingDeal
from auth.dependencies import get_current_user, require_roles, verify_csrf, require_module_perm
from services.audit_engine import audit
from services.event_bus import EventType, publish
from models.sales import Sale
from models.spare_parts import SparePartConsumption
from models.engines import RepairAttempt
from models.qc import QCCheck
from models.iqc_inspection import IQCInspection
from models.cost_config import CostConfig
from models.stock_transfer import StockTransfer
from models.stock_validation import StockValidation

router = APIRouter(tags=["stock"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.inventory_manager)


@router.get("/lots/api/exists")
async def lot_number_exists(lot_number: str, exclude_id: str = "",
                            db: AsyncSession = Depends(get_db),
                            current_user: User = Depends(get_current_user)):
    """Live duplicate check for Lot Number (item 13). Returns {"exists": bool}.
    exclude_id lets the Edit Lot page ignore the lot being edited."""
    ln = (lot_number or "").strip()
    if not ln:
        return JSONResponse({"exists": False})
    q = select(Lot.id).where(Lot.lot_number == ln)
    rows = (await db.execute(q)).all()
    exists = False
    for (rid,) in rows:
        if exclude_id and str(rid) == str(exclude_id):
            continue
        exists = True
        break
    return JSONResponse({"exists": exists})

STOCK_DEPARTMENTS = [
    "IQC Handler", "L1 Engineer", "L2 Engineer", "L3 Engineer",
    "QC Handler", "Inventory Manager", "Sales Manager", "Parts Manager",
]

import csv
import io
from fastapi.responses import StreamingResponse


async def _next_lot_number(db: AsyncSession) -> str:
    """
    Auto-generate the next LOT-NNN number.
    Uses MAX on the numeric suffix (not COUNT) so gaps from trashed lots
    don't cause collisions: e.g., if LOT-003 was trashed, next is still
    LOT-004 and we never accidentally suggest LOT-003 again.
    Falls back to LOT-001 when the table is empty.
    """
    from sqlalchemy import text as _text
    result = await db.execute(
        _text(
            "SELECT COALESCE(MAX(CAST(REGEXP_REPLACE(lot_number, '[^0-9]', '', 'g') AS INTEGER)), 0)"
            " FROM lots WHERE lot_number ~ '^LOT-[0-9]'"
        )
    )
    max_num = result.scalar() or 0
    return f"LOT-{max_num + 1:03d}"


@router.get("/lots", response_class=HTMLResponse)
async def list_lots(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    q: str = Query(default=""),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
):
    offset = (page - 1) * page_size

    # Build filtered base statement — exclude trashed lots
    base_stmt = select(Lot).where(Lot.is_trashed.isnot(True))
    if q:
        _like = f"%{q}%"
        base_stmt = base_stmt.where(or_(
            Lot.supplier_name.ilike(_like),
            Lot.lot_number.ilike(_like),
            Lot.vendor_name.ilike(_like),
        ))
    if date_from:
        try:
            base_stmt = base_stmt.where(Lot.purchase_date >= _dt.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            pass
    if date_to:
        try:
            base_stmt = base_stmt.where(Lot.purchase_date <= _dt.strptime(date_to, "%Y-%m-%d"))
        except ValueError:
            pass

    # Total count for pagination (filtered)
    total_result = await db.execute(select(func.count()).select_from(base_stmt.subquery()))
    total = total_result.scalar() or 0
    total_pages = max(1, (total + page_size - 1) // page_size)

    # Fetch the page of lots — one query
    lots_result = await db.execute(
        base_stmt.order_by(Lot.created_at.desc()).offset(offset).limit(page_size)
    )
    lots = lots_result.scalars().all()
    lot_ids = [lot.id for lot in lots]

    # Batch-fetch device counts and sold counts — two queries instead of 2N
    dev_counts: dict = {}
    sold_counts: dict = {}
    if lot_ids:
        dev_rows = await db.execute(
            select(Device.lot_id, func.count(Device.id))
            .where(Device.lot_id.in_(lot_ids), Device.is_active == True)
            .group_by(Device.lot_id)
        )
        dev_counts = dict(dev_rows.fetchall())

        sold_rows = await db.execute(
            select(Device.lot_id, func.count(Device.id))
            .where(Device.lot_id.in_(lot_ids), Device.current_stage == DeviceStage.sold)
            .group_by(Device.lot_id)
        )
        sold_counts = dict(sold_rows.fetchall())

    lot_stats = [
        {"lot": lot, "devices": dev_counts.get(lot.id, 0), "sold": sold_counts.get(lot.id, 0)}
        for lot in lots
    ]
    return templates.TemplateResponse("lots/list.html", {
        "request": request, "lot_stats": lot_stats, "current_user": current_user,
        "page": page, "page_size": page_size, "total": total, "total_pages": total_pages,
        "q": q, "date_from": date_from, "date_to": date_to,
    })


@router.get("/lots/export-all-csv")
async def export_all_lots_csv(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    q: str = Query(default=""),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
):
    """Export filtered lots as CSV — respects the same q / date_from / date_to
    filters that are active on the Lot Management list page."""

    # ── Apply the same filter logic as list_lots ─────────────────────────────
    base_stmt = select(Lot).where(Lot.is_trashed.isnot(True))
    if q:
        base_stmt = base_stmt.where(
            or_(Lot.lot_number.ilike(f"%{q}%"), Lot.supplier_name.ilike(f"%{q}%"))
        )
    if date_from:
        try:
            base_stmt = base_stmt.where(Lot.purchase_date >= _dt.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            pass
    if date_to:
        try:
            base_stmt = base_stmt.where(Lot.purchase_date <= _dt.strptime(date_to, "%Y-%m-%d"))
        except ValueError:
            pass

    result = await db.execute(base_stmt.order_by(Lot.created_at.desc()))
    lots = result.scalars().all()

    # ── Per-lot device + sold counts ─────────────────────────────────────────
    lot_ids = [lot.id for lot in lots]
    dev_map: dict = {}
    sold_map: dict = {}
    if lot_ids:
        dev_rows = await db.execute(
            select(Device.lot_id, func.count(Device.id))
            .where(Device.lot_id.in_(lot_ids), Device.is_active == True)
            .group_by(Device.lot_id)
        )
        dev_map = dict(dev_rows.fetchall())

        sold_rows = await db.execute(
            select(Device.lot_id, func.count(Device.id))
            .where(Device.lot_id.in_(lot_ids), Device.current_stage == DeviceStage.sold)
            .group_by(Device.lot_id)
        )
        sold_map = dict(sold_rows.fetchall())

    # ── Build CSV with full column set matching the UI table ─────────────────
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Lot #", "GRN #", "Supplier", "Created At",
        "Purchase Date", "Rcvd Date (GRN)", "Invoice No.", "Invoice Value",
        "SGST", "CGST", "IGST", "Qty (PO)",
        "Registered Devices", "Sold", "Buying Price (₹)",
    ])
    for lot in lots:
        grn = lot.grn_system_number or (str(lot.grn_number_new) if lot.grn_number_new else "")
        writer.writerow([
            lot.lot_number,
            grn,
            lot.supplier_name or "",
            lot.created_at.strftime("%d-%m-%Y %H:%M") if lot.created_at else "",
            lot.purchase_date.strftime("%d-%m-%Y") if lot.purchase_date else "",
            lot.grn_date.strftime("%d-%m-%Y") if lot.grn_date else "",
            lot.invoice_no or "",
            float(lot.invoice_value or 0) or "",
            float(lot.sgst or 0) or "",
            float(lot.cgst or 0) or "",
            float(lot.igst or 0) or "",
            lot.qty or 0,
            dev_map.get(lot.id, 0),
            sold_map.get(lot.id, 0),
            float(lot.buying_price or 0),
        ])

    from datetime import datetime as _dtnow
    suffix = f"-{q}" if q else ""
    filename = f"lots-export{suffix}-{_dtnow.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/lots/export-csv")
async def export_selected_lots_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Export devices belonging to selected lot IDs as CSV."""
    form = await request.form()
    lot_ids_raw = form.getlist("lot_ids")
    if not lot_ids_raw:
        return RedirectResponse(url="/lots?warning=No+lots+selected", status_code=302)

    rows = await db.execute(
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.lot_id.in_(lot_ids_raw), Device.is_active == True)
        .order_by(Lot.lot_number, Device.barcode)
    )
    devices = rows.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "barcode", "brand", "model", "lot_number", "grade",
        "ram_gb", "storage_gb", "storage_type", "current_stage", "serial_no",
    ])
    for device, lot_number in devices:
        writer.writerow([
            device.barcode,
            device.brand or "",
            device.model or "",
            lot_number,
            device.grade or "",
            device.ram_gb or "",
            device.storage_gb or "",
            device.storage_type or "",
            device.current_stage.value if device.current_stage else "",
            device.serial_no or "",
        ])
    from datetime import datetime as _dtnow
    filename = f"lot-devices-{_dtnow.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/lots/new", response_class=HTMLResponse)
async def new_lot_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    # Optional pre-fill params from a CRM sourcing deal
    from_deal: str = Query(default=None),
    prefill_supplier: str = Query(default=""),
    prefill_qty: str = Query(default=""),
    prefill_price: str = Query(default=""),
    prefill_notes: str = Query(default=""),
    prefill_po: str = Query(default=""),
    grn_system_number: str = Query(default=""),
    grn_date: str = Query(default=""),
    supplier: str = Query(default=""),
    lot_number: str = Query(default=""),
):
    next_num = await _next_lot_number(db)
    prefill = {
        "from_deal": from_deal or "",
        "supplier": prefill_supplier,
        "qty": prefill_qty,
        "price": prefill_price,
        "notes": prefill_notes,
        "po": prefill_po,
    } if from_deal else None
    return templates.TemplateResponse("lots/form.html", {
        "request": request, "next_lot_number": next_num,
        "current_user": current_user, "error": None,
        "prefill": prefill, "lot": None,
        "prefill_grn_system": grn_system_number,
        "prefill_grn_date": _norm_grn_date(grn_date),
        "prefill_supplier_locked": supplier,
        "prefill_lot_number": lot_number,
        "from_grn": bool(grn_system_number or lot_number or supplier),
        "today_date": app_now().strftime('%Y-%m-%d'),
    })


def _parse_date(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d") if s else None
    except Exception:
        return None


def _parse_decimal(s: str):
    try:
        return float(s) if s else None
    except Exception:
        return None


def _norm_grn_date(s: str) -> str:
    """Normalise a free-text invoice date (the GRN 'Date of Invoice') to
    YYYY-MM-DD for the date picker. Returns '' if unparseable (the form then
    falls back to today)."""
    s = (s or "").strip()
    if not s:
        return ""
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d",
                "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y",
                "%B %d, %Y", "%d-%b-%y", "%d/%m/%y"):
        try:
            return _dt.strptime(s, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return ""


@router.post("/lots/new")
async def create_lot(
    request: Request,
    background_tasks: BackgroundTasks,
    lot_number: str = Form(...),
    supplier_name: str = Form(...),
    buying_price: str = Form(...),
    qty: int = Form(...),
    purchase_date: str = Form(...),
    grn_system_number: str = Form(""),
    grn_number_new: str = Form(""),
    grn_date: str = Form(""),
    invoice_date: str = Form(""),
    invoice_no: str = Form(""),
    invoice_value: str = Form(""),
    taxable_amount: str = Form(""),
    sgst: str = Form(""),
    cgst: str = Form(""),
    igst: str = Form(""),
    vehicle_number: str = Form(""),
    e_way_bill: str = Form(""),
    po_number: str = Form(""),
    vendor_name: str = Form(""),
    notes: str = Form(""),
    crm_deal_id: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    _perm: User = Depends(require_module_perm("lots", "add")),
):
    existing = await db.execute(select(Lot).where(Lot.lot_number == lot_number))
    if existing.scalar_one_or_none():
        next_num = await _next_lot_number(db)
        return templates.TemplateResponse("lots/form.html", {
            "request": request, "next_lot_number": next_num, "current_user": current_user,
            "error": "Lot number already exists", "lot": None,
        })
    lot = Lot(
        lot_number=lot_number,
        supplier_name=supplier_name,
        buying_price=float(buying_price),
        qty=qty,
        purchase_date=datetime.strptime(purchase_date, "%Y-%m-%d"),
        grn_system_number=grn_system_number or None,
        grn_number_new=int(grn_number_new) if grn_number_new else None,
        grn_date=_parse_date(grn_date),
        invoice_date=_parse_date(invoice_date),
        invoice_no=invoice_no or None,
        invoice_value=_parse_decimal(invoice_value),
        taxable_amount=_parse_decimal(taxable_amount),
        sgst=_parse_decimal(sgst),
        cgst=_parse_decimal(cgst),
        igst=_parse_decimal(igst),
        vehicle_number=vehicle_number or None,
        e_way_bill=e_way_bill or None,
        po_number=po_number or None,
        vendor_name=vendor_name or None,
        notes=notes or None,
        created_by=current_user.username,
    )
    db.add(lot)
    await db.flush()   # get lot.id before audit/commit

    await audit(db, action="LOT_CREATED", user=current_user,
                table_name="lots", record_id=str(lot.id),
                new_value={"lot_number": lot_number, "supplier": supplier_name,
                           "qty": qty, "buying_price": buying_price},
                request=request)

    # ── CRM integration: back-link sourcing deal to this lot ──────────────
    if crm_deal_id and crm_deal_id.strip():
        deal_r = await db.execute(
            select(CRMSourcingDeal).where(CRMSourcingDeal.id == crm_deal_id.strip())
        )
        deal = deal_r.scalar_one_or_none()
        if deal:
            deal.linked_lot_id = lot.id
            deal.stage = "won"

    await db.commit()

    publish(EventType.LOT_CREATED, {
        "lot_id": str(lot.id),
        "lot_number": lot.lot_number,
        "supplier": supplier_name,
        "qty": qty,
        "buying_price": buying_price,
        "_source": "stock_html",
    }, background_tasks)

    if crm_deal_id and crm_deal_id.strip():
        return RedirectResponse(
            url=f"/crm/sourcing/{crm_deal_id.strip()}?success=Lot+{lot.lot_number}+created+and+linked",
            status_code=302,
        )
    return RedirectResponse(url="/lots?success=Lot+created", status_code=302)


@router.get("/lots/{lot_id}/edit", response_class=HTMLResponse)
async def edit_lot_form(lot_id: str, request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(allowed)):
    result = await db.execute(select(Lot).where(Lot.id == lot_id))
    lot = result.scalar_one_or_none()
    if not lot:
        raise HTTPException(404)
    return templates.TemplateResponse("lots/form.html", {
        "request": request, "lot": lot, "next_lot_number": None, "current_user": current_user, "error": None,
    })


@router.post("/lots/{lot_id}/edit")
async def edit_lot(
    lot_id: str,
    request: Request,
    lot_number: str = Form(...),
    supplier_name: str = Form(...),
    buying_price: str = Form(...),
    qty: int = Form(...),
    purchase_date: str = Form(...),
    grn_system_number: str = Form(""),
    grn_number_new: str = Form(""),
    grn_date: str = Form(""),
    invoice_date: str = Form(""),
    invoice_no: str = Form(""),
    invoice_value: str = Form(""),
    taxable_amount: str = Form(""),
    sgst: str = Form(""),
    cgst: str = Form(""),
    igst: str = Form(""),
    vehicle_number: str = Form(""),
    e_way_bill: str = Form(""),
    po_number: str = Form(""),
    vendor_name: str = Form(""),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    result = await db.execute(select(Lot).where(Lot.id == lot_id))
    lot = result.scalar_one_or_none()
    if not lot:
        raise HTTPException(404)
    lot.lot_number = lot_number
    lot.supplier_name = supplier_name
    lot.buying_price = float(buying_price)
    lot.qty = qty
    lot.purchase_date = datetime.strptime(purchase_date, "%Y-%m-%d")
    lot.grn_system_number = grn_system_number or None
    lot.grn_number_new = int(grn_number_new) if grn_number_new else None
    lot.grn_date = _parse_date(grn_date)
    lot.invoice_date = _parse_date(invoice_date)
    lot.invoice_no = invoice_no or None
    lot.invoice_value = _parse_decimal(invoice_value)
    lot.taxable_amount = _parse_decimal(taxable_amount)
    lot.sgst = _parse_decimal(sgst)
    lot.cgst = _parse_decimal(cgst)
    lot.igst = _parse_decimal(igst)
    lot.vehicle_number = vehicle_number or None
    lot.e_way_bill = e_way_bill or None
    lot.po_number = po_number or None
    lot.vendor_name = vendor_name or None
    lot.notes = notes or None
    await db.commit()
    return RedirectResponse(url=f"/lots/{lot_id}?success=Lot+updated", status_code=302)


@router.post("/lots/{lot_id}/delete")
async def delete_lot_permanent(
    lot_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """
    Permanently delete a lot and all its associated devices (with their full
    history) from the database. Deletion cascades through every device child
    table in FK dependency order so no constraint violations occur.
    CRM sourcing deal links are nullified, then LotLineItems are cascade-deleted
    by the DB alongside the lot row.
    """
    import uuid as _uuid
    from urllib.parse import quote
    from sqlalchemy import text as _text

    try:
        uid = _uuid.UUID(lot_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Lot not found")

    lot = (await db.execute(select(Lot).where(Lot.id == uid))).scalar_one_or_none()
    if not lot:
        raise HTTPException(status_code=404, detail="Lot not found")

    lot_number = lot.lot_number
    lot_id_param = {"lot_id": str(uid)}

    # ── Cascade-delete all device child records (leaf tables first) ──────────
    # 1. spare_parts_consumption (nullable device_id)
    await db.execute(_text(
        "DELETE FROM spare_parts_consumption "
        "WHERE device_id IN (SELECT id FROM devices WHERE lot_id = :lot_id)"
    ), lot_id_param)

    # 2. ram_tracking (nullable device_id AND destination_device_id)
    await db.execute(_text(
        "DELETE FROM ram_tracking "
        "WHERE device_id IN (SELECT id FROM devices WHERE lot_id = :lot_id) "
        "OR destination_device_id IN (SELECT id FROM devices WHERE lot_id = :lot_id)"
    ), lot_id_param)

    # 3. spare_parts_ledger (nullable device_id)
    await db.execute(_text(
        "DELETE FROM spare_parts_ledger "
        "WHERE device_id IN (SELECT id FROM devices WHERE lot_id = :lot_id)"
    ), lot_id_param)

    # 4. audit_scan_items (nullable device_id)
    await db.execute(_text(
        "DELETE FROM audit_scan_items "
        "WHERE device_id IN (SELECT id FROM devices WHERE lot_id = :lot_id)"
    ), lot_id_param)

    # 5. device_location_logs
    await db.execute(_text(
        "DELETE FROM device_location_logs "
        "WHERE device_id IN (SELECT id FROM devices WHERE lot_id = :lot_id)"
    ), lot_id_param)

    # 6. qc_checks
    await db.execute(_text(
        "DELETE FROM qc_checks "
        "WHERE device_id IN (SELECT id FROM devices WHERE lot_id = :lot_id)"
    ), lot_id_param)

    # 7. iqc_inspections
    await db.execute(_text(
        "DELETE FROM iqc_inspections "
        "WHERE device_id IN (SELECT id FROM devices WHERE lot_id = :lot_id)"
    ), lot_id_param)

    # 8. repair_attempts (before repair_jobs — may FK into repair_jobs)
    await db.execute(_text(
        "DELETE FROM repair_attempts "
        "WHERE device_id IN (SELECT id FROM devices WHERE lot_id = :lot_id)"
    ), lot_id_param)

    # 9. repair_jobs
    await db.execute(_text(
        "DELETE FROM repair_jobs "
        "WHERE device_id IN (SELECT id FROM devices WHERE lot_id = :lot_id)"
    ), lot_id_param)

    # 10. device_costing
    await db.execute(_text(
        "DELETE FROM device_costing "
        "WHERE device_id IN (SELECT id FROM devices WHERE lot_id = :lot_id)"
    ), lot_id_param)

    # 11. device_aging (nullable device_id)
    await db.execute(_text(
        "DELETE FROM device_aging "
        "WHERE device_id IN (SELECT id FROM devices WHERE lot_id = :lot_id)"
    ), lot_id_param)

    # 12. stage_movements
    await db.execute(_text(
        "DELETE FROM stage_movements "
        "WHERE device_id IN (SELECT id FROM devices WHERE lot_id = :lot_id)"
    ), lot_id_param)

    # 13. returns (before sales — returns may FK to sales.original_sale_id)
    await db.execute(_text(
        "DELETE FROM returns "
        "WHERE device_id IN (SELECT id FROM devices WHERE lot_id = :lot_id)"
    ), lot_id_param)

    # 14a. customer_receipts (FK to sales.id via sale_id — must precede sales)
    await db.execute(_text(
        "DELETE FROM customer_receipts "
        "WHERE sale_id IN ("
        "  SELECT id FROM sales "
        "  WHERE device_id IN (SELECT id FROM devices WHERE lot_id = :lot_id)"
        ")"
    ), lot_id_param)

    # 14b. sales
    await db.execute(_text(
        "DELETE FROM sales "
        "WHERE device_id IN (SELECT id FROM devices WHERE lot_id = :lot_id)"
    ), lot_id_param)

    # 15. stock_transfers
    await db.execute(_text(
        "DELETE FROM stock_transfers "
        "WHERE device_id IN (SELECT id FROM devices WHERE lot_id = :lot_id)"
    ), lot_id_param)

    # 16. devices for this lot
    await db.execute(_text(
        "DELETE FROM devices WHERE lot_id = :lot_id"
    ), lot_id_param)
    # ── End device cascade ────────────────────────────────────────────────────

    # Nullify any CRM sourcing deal back-links so the FK doesn't block the delete
    await db.execute(
        update(CRMSourcingDeal)
        .where(CRMSourcingDeal.linked_lot_id == uid)
        .values(linked_lot_id=None)
    )

    # Audit before the row is gone
    await audit(
        db, action="LOT_DELETED", user=current_user,
        table_name="lots", record_id=str(uid),
        new_value={
            "lot_number": lot_number,
            "supplier": lot.supplier_name,
            "buying_price": str(lot.buying_price),
            "qty": lot.qty,
            "deleted_by": current_user.username,
        },
        request=request,
    )

    await db.delete(lot)
    await db.commit()

    return RedirectResponse(
        url=f"/lots?success={quote(lot_number + ' deleted permanently')}",
        status_code=302,
    )


@router.get("/lots/{lot_id}", response_class=HTMLResponse)
async def lot_detail(lot_id: str, request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(Lot).where(Lot.id == lot_id))
    lot = result.scalar_one_or_none()
    if not lot:
        raise HTTPException(404)
    devices_result = await db.execute(select(Device).where(Device.lot_id == lot_id, Device.is_active == True).order_by(Device.created_at))
    devices = devices_result.scalars().all()
    li_result = await db.execute(
        select(LotLineItem).where(LotLineItem.lot_id == lot_id).order_by(LotLineItem.sub_category, LotLineItem.brand, LotLineItem.model)
    )
    line_items = li_result.scalars().all()

    # ── Profit calculation (same COGS formula as dashboard lot_pl) ──────────
    _cfg_result = await db.execute(select(CostConfig))
    _cfg = {r.key: float(r.value) for r in _cfg_result.scalars().all()}
    repair_labour_rate = _cfg.get("repair_labour_rate", 150.0)
    cosmetic_rate      = _cfg.get("cosmetic_rate", 50.0)

    revenue_result = await db.execute(
        select(func.coalesce(func.sum(Sale.sale_price), 0))
        .join(Device, Sale.device_id == Device.id)
        .where(Device.lot_id == lot.id)
    )
    lot_revenue = float(revenue_result.scalar() or 0)

    parts_result = await db.execute(
        select(func.coalesce(func.sum(SparePartConsumption.total_cost), 0))
        .where(SparePartConsumption.lot_id == lot.id)
    )
    parts_cost = float(parts_result.scalar() or 0)

    labour_result = await db.execute(
        select(
            func.coalesce(func.sum(RepairAttempt.cost), 0),
            func.count(RepairAttempt.id),
        )
        .join(Device, RepairAttempt.device_id == Device.id)
        .where(Device.lot_id == lot.id)
    )
    labour_row = labour_result.one()
    labour_actual = float(labour_row[0] or 0)
    attempt_count = int(labour_row[1] or 0)
    labour_cost = labour_actual if labour_actual > 0 else (attempt_count * repair_labour_rate)

    cosmetic_result = await db.execute(
        select(func.count(StageMovement.id))
        .join(Device, StageMovement.device_id == Device.id)
        .where(Device.lot_id == lot.id, StageMovement.to_stage == DeviceStage.cleaning)
    )
    cosmetic_count = int(cosmetic_result.scalar() or 0)
    cosmetic_cost  = cosmetic_count * cosmetic_rate

    buying     = float(lot.buying_price or 0)
    total_cost = buying + parts_cost + labour_cost + cosmetic_cost
    lot_profit = lot_revenue - total_cost
    lot_margin = round((lot_profit / lot_revenue * 100) if lot_revenue > 0 else 0, 1)

    # ── Per-device sub-record counts for the devices table ──────────────────
    device_id_list = [d.id for d in devices]
    if device_id_list:
        # Repair attempts per device
        repair_q = await db.execute(
            select(RepairAttempt.device_id, func.count(RepairAttempt.id).label("cnt"))
            .where(RepairAttempt.device_id.in_(device_id_list))
            .group_by(RepairAttempt.device_id)
        )
        repair_map = {str(r.device_id): r.cnt for r in repair_q.all()}

        # QC checks per device
        qc_q = await db.execute(
            select(QCCheck.device_id, func.count(QCCheck.id).label("cnt"))
            .where(QCCheck.device_id.in_(device_id_list))
            .group_by(QCCheck.device_id)
        )
        qc_map = {str(r.device_id): r.cnt for r in qc_q.all()}

        # IQC done (distinct device_ids that have an IQC record)
        iqc_q = await db.execute(
            select(IQCInspection.device_id)
            .where(IQCInspection.device_id.in_(device_id_list))
            .distinct()
        )
        iqc_set = {str(r.device_id) for r in iqc_q.all()}

        # Sold status
        sold_q = await db.execute(
            select(Sale.device_id).where(Sale.device_id.in_(device_id_list))
        )
        sold_set = {str(r.device_id) for r in sold_q.all()}
    else:
        repair_map = {}
        qc_map     = {}
        iqc_set    = set()
        sold_set   = set()
    # ─────────────────────────────────────────────────────────────────────────

    return templates.TemplateResponse("lots/detail.html", {
        "request": request, "lot": lot, "devices": devices, "current_user": current_user,
        "line_items": line_items,
        "lot_revenue":       lot_revenue,
        "lot_buying":        buying,
        "lot_parts_cost":    parts_cost,
        "lot_labour_cost":   labour_cost,
        "lot_cosmetic_cost": cosmetic_cost,
        "lot_total_cost":    total_cost,
        "lot_profit":        lot_profit,
        "lot_margin":        lot_margin,
        # per-device sub-record counts
        "repair_map":  repair_map,
        "qc_map":      qc_map,
        "iqc_set":     iqc_set,
        "sold_set":    sold_set,
    })


@router.get("/stock", response_class=HTMLResponse)
async def stock_in_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    offset = (page - 1) * page_size

    base_stmt = (
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.current_stage == DeviceStage.stock_in, Device.is_active == True)
    )

    total_result = await db.execute(
        select(func.count()).select_from(base_stmt.subquery())
    )
    total = total_result.scalar() or 0
    total_pages = max(1, (total + page_size - 1) // page_size)

    result = await db.execute(
        base_stmt.order_by(Device.updated_at.desc()).offset(offset).limit(page_size)
    )
    devices = result.all()

    # ── Analytics count cards (#17) ──────────────────────────────────────────
    count_rows = (await db.execute(
        select(Device.current_stage, func.count(Device.id))
        .where(Device.is_active == True)
        .group_by(Device.current_stage)
    )).all()
    stage_counts = {stage: cnt for stage, cnt in count_rows}

    def _c(*stages):
        return sum(stage_counts.get(s, 0) for s in stages)

    repair_stages = [DeviceStage.l1, DeviceStage.l2, DeviceStage.l3, DeviceStage.qc_check]
    cosmetic_stages = [DeviceStage.cleaning, DeviceStage.dry_sanding, DeviceStage.masking,
                       DeviceStage.painting, DeviceStage.water_sanding, DeviceStage.final_qc]
    analytics = {
        "iqc": _c(DeviceStage.iqc),
        "in_stock": _c(*repair_stages, *cosmetic_stages, DeviceStage.ready_to_sale),
        "trc": _c(*repair_stages, *cosmetic_stages),
        "ready": _c(DeviceStage.ready_to_sale),
    }

    # ── Assigned department per device (latest stock transfer) for #1 column ──
    device_ids = [d.id for d, _ in devices]
    assigned_dept_map = {}
    if device_ids:
        st_rows = (await db.execute(
            select(StockTransfer.device_id, StockTransfer.department)
            .where(StockTransfer.device_id.in_(device_ids), StockTransfer.department != None)
            .order_by(StockTransfer.transfer_date.desc())
        )).all()
        for did, dept in st_rows:
            key = str(did)
            if key not in assigned_dept_map and dept:
                assigned_dept_map[key] = dept

    return templates.TemplateResponse("lots/stock_in.html", {
        "request": request, "devices": devices, "current_user": current_user,
        "analytics": analytics, "assigned_dept_map": assigned_dept_map,
        "departments": STOCK_DEPARTMENTS,
        "page": page, "page_size": page_size, "total": total, "total_pages": total_pages,
    })


@router.get("/stock/move-to-stock")
async def move_to_stock_get():
    return RedirectResponse(url="/stock", status_code=302)


def _transfer_snapshot(device, **over):
    """Build common StockTransfer snapshot kwargs from a device."""
    base = dict(
        device_id=device.id, barcode=device.barcode, serial_no=device.serial_no,
        make=device.brand, model=device.model, category=device.sub_category,
        product_stage=device.current_stage.value if device.current_stage else None,
        transfer_date=app_now(),
    )
    base.update(over)
    return base


@router.post("/stock/validate")
async def stock_validate(
    request: Request,
    barcode: str = Form(...),
    qty_received: str = Form(""),
    condition_received: str = Form(""),
    reassign_department: str = Form(""),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    device = (await db.execute(select(Device).where(Device.barcode == barcode))).scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
    try:
        qty = int(qty_received) if qty_received else None
    except ValueError:
        qty = None
    db.add(StockValidation(
        device_id=device.id, barcode=device.barcode, qty_received=qty,
        condition_received=condition_received or None,
        reassign_department=reassign_department or None, notes=notes or None,
        validated_by=current_user.username,
    ))
    # Reassignment records a stock transfer to that department (drives 'Assigned User')
    if reassign_department:
        wh = device.warehouse or "Stock In"
        db.add(StockTransfer(**_transfer_snapshot(
            device, transfer_type="reassign", from_warehouse=wh, to_warehouse=wh,
            transferred_by=current_user.username, department=reassign_department,
            notes="Reassigned via Stock Validate", created_by=current_user.username,
        )))
    await audit(db, user=current_user, action="STOCK_VALIDATE", table_name="stock_validations",
                record_id=str(device.id),
                new_value={"barcode": barcode, "qty_received": qty,
                           "condition": condition_received, "reassign": reassign_department},
                request=request)
    await db.commit()
    return RedirectResponse(url=f"/stock?success=Stock+validated+for+{barcode}", status_code=302)


@router.post("/stock/bulk-transfer")
async def stock_bulk_transfer(
    request: Request,
    barcodes: list[str] = Form(default=[]),
    transfer_type: str = Form("transfer_to_trc"),
    department: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    barcodes = [b for b in (barcodes or []) if b]
    if not barcodes:
        return RedirectResponse(url="/stock?error=No+items+selected", status_code=302)
    devices = (await db.execute(select(Device).where(Device.barcode.in_(barcodes)))).scalars().all()
    cnt = 0
    for device in devices:
        db.add(StockTransfer(**_transfer_snapshot(
            device, transfer_type=transfer_type or "transfer_to_trc",
            from_warehouse=device.warehouse or "Stock In", to_warehouse=device.warehouse or "TRC",
            transferred_by=current_user.username, department=department or None,
            notes="Bulk stock transfer", created_by=current_user.username,
        )))
        cnt += 1
    await audit(db, user=current_user, action="STOCK_BULK_TRANSFER", table_name="stock_transfers",
                record_id=None, new_value={"count": cnt, "department": department}, request=request)
    await db.commit()
    return RedirectResponse(url=f"/stock?success={cnt}+item(s)+transferred", status_code=302)


@router.post("/stock/move-to-stock")
async def move_to_stock(
    barcode: str = Form(...),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    result = await db.execute(select(Device).where(Device.barcode == barcode))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
    prev_stage = device.current_stage
    device.current_stage = DeviceStage.stock_in
    device.updated_at = app_now()
    movement = StageMovement(
        device_id=device.id, from_stage=prev_stage, to_stage=DeviceStage.stock_in,
        moved_by=current_user.username, notes=notes or "Moved to Stock"
    )
    db.add(movement)
    await db.commit()
    return RedirectResponse(url="/stock?success=Moved+to+Stock", status_code=302)


@router.post("/stock/move-to-trc")
async def move_to_trc(
    barcode: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Move a Stock Inward device into the TRC Production stage."""
    device = (await db.execute(select(Device).where(Device.barcode == barcode))).scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
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
        moved_by=current_user.username, notes="Moved to TRC Production",
    ))
    await db.commit()
    return RedirectResponse(url="/stock?success=Moved+to+TRC+Production", status_code=302)


@router.get("/trc-production", response_class=HTMLResponse)
async def trc_production_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    offset = (page - 1) * page_size
    base_stmt = (
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.current_stage == DeviceStage.trc_production, Device.is_active == True)
    )
    total = (await db.execute(select(func.count()).select_from(base_stmt.subquery()))).scalar() or 0
    total_pages = max(1, (total + page_size - 1) // page_size)
    devices = (await db.execute(
        base_stmt.order_by(Device.updated_at.desc()).offset(offset).limit(page_size)
    )).all()

    device_ids = [d.id for d, _ in devices]
    assigned_dept_map = {}
    if device_ids:
        st_rows = (await db.execute(
            select(StockTransfer.device_id, StockTransfer.department)
            .where(StockTransfer.device_id.in_(device_ids), StockTransfer.department != None)
            .order_by(StockTransfer.transfer_date.desc())
        )).all()
        for did, dept in st_rows:
            key = str(did)
            if key not in assigned_dept_map and dept:
                assigned_dept_map[key] = dept

    return templates.TemplateResponse("lots/trc_production.html", {
        "request": request, "devices": devices, "current_user": current_user,
        "assigned_dept_map": assigned_dept_map, "departments": STOCK_DEPARTMENTS,
        "page": page, "page_size": page_size, "total": total, "total_pages": total_pages,
    })


# ── Lot Line Items (Invoice Breakdown) ─────────────────────────────────────

@router.get("/lots/{lot_id}/line-items/export")
async def export_line_items_csv(
    lot_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import csv as _csv, io as _io
    from fastapi.responses import StreamingResponse as SR
    lot = (await db.execute(select(Lot).where(Lot.id == lot_id))).scalar_one_or_none()
    result = await db.execute(
        select(LotLineItem).where(LotLineItem.lot_id == lot_id)
        .order_by(LotLineItem.sub_category, LotLineItem.brand, LotLineItem.model)
    )
    items = result.scalars().all()
    out = _io.StringIO()
    w = _csv.writer(out)
    w.writerow(["sub_category","brand","model","cpu","generation","ram_gb","has_ram","storage_gb","storage_type","has_storage","screen_size","grade","unit_price","qty","notes"])
    for item in items:
        w.writerow([
            item.sub_category, item.brand or "", item.model or "",
            item.cpu or "", item.generation or "",
            item.ram_gb or "", "yes" if item.has_ram else "no",
            item.storage_gb or "", item.storage_type or "", "yes" if item.has_storage else "no",
            item.screen_size or "", item.grade or "",
            item.unit_price, item.qty, item.notes or ""
        ])
    out.seek(0)
    fname = f"line_items_{lot.lot_number if lot else lot_id}.csv"
    return SR(
        _io.BytesIO(out.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"}
    )


@router.get("/lots/{lot_id}/line-items", response_class=JSONResponse)
async def get_lot_line_items(
    lot_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all line items for a lot as JSON."""
    result = await db.execute(
        select(LotLineItem)
        .where(LotLineItem.lot_id == lot_id)
        .order_by(LotLineItem.sub_category, LotLineItem.brand, LotLineItem.model)
    )
    items = result.scalars().all()
    return JSONResponse({"items": [
        {
            "id": str(item.id),
            "sub_category": item.sub_category,
            "brand": item.brand or "",
            "model": item.model or "",
            "cpu": item.cpu or "",
            "generation": item.generation or "",
            "ram_gb": item.ram_gb,
            "has_ram": item.has_ram,
            "storage_gb": item.storage_gb,
            "storage_type": item.storage_type or "",
            "has_storage": item.has_storage,
            "screen_size": item.screen_size or "",
            "grade": item.grade or "",
            "unit_price": float(item.unit_price),
            "qty": item.qty,
            "notes": item.notes or "",
            "label": _line_item_label(item),
        }
        for item in items
    ]})


def _line_item_label(item) -> str:
    """Generate a human-readable label for a line item."""
    parts = [item.sub_category]
    if item.brand:   parts.append(item.brand)
    if item.model:   parts.append(item.model)
    spec = []
    if item.ram_gb:
        spec.append(f"{item.ram_gb}GB RAM")
    elif item.has_ram is False:
        spec.append("No RAM")
    if item.storage_gb and item.storage_type:
        spec.append(f"{item.storage_gb}GB {item.storage_type}")
    elif item.storage_gb:
        spec.append(f"{item.storage_gb}GB Storage")
    elif item.has_storage is False:
        spec.append("No HDD/SSD")
    if spec:
        parts.append(f"[{', '.join(spec)}]")
    return " — ".join(parts)


@router.post("/lots/{lot_id}/line-items")
async def add_lot_line_item(
    lot_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    body = await request.json()
    lot = (await db.execute(select(Lot).where(Lot.id == lot_id))).scalar_one_or_none()
    if not lot:
        return JSONResponse({"ok": False, "error": "Lot not found"}, status_code=404)

    item = LotLineItem(
        lot_id       = lot.id,
        sub_category = body.get("sub_category", "Laptop").strip(),
        brand        = (body.get("brand") or "").strip() or None,
        model        = (body.get("model") or "").strip() or None,
        cpu          = (body.get("cpu") or "").strip() or None,
        generation   = (body.get("generation") or "").strip() or None,
        ram_gb       = int(body["ram_gb"]) if body.get("ram_gb") else None,
        has_ram      = body.get("has_ram", True),
        storage_gb   = int(body["storage_gb"]) if body.get("storage_gb") else None,
        storage_type = (body.get("storage_type") or "").strip() or None,
        has_storage  = body.get("has_storage", True),
        screen_size  = (body.get("screen_size") or "").strip() or None,
        grade        = (body.get("grade") or "").strip() or None,
        unit_price   = float(body["unit_price"]),
        qty          = int(body.get("qty", 1)),
        notes        = (body.get("notes") or "").strip() or None,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return JSONResponse({"ok": True, "id": str(item.id), "label": _line_item_label(item)})


@router.put("/lots/{lot_id}/line-items/{item_id}")
async def update_lot_line_item(
    lot_id: str,
    item_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    result = await db.execute(
        select(LotLineItem).where(LotLineItem.id == item_id, LotLineItem.lot_id == lot_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
    body = await request.json()
    item.sub_category = body.get("sub_category", item.sub_category)
    item.brand        = (body.get("brand") or "").strip() or None
    item.model        = (body.get("model") or "").strip() or None
    item.cpu          = (body.get("cpu") or "").strip() or None
    item.generation   = (body.get("generation") or "").strip() or None
    item.ram_gb       = int(body["ram_gb"]) if body.get("ram_gb") else None
    item.has_ram      = body.get("has_ram", item.has_ram)
    item.storage_gb   = int(body["storage_gb"]) if body.get("storage_gb") else None
    item.storage_type = (body.get("storage_type") or "").strip() or None
    item.has_storage  = body.get("has_storage", item.has_storage)
    item.screen_size  = (body.get("screen_size") or "").strip() or None
    item.grade        = (body.get("grade") or "").strip() or None
    item.unit_price   = float(body["unit_price"])
    item.qty          = int(body.get("qty", item.qty))
    item.notes        = (body.get("notes") or "").strip() or None
    await db.commit()
    await db.refresh(item)
    return JSONResponse({"ok": True, "id": str(item.id), "label": _line_item_label(item)})


@router.delete("/lots/{lot_id}/line-items/{item_id}")
async def delete_lot_line_item(
    lot_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    result = await db.execute(
        select(LotLineItem).where(LotLineItem.id == item_id, LotLineItem.lot_id == lot_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
    await db.delete(item)
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/lots/{lot_id}/line-items/bulk-csv")
async def bulk_import_line_items(
    lot_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Bulk import line items from CSV."""
    import csv as _csv, io as _io
    lot = (await db.execute(select(Lot).where(Lot.id == lot_id))).scalar_one_or_none()
    if not lot:
        return JSONResponse({"ok": False, "error": "Lot not found"}, status_code=404)

    form = await request.form()
    file = form.get("file")
    if not file:
        return JSONResponse({"ok": False, "error": "No file"}, status_code=400)

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except Exception:
        text = content.decode("latin-1")

    reader = _csv.DictReader(_io.StringIO(text))
    saved, errors = 0, []
    for i, row in enumerate(reader, start=2):
        try:
            unit_price = float((row.get("unit_price") or "0").replace(",", ""))
            qty = int(row.get("qty") or 1)
            sub_cat = (row.get("sub_category") or "Laptop").strip()
            has_ram_val = (row.get("has_ram") or "yes").strip().lower()
            has_storage_val = (row.get("has_storage") or "yes").strip().lower()
            item = LotLineItem(
                lot_id       = lot.id,
                sub_category = sub_cat,
                brand        = (row.get("brand") or "").strip() or None,
                model        = (row.get("model") or "").strip() or None,
                cpu          = (row.get("cpu") or "").strip() or None,
                generation   = (row.get("generation") or "").strip() or None,
                ram_gb       = int(row["ram_gb"]) if row.get("ram_gb") else None,
                has_ram      = has_ram_val not in ("no", "false", "0"),
                storage_gb   = int(row["storage_gb"]) if row.get("storage_gb") else None,
                storage_type = (row.get("storage_type") or "").strip() or None,
                has_storage  = has_storage_val not in ("no", "false", "0"),
                screen_size  = (row.get("screen_size") or "").strip() or None,
                grade        = (row.get("grade") or "").strip() or None,
                unit_price   = unit_price,
                qty          = qty,
                notes        = (row.get("notes") or "").strip() or None,
            )
            db.add(item)
            saved += 1
        except Exception as e:
            errors.append(f"Row {i}: {e}")
    await db.commit()
    if errors:
        return RedirectResponse(
            url=f"/lots/{lot_id}?warning=Bulk+import+partial:+{saved}+saved,+{len(errors)}+error(s)",
            status_code=302,
        )
    return RedirectResponse(
        url=f"/lots/{lot_id}?success=Bulk+import+complete:+{saved}+line+items+imported",
        status_code=302,
    )


# ── GRN Barcode Registration ────────────────────────────────────────────────

@router.get("/lots/{lot_id}/register", response_class=HTMLResponse)
async def grn_register_page(
    request: Request,
    lot_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """GRN barcode registration page — category-wise device entry for a lot."""
    lot = (await db.execute(select(Lot).where(Lot.id == lot_id))).scalar_one_or_none()
    if not lot:
        return RedirectResponse(url="/lots?error=Lot+not+found", status_code=302)

    # Devices already registered in this lot (at grn or iqc stage)
    result = await db.execute(
        select(Device).where(Device.lot_id == lot.id).order_by(Device.created_at.desc())
    )
    devices = result.scalars().all()

    # Group by sub_category
    from collections import defaultdict
    by_category = defaultdict(list)
    for d in devices:
        by_category[d.sub_category or "Other"].append(d)

    return templates.TemplateResponse("lots/grn_register.html", {
        "request":     request,
        "lot":         lot,
        "devices":     devices,
        "by_category": dict(by_category),
        "total_registered": len(devices),
        "current_user": current_user,
    })


@router.post("/lots/{lot_id}/register-device")
async def register_device_barcode(
    request: Request,
    lot_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AJAX: register a single device barcode into a lot at GRN stage."""
    import json as _json
    body = await request.json()

    barcode    = (body.get("barcode") or "").strip()
    brand      = (body.get("brand") or "").strip()
    model_name = (body.get("model") or "").strip()
    serial_no  = (body.get("serial_no") or "").strip()
    sub_cat    = (body.get("sub_category") or "Laptop").strip()
    device_price = body.get("device_price")

    if not barcode:
        return JSONResponse({"ok": False, "error": "Barcode is required"}, status_code=400)

    lot = (await db.execute(select(Lot).where(Lot.id == lot_id))).scalar_one_or_none()
    if not lot:
        return JSONResponse({"ok": False, "error": "Lot not found"}, status_code=404)

    # Check duplicate barcode — show lot_number not UUID
    dup_barcode = (await db.execute(
        select(Device, Lot.lot_number).join(Lot, Device.lot_id == Lot.id)
        .where(Device.barcode == barcode)
    )).first()
    if dup_barcode:
        _dev, _lot_num = dup_barcode
        return JSONResponse({
            "ok": False,
            "error": f"Barcode {barcode} already registered in lot {_lot_num}"
        }, status_code=409)

    # Check duplicate serial_no (if provided)
    if serial_no:
        dup_serial = (await db.execute(
            select(Device, Lot.lot_number).join(Lot, Device.lot_id == Lot.id)
            .where(Device.serial_no == serial_no, Device.is_active == True)
        )).first()
        if dup_serial:
            _dev, _lot_num = dup_serial
            return JSONResponse({
                "ok": False,
                "error": f"Serial {serial_no} already registered as barcode {_dev.barcode} in lot {_lot_num}"
            }, status_code=409)

    device = Device(
        barcode       = barcode,
        lot_id        = lot.id,
        brand         = brand or None,
        model         = model_name or None,
        serial_no     = serial_no or None,
        sub_category  = sub_cat,
        current_stage = DeviceStage.grn,
        grn_number    = lot.grn_system_number or str(lot.grn_number_new or ""),
        device_price  = float(device_price) if device_price else None,
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)

    return JSONResponse({
        "ok":          True,
        "barcode":     device.barcode,
        "brand":       device.brand or "",
        "model":       device.model or "",
        "serial_no":   device.serial_no or "",
        "sub_category": device.sub_category or "",
        "device_price": str(device.device_price or ""),
        "registered_at": device.created_at.strftime("%d-%m-%Y %H:%M"),
    })


@router.delete("/lots/{lot_id}/register-device/{barcode}")
async def delete_registered_device(
    request: Request,
    lot_id: str,
    barcode: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AJAX: remove a device from GRN registration (only if still at grn stage)."""
    device = (await db.execute(
        select(Device).where(Device.barcode == barcode, Device.lot_id == lot_id)
    )).scalar_one_or_none()

    if not device:
        return JSONResponse({"ok": False, "error": "Device not found"}, status_code=404)
    if device.current_stage != DeviceStage.grn:
        return JSONResponse({"ok": False, "error": f"Cannot remove — device already moved to {device.current_stage}"}, status_code=400)

    device.is_active = False
    device.deleted_at = datetime.now(timezone.utc)
    await audit(db, action="DEVICE_SOFT_DELETED", user=current_user,
                table_name="devices", record_id=str(device.id),
                old_value={"barcode": device.barcode, "is_active": True},
                new_value={"barcode": device.barcode, "is_active": False, "deleted_at": device.deleted_at.isoformat()},
                request=request)
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/lots/{lot_id}/register-bulk-csv")
async def register_bulk_csv(
    request: Request,
    lot_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Bulk register devices from uploaded CSV/Excel data."""
    import csv as _csv, io as _io
    lot = (await db.execute(select(Lot).where(Lot.id == lot_id))).scalar_one_or_none()
    if not lot:
        return JSONResponse({"ok": False, "error": "Lot not found"}, status_code=404)

    form = await request.form()
    file = form.get("file")
    if not file:
        return JSONResponse({"ok": False, "error": "No file uploaded"}, status_code=400)

    content = await file.read()
    try:
        text_content = content.decode("utf-8-sig")  # handle BOM
    except Exception:
        text_content = content.decode("latin-1")

    reader = _csv.DictReader(_io.StringIO(text_content))
    saved, skipped, errors = 0, 0, []

    for row in reader:
        barcode = (row.get("barcode") or row.get("Barcode") or row.get("BARCODE") or "").strip()
        if not barcode:
            continue

        existing = (await db.execute(select(Device).where(Device.barcode == barcode))).scalar_one_or_none()
        if existing:
            skipped += 1
            continue

        sub_cat = (row.get("sub_category") or row.get("Category") or row.get("category") or "Laptop").strip()
        try:
            price_raw = row.get("device_price") or row.get("price") or row.get("Price") or ""
            price = float(price_raw.replace(",", "")) if price_raw.strip() else None
        except Exception:
            price = None

        device = Device(
            barcode       = barcode,
            lot_id        = lot.id,
            brand         = (row.get("brand") or row.get("Brand") or "").strip() or None,
            model         = (row.get("model") or row.get("Model") or "").strip() or None,
            serial_no     = (row.get("serial_no") or row.get("Serial") or row.get("serial") or "").strip() or None,
            sub_category  = sub_cat,
            current_stage = DeviceStage.grn,
            grn_number    = lot.grn_system_number or str(lot.grn_number_new or ""),
            device_price  = price,
        )
        db.add(device)
        saved += 1

    await db.commit()
    return JSONResponse({"ok": True, "saved": saved, "skipped": skipped, "errors": errors})


@router.post("/lots/{lot_id}/advance-grn-to-iqc")
async def advance_grn_to_iqc(
    request: Request,
    lot_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Move all GRN-stage devices in this lot forward to IQC."""
    from sqlalchemy import update as sa_update
    result = await db.execute(
        select(Device).where(Device.lot_id == lot_id, Device.current_stage == DeviceStage.grn)
    )
    devices = result.scalars().all()
    if not devices:
        return JSONResponse({"ok": False, "error": "No devices at GRN stage in this lot"})

    for d in devices:
        d.current_stage = DeviceStage.iqc
    await db.commit()
    return JSONResponse({"ok": True, "moved": len(devices)})
