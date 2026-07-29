"""
Sales Router — sale block enforcement + return re-entry to IQC + audit
"""
from templates_config import templates
import uuid as _uuid
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from utils.timezone import app_now
from decimal import Decimal
from fastapi import APIRouter, Depends, Form, File, Request, HTTPException, Query, BackgroundTasks, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
import csv
import io
from sqlalchemy import select, func, text, or_
from fastapi.responses import StreamingResponse

from database import get_db
from utils.csv_decode import decode_csv_bytes
from models.user import User, UserRole
from models.device import Device, DeviceStage, StageMovement
from models.lot import Lot
from models.sales import Sale, Return
from models.crm import CRMSalesOpportunity, CRMContact
from models.dispatch_request import TelecallerDispatchRequest
from auth.dependencies import get_current_user, require_roles, verify_csrf, require_module_perm
from services.control_engine import validate_sale_allowed
from services.cost_engine import (
    check_below_cost_warning, get_or_create_costings, below_cost_warning_for,
)
from services.audit_engine import audit
from services.event_bus import EventType, publish
from utils.warranty import (
    warranty_from_sold_at, latest_sold_at_map,
    compute_warranty_expiry, warranty_status_for_sale,
)

router = APIRouter(tags=["sales"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.sales, UserRole.sales_manager, UserRole.telecaller)
ready_allowed = require_roles(UserRole.admin, UserRole.sales, UserRole.sales_manager, UserRole.telecaller)


async def _next_sale_number(db: AsyncSession) -> str:
    result = await db.execute(text("SELECT nextval('sale_number_seq')"))
    seq = result.scalar()
    return f"SALE-{seq:04d}"


@router.get("/sales/ready", response_class=HTMLResponse)
async def ready_list(request: Request, db: AsyncSession = Depends(get_db),
                     current_user: User = Depends(ready_allowed)):
    result = await db.execute(
        select(Device, Lot.lot_number, Lot.buying_price, Lot.qty, Lot.selling_price)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.current_stage == DeviceStage.ready_to_sale)
        .order_by(Device.updated_at.desc())
    )
    devices = result.all()

    # ── Model Summary for Ready to Sale: one row per (model, brand), aggregated
    # purchase/sale price using the same per-device-else-lot-average logic as
    # the main table's Unit Cost column. ──────────────────────────────────────
    model_summary_ready: dict = {}
    for device, lot_number, buying_price, lot_qty, selling_price in devices:
        if device.device_price:
            unit_cost = float(device.device_price)
        elif lot_qty:
            unit_cost = float(buying_price or 0) / lot_qty
        else:
            unit_cost = 0.0
        unit_sale = (float(selling_price) / lot_qty) if (selling_price and lot_qty) else 0.0
        key = (device.model or "Unknown Model", device.brand or "Unknown Make")
        g = model_summary_ready.setdefault(key, {
            "model": key[0], "make": key[1], "device_type": device.device_type or "—",
            "total_count": 0, "total_purchase_price": 0.0, "total_sale_price": 0.0,
            "barcodes": [],
        })
        g["total_count"] += 1
        g["total_purchase_price"] += unit_cost
        g["total_sale_price"] += unit_sale
        g["barcodes"].append(device.barcode)
    model_summary_ready = sorted(model_summary_ready.values(), key=lambda g: g["total_count"], reverse=True)

    # ── Total Count Sold (item 2): historical sales count for this model/make,
    # regardless of current stage — lets the telecaller see how well a model sells. ──
    sold_count_by_model = {}
    if model_summary_ready:
        sold_rows = (await db.execute(
            select(Device.model, Device.brand, func.count(Sale.id))
            .join(Sale, Sale.device_id == Device.id)
            .group_by(Device.model, Device.brand)
        )).all()
        for model, brand, cnt in sold_rows:
            sold_count_by_model[(model or "Unknown Model", brand or "Unknown Make")] = cnt
    for g in model_summary_ready:
        g["total_sold"] = sold_count_by_model.get((g["model"], g["make"]), 0)

    # ── Dispatch-request state (#21): Sell enabled only after approval ───────
    device_ids = [d.id for d, *_ in devices]
    approved_ids, requested_ids = set(), set()
    rejected_notes_map = {}
    if device_ids:
        drs = (await db.execute(
            select(TelecallerDispatchRequest.device_id, TelecallerDispatchRequest.status,
                   TelecallerDispatchRequest.rejected_notes)
            .where(TelecallerDispatchRequest.device_id.in_(device_ids))
        )).all()
        for did, st, notes in drs:
            if st == "approved":
                approved_ids.add(str(did))
            elif st == "requested":
                requested_ids.add(str(did))
            elif st == "rejected":
                rejected_notes_map[str(did)] = notes or ""

    # ── Warranty (item 1): 30 days from most recent sale of this device ──────
    sold_map = await latest_sold_at_map(db, device_ids)
    warranty_map = {}
    for did, sold_at in sold_map.items():
        w = warranty_from_sold_at(sold_at)
        if w:
            warranty_map[did] = w

    # ── Interested dealers banner: open CRM sales opps matching ready device types ──
    ready_device_types = {d.device_type for d, *_ in devices if d.device_type}
    interested_dealers: list = []
    if ready_device_types:
        opps = (await db.execute(
            select(CRMSalesOpportunity, CRMContact.company_name, CRMContact.phone)
            .outerjoin(CRMContact, CRMSalesOpportunity.contact_id == CRMContact.id)
            .where(
                CRMSalesOpportunity.device_type.in_(ready_device_types),
                CRMSalesOpportunity.stage.notin_(["won", "lost"]),
            )
            .order_by(CRMSalesOpportunity.priority.desc(), CRMSalesOpportunity.updated_at.desc())
            .limit(20)
        )).all()
        interested_dealers = [
            {
                "opp_number": opp.opp_number,
                "title": opp.title,
                "device_type": opp.device_type,
                "grade": opp.grade_required or "Any",
                "qty": opp.required_qty,
                "budget": opp.budget_per_unit,
                "stage": opp.stage,
                "priority": opp.priority,
                "company": company or "Unknown",
                "phone": phone or "",
            }
            for opp, company, phone in opps
        ]

    from routers.dispatch import _build_lot_overview
    lot_overview = await _build_lot_overview(db)

    return templates.TemplateResponse("sales/ready_list.html", {
        "request": request, "devices": devices, "current_user": current_user,
        "interested_dealers": interested_dealers,
        "approved_ids": approved_ids, "requested_ids": requested_ids,
        "rejected_notes_map": rejected_notes_map,
        "warranty_map": warranty_map, "model_summary_ready": model_summary_ready,
        "lot_overview": lot_overview,
    })


@router.post("/sales/ready/upload-tags")
async def upload_ready_tags(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(ready_allowed),
):
    """Bulk Upload Tags on Ready to Sale — reads a single-column CSV of tag
    numbers and reports back which are ready to sale, so the page can tick the
    matching rows. Read-only: selects nothing, changes nothing."""
    content = await file.read()
    text_data = decode_csv_bytes(content)
    reader = csv.DictReader(io.StringIO(text_data))

    # Accept `tag_number` or `barcode`, any casing — read by header name so a
    # user's extra columns can't shift the one we want out from under us.
    field_map = {(f or "").strip().lower(): f for f in (reader.fieldnames or [])}
    key = field_map.get("tag_number") or field_map.get("barcode")
    if not key:
        return JSONResponse(
            {"error": "CSV must have a 'tag_number' (or 'barcode') column header"},
            status_code=400,
        )

    tags, errors = [], []
    seen = set()
    for i, row in enumerate(reader, start=2):
        tag = (row.get(key) or "").strip()
        if not tag:
            errors.append(f"Row {i}: tag_number is empty")
            continue
        if tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)

    if not tags:
        return JSONResponse({"found": [], "not_found": [], "not_ready": [], "errors": errors})

    stages = dict((await db.execute(
        select(Device.barcode, Device.current_stage).where(Device.barcode.in_(tags))
    )).all())

    found, not_found, not_ready = [], [], []
    for tag in tags:
        if tag not in stages:
            not_found.append(tag)
        elif stages[tag] != DeviceStage.ready_to_sale:
            not_ready.append(tag)
        else:
            found.append(tag)

    return JSONResponse({"found": found, "not_found": not_found,
                         "not_ready": not_ready, "errors": errors})


def _unit_stock_price(device, lot) -> float:
    """Device unit cost — device-level price if set, else avg lot cost (same
    logic as the Ready-to-Sale Unit Cost column)."""
    if device is not None and device.device_price:
        return float(device.device_price)
    if lot is not None and lot.qty:
        return float(lot.buying_price or 0) / lot.qty
    return 0.0


@router.get("/sales/new", response_class=HTMLResponse)
async def sale_new_form(request: Request, barcode: str = None,
                        barcodes: str = None, qty: int = None,
                        embed: int = 0,
                        db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(allowed)):
    device = None; lot = None; stage_error = None; approved_qty = None
    stock_price = None; prefill_barcode = None; prefill_qty = None; multi_count = 0

    # ── Multi-sell prefill: comma-separated tag list (?barcodes=A,B&qty=N) ──
    if barcodes:
        codes, seen = [], set()
        for c in barcodes.split(","):
            c = c.strip()
            if c and c not in seen:
                seen.add(c); codes.append(c)
        if codes:
            prefill_barcode = ",".join(codes)
            prefill_qty = qty or len(codes)
            multi_count = len(codes)
            rows = (await db.execute(
                select(Device, Lot).outerjoin(Lot, Device.lot_id == Lot.id)
                .where(Device.barcode.in_(codes))
            )).all()
            stock_price = sum(_unit_stock_price(d, l) for d, l in rows)
            if rows:
                device, lot = rows[0]  # representative device for the info alert
    elif barcode:
        result = await db.execute(select(Device).where(Device.barcode == barcode))
        device = result.scalar_one_or_none()
        if device:
            lot_result = await db.execute(select(Lot).where(Lot.id == device.lot_id))
            lot = lot_result.scalar_one_or_none()
            # Show warning if not ready
            if device.current_stage != DeviceStage.ready_to_sale:
                stage_val = device.current_stage.value if device.current_stage else "unknown"
                stage_error = (f"Device is in stage '{stage_val}' — "
                               f"it must be in 'ready_to_sale' to sell.")
            # Prefill qty from the latest approved telecaller dispatch request
            appr = (await db.execute(
                select(TelecallerDispatchRequest)
                .where(TelecallerDispatchRequest.device_id == device.id,
                       TelecallerDispatchRequest.status == "approved")
                .order_by(TelecallerDispatchRequest.approved_at.desc())
            )).scalars().first()
            if appr:
                approved_qty = appr.qty_requested
            stock_price = _unit_stock_price(device, lot)
    next_num = await _next_sale_number(db)
    from utils.sales_person import sales_person_options
    return templates.TemplateResponse("sales/new.html", {
        "request": request, "device": device, "lot": lot,
        "sales_person_options": await sales_person_options(db),
        "next_sale_number": next_num, "current_user": current_user,
        "error": stage_error, "approved_qty": approved_qty,
        "stock_price": stock_price, "prefill_barcode": prefill_barcode,
        "prefill_qty": prefill_qty, "multi_count": multi_count,
        "embed": bool(embed),
    })


@router.post("/sales/new")
async def create_sale(
    request: Request,
    background_tasks: BackgroundTasks,
    barcode: str = Form(...),
    sale_price: str = Form(...),
    customer_name: str = Form(""),
    sales_person: str = Form(""),
    customer_phone: str = Form(""),
    customer_state: str = Form(default=None),
    invoice_no: str = Form(""),
    payment_mode: str = Form("cash"),
    notes: str = Form(""),
    qty: int = Form(1),
    invoice_file_path: str = Form(""),
    warranty_type: str = Form("none"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    _perm: User = Depends(require_module_perm("sales", "add")),
):
    # The Ready to Sale page posts this form over AJAX so a bulk sale never leaves
    # the page. Those callers get JSON — including the real failure text, which an
    # embedded page could only render into a frame the user then had to read.
    # Ordinary form posts are unaffected and still redirect/render as before.
    xhr = request.headers.get("x-requested-with", "").lower() == "xmlhttprequest"

    async def _fail(message: str, device=None, lot=None, status: int = 400):
        if xhr:
            return JSONResponse({"ok": False, "error": message}, status_code=status)
        return templates.TemplateResponse("sales/new.html", {
            "request": request, "device": device, "lot": lot,
            "next_sale_number": await _next_sale_number(db),
            "current_user": current_user, "error": message,
        })

    # ── Multi-sale support: barcode field may be a comma-separated tag list ──
    codes, _seen = [], set()
    for c in barcode.split(","):
        c = c.strip()
        if c and c not in _seen:
            _seen.add(c); codes.append(c)
    is_multi = len(codes) > 1

    if qty > 1 and not is_multi:
        notes = f"[Qty:{qty}] {notes}".strip()

    try:
        price = Decimal(sale_price)  # per-unit price (form divides Total ÷ Qty)
    except Exception:
        return await _fail("Invalid sale price — please enter a valid number")

    wtype = warranty_type if warranty_type in ("none", "30_days", "6_months", "1_year") else "none"

    # ── Resolve the whole batch up front (set-based, not per device) ──────────
    # This loop used to issue ~10 sequential round trips PER DEVICE. Against a
    # database in another region that made a 600-tag bulk sale ~6,000 serial
    # round trips and it never finished inside a request timeout. Everything the
    # loop needs is now fetched in a fixed handful of queries regardless of size.
    devices_by_code = {
        d.barcode: d for d in (await db.execute(
            select(Device).where(Device.barcode.in_(codes))
        )).scalars().all()
    }
    found = [devices_by_code[c] for c in codes if c in devices_by_code]

    # Costing rows for below-cost warnings (2 queries for the whole batch).
    costings = await get_or_create_costings(found, db)

    # Open stage movements to close, keyed by device — one query, not one each.
    open_moves = {}
    if found:
        for mv in (await db.execute(
            select(StageMovement)
            .where(StageMovement.device_id.in_([d.id for d in found]),
                   StageMovement.exited_at == None)
            .order_by(StageMovement.moved_at.desc())
        )).scalars().all():
            # Keep the newest per (device, to_stage); ordering above is desc.
            open_moves.setdefault((mv.device_id, mv.to_stage), mv)

    # Sale numbers: drawn in one call instead of one nextval per device. Count is
    # the devices that will ACTUALLY sell, not the tags submitted — drawing per
    # submitted tag would burn a number for every skipped tag and leave holes in
    # the SALE- sequence. validate_sale_allowed is pure in-memory, so this
    # pre-pass costs no queries and keeps eligibility defined in one place.
    eligible = 0
    for d in found:
        try:
            await validate_sale_allowed(d)
            eligible += 1
        except HTTPException:
            pass
    sale_numbers = [
        f"SALE-{n:04d}" for n in (await db.execute(
            text("SELECT nextval('sale_number_seq') FROM generate_series(1, :n)"),
            {"n": eligible},
        )).scalars().all()
    ] if eligible else []

    sold, skipped, warn, events = [], [], None, []
    _num_idx = 0
    for code in codes:
        device = devices_by_code.get(code)
        if not device:
            if not is_multi:
                return await _fail(f"Device {code} not found")
            skipped.append(f"{code} (not found)")
            continue

        # ── Control Engine: sale block ────────────────────────────────────
        try:
            await validate_sale_allowed(device)
        except HTTPException as e:
            if not is_multi:
                return await _fail(e.detail, device=device)
            skipped.append(f"{code} (blocked)")
            continue

        # ── Cost Engine: below-cost warning (first one reported) ─────────
        w = below_cost_warning_for(costings.get(device.id), price)
        if w and not warn:
            warn = w

        sale_num = sale_numbers[_num_idx]
        _num_idx += 1
        sold_at = app_now()
        warranty_expires_at = compute_warranty_expiry(sold_at, wtype)
        sale = Sale(
            sale_number=sale_num, device_id=device.id,
            sale_price=price,
            customer_name=customer_name or None, customer_phone=customer_phone or None,
            customer_state=customer_state or None,
            invoice_no=invoice_no or None, payment_mode=payment_mode,
            sold_by=current_user.username, sales_person=sales_person.strip() or None,
            notes=notes or None,
            invoice_file_path=invoice_file_path or None,
            sold_at=sold_at,
            warranty_type=wtype, warranty_expires_at=warranty_expires_at,
        )
        db.add(sale)

        prev = device.current_stage
        prev_mv = open_moves.get((device.id, prev))
        if prev_mv:
            prev_mv.exited_at = app_now()

        device.current_stage = DeviceStage.sold
        device.updated_at    = app_now()
        db.add(StageMovement(device_id=device.id, from_stage=prev, to_stage=DeviceStage.sold,
                             moved_by=current_user.username, notes=f"Sold — {sale_num}"))

        await audit(db, user=current_user, action="SALE_CREATED",
                    table_name="sales", record_id=str(device.id),
                    new_value={"sale_number": sale_num, "price": str(price),
                               "below_cost": bool(w)},
                    notes=w, request=request)

        sold.append(sale_num)
        events.append({
            "sale_number": sale_num,
            "barcode": code,
            "price": str(price),
            "customer_name": customer_name or None,
            "sold_by": current_user.username,
            "_source": "sales_html",
        })

    if not sold:
        return await _fail(
            "No sales recorded — " + ("; ".join(skipped) or "no valid tag numbers"))

    await db.commit()
    for payload in events:
        publish(EventType.SALE_COMPLETED, payload, background_tasks)

    if is_multi:
        redirect = f"/sales?success={len(sold)}+devices+sold"
    else:
        redirect = f"/sales?success=Sale+{sold[0]}+recorded"
    warn_parts = []
    if warn:
        warn_parts.append(warn)
    if skipped:
        warn_parts.append(f"{len(skipped)} skipped: " + ", ".join(skipped))
    if warn_parts:
        import urllib.parse
        redirect += f"&warning={urllib.parse.quote(' | '.join(warn_parts))}"
    if xhr:
        return JSONResponse({
            "ok": True, "sold": len(sold), "skipped": skipped,
            "warning": " | ".join(warn_parts) or None, "redirect": redirect,
        })
    return RedirectResponse(url=redirect, status_code=302)


@router.get("/sales/export-selected", response_class=HTMLResponse)
async def export_selected_get(request: Request, current_user: User = Depends(allowed)):
    """Redirect GET to sales list (form should POST)."""
    return RedirectResponse(url="/sales", status_code=302)


@router.post("/sales/export-selected")
async def export_selected_sales(
    sale_ids: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Export selected sales rows as CSV. Receives comma-separated Sale UUIDs."""
    ids = [sid.strip() for sid in sale_ids.split(",") if sid.strip()]
    if not ids:
        return RedirectResponse(url="/sales", status_code=302)

    result = await db.execute(
        select(Sale, Device.barcode, Device.brand, Device.model, Device.grade, Lot.lot_number)
        .join(Device, Sale.device_id == Device.id)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Sale.id.in_(ids))
        .order_by(Sale.sold_at.desc())
    )
    rows = result.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Sale#", "Date", "Barcode", "Brand", "Model", "Lot", "Grade",
                     "Price", "Customer", "Phone", "Payment", "Sold By"])
    for row in rows:
        s = row.Sale
        writer.writerow([
            s.sale_number,
            s.sold_at.strftime("%d-%m-%Y"),
            row.barcode, row.brand, row.model, row.lot_number,
            row.grade.value if row.grade else "",
            float(s.sale_price or 0),
            s.customer_name or "", s.customer_phone or "",
            s.payment_mode or "", s.sold_by or "",
        ])
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sales_selected.csv"},
    )


@router.post("/sales/parse-invoice-pdf")
async def parse_invoice_pdf(
    pdf: UploadFile = File(...),
    current_user=Depends(allowed),
):
    """Accept a PDF upload, save it, and attempt best-effort field extraction."""
    upload_dir = Path("uploads/sale_invoices")
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"inv_{int(time.time())}_{pdf.filename}"
    dest = upload_dir / safe_name
    with open(dest, "wb") as f:
        shutil.copyfileobj(pdf.file, f)

    result: dict = {"file_path": str(dest).replace("\\", "/")}

    # Best-effort text extraction — works if pdfplumber is installed
    try:
        import pdfplumber
        with pdfplumber.open(dest) as doc:
            text_content = " ".join(p.extract_text() or "" for p in doc.pages)

        # Total / sale price
        m = re.search(r"(?i)total\s*[:\s]+(?:INR|Rs\.?|₹)?\s*([\d,]+\.?\d*)", text_content)
        if m:
            result["sale_price"] = m.group(1).replace(",", "")

        # Customer / bill-to name
        m = re.search(r"(?i)(?:customer|bill\s*to|sold\s*to)\s*[:\s]+([A-Z][^\n]{2,50})", text_content)
        if m:
            result["customer_name"] = m.group(1).strip()

        # Invoice / PO number
        m = re.search(r"(?i)(?:invoice\s*no|inv\.?\s*no|po\s*number)\s*[.:\s]+([A-Z0-9/_-]+)", text_content)
        if m:
            result["invoice_no"] = m.group(1).strip()
    except ImportError:
        pass  # pdfplumber not installed — file is saved, fields will be empty
    except Exception:
        pass  # extraction failed — still return file_path

    return JSONResponse(result)


@router.get("/sales/{sale_id}", response_class=HTMLResponse)
async def sale_detail(
    sale_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    # UUID columns require proper UUID type — bare string comparison fails with asyncpg
    try:
        sale_uuid = _uuid.UUID(sale_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="Sale not found")

    result = await db.execute(
        select(Sale, Device, Lot)
        .join(Device, Sale.device_id == Device.id)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Sale.id == sale_uuid)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Sale not found")
    sale, device, lot = row.Sale, row.Device, row.Lot
    return templates.TemplateResponse("sales/detail.html", {
        "request": request,
        "current_user": current_user,
        "sale": sale,
        "device": device,
        "lot": lot,
    })


@router.get("/sales", response_class=HTMLResponse)
async def sales_list(
    request: Request,
    q: str = Query(default=""),
    sale_no: str = Query(default=""),
    sold_by_filter: str = Query(default=""),
    customer: str = Query(default=""),
    grade: str = Query(default=""),
    lot_id: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    from sqlalchemy import case as sa_case

    base_q = (
        select(Sale, Device.barcode, Device.brand, Device.model, Device.grade,
               Lot.lot_number, Lot.buying_price, Lot.qty)
        .join(Device, Sale.device_id == Device.id)
        .join(Lot, Device.lot_id == Lot.id)
    )

    # ── Apply filters ────────────────────────────────────────────────────────
    if q:
        like = f"%{q}%"
        base_q = base_q.where(or_(
            Device.barcode.ilike(like),
            Device.brand.ilike(like),
            Device.model.ilike(like),
        ))
    if sale_no:
        base_q = base_q.where(Sale.sale_number.ilike(f"%{sale_no}%"))
    if sold_by_filter:
        base_q = base_q.where(Sale.sold_by == sold_by_filter)
    if customer:
        base_q = base_q.where(Sale.customer_name.ilike(f"%{customer}%"))
    if grade:
        base_q = base_q.where(Device.grade == grade)
    if lot_id:
        base_q = base_q.where(Device.lot_id == lot_id)

    result = await db.execute(base_q.order_by(Sale.sold_at.desc()))
    sales = result.all()
    total = len(sales)

    # ── Registered device stats (single query) ───────────────────────────────
    dev_stats = (await db.execute(
        select(
            func.count(Device.id).label("total"),
            func.count(sa_case((Device.current_stage == DeviceStage.sold, 1))).label("sold"),
        ).where(Device.is_active == True)
    )).one()
    total_registered = dev_stats.total
    total_devices_sold = dev_stats.sold
    total_available = total_registered - total_devices_sold

    # ── Sales-user dropdown ──────────────────────────────────────────────────
    sellers_result = await db.execute(
        select(Sale.sold_by).distinct().where(Sale.sold_by.isnot(None)).order_by(Sale.sold_by)
    )
    sellers = [r.sold_by for r in sellers_result]

    # ── Lot dropdown ─────────────────────────────────────────────────────────
    lots_result = await db.execute(select(Lot).order_by(Lot.lot_number))
    lots = lots_result.scalars().all()

    return templates.TemplateResponse("sales/list.html", {
        "request": request,
        "sales": sales,
        "lots": lots,
        "sellers": sellers,
        "selected_lot": lot_id,
        "current_user": current_user,
        "total": total,
        # Filters
        "q": q,
        "sale_no": sale_no,
        "sold_by_filter": sold_by_filter,
        "customer": customer,
        "grade": grade,
        # Device stats
        "total_registered": total_registered,
        "total_devices_sold": total_devices_sold,
        "total_available": total_available,
    })


@router.get("/returns", response_class=HTMLResponse)
async def returns_list(request: Request, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(allowed)):
    result = await db.execute(
        select(Return, Device.barcode, Device.brand, Device.model,
               Sale.sale_price, Sale.sale_number)
        .join(Device, Return.device_id == Device.id)
        .join(Sale, Return.sale_id == Sale.id)
        .order_by(Return.return_date.desc())
    )
    returns = result.all()
    return templates.TemplateResponse("sales/returns_list.html", {
        "request": request, "returns": returns, "current_user": current_user,
    })


@router.get("/returns/new", response_class=HTMLResponse)
async def return_form(request: Request, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(allowed)):
    from models.cost_config import CostConfig
    row = (await db.execute(
        select(CostConfig).where(CostConfig.key == "default_paid_repair")
    )).scalar_one_or_none()
    default_paid_repair = float(row.value) if row else 1500.0
    return templates.TemplateResponse("sales/return_form.html", {
        "request": request, "current_user": current_user, "error": None, "sale": None,
        "default_paid_repair": default_paid_repair,
    })


@router.post("/returns/new")
async def process_return(
    request: Request,
    barcode: str = Form(...),
    reason: str = Form(""),
    condition_on_return: str = Form(""),
    action_taken: str = Form("restock"),
    refund_amount: str = Form("0"),
    notes: str = Form(""),
    return_type: str = Form("customer"),
    complaint_text: str = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    _perm: User = Depends(require_module_perm("returns", "add")),
):
    dev_result = await db.execute(select(Device).where(Device.barcode == barcode))
    device = dev_result.scalar_one_or_none()
    if not device:
        return templates.TemplateResponse("sales/return_form.html", {
            "request": request, "current_user": current_user,
            "error": f"Device {barcode} not found", "sale": None,
        })

    sale_result = await db.execute(
        select(Sale).where(Sale.device_id == device.id)
        .order_by(Sale.sold_at.desc()).limit(1)
    )
    sale = sale_result.scalars().first()
    if not sale:
        return templates.TemplateResponse("sales/return_form.html", {
            "request": request, "current_user": current_user,
            "error": "No sale found for this device", "sale": None,
        })

    # Guard: prevent duplicate return for the same sale
    existing_return = (await db.execute(
        select(Return).where(Return.sale_id == sale.id)
    )).scalars().first()
    if existing_return:
        return templates.TemplateResponse("sales/return_form.html", {
            "request": request, "current_user": current_user,
            "error": (f"A return for sale {sale.sale_number} already exists "
                      f"(processed on {existing_return.return_date.strftime('%d %b %Y')}). "
                      "Cannot create a duplicate return."),
            "sale": sale,
        })

    # Mandatory field validation
    if not reason or not reason.strip():
        return templates.TemplateResponse("sales/return_form.html", {
            "request": request, "current_user": current_user,
            "error": "Return Reason is required.", "sale": sale,
        })
    if not condition_on_return or not condition_on_return.strip():
        return templates.TemplateResponse("sales/return_form.html", {
            "request": request, "current_user": current_user,
            "error": "Condition on Return is required.", "sale": sale,
        })

    # Determine intended re-entry stage (used once approved)
    if action_taken == "scrap":
        reentered_stage = "scrapped"
    else:
        reentered_stage = "iqc"

    # Server-computed warranty status at RMA time — never trust client input
    rtype = return_type if return_type in ("customer", "dealer") else "customer"
    warranty_status = warranty_status_for_sale(sale)

    # Create return as PENDING — device stage unchanged until manager approves
    ret = Return(
        sale_id=sale.id, device_id=device.id,
        reason=reason or None, condition_on_return=condition_on_return or None,
        action_taken=action_taken or None,
        reentered_stage=reentered_stage,
        processed_by=current_user.username,
        refund_amount=Decimal(refund_amount) if refund_amount else None,
        notes=notes or None,
        approval_status='pending',
        return_type=rtype,
        serial_captured=barcode or None,
        warranty_status=warranty_status,
        complaint_text=complaint_text or None,
    )
    db.add(ret)

    # Item 6: mark the device as returned (Device Profile "Return Status" → Yes)
    device.return_status = True

    await audit(db, user=current_user, action="RETURN_SUBMITTED",
                table_name="returns", record_id=str(device.id),
                new_value={"sale": sale.sale_number, "reason": reason,
                           "action": action_taken, "approval_status": "pending",
                           "return_type": rtype, "warranty_status": warranty_status,
                           "complaint_text": complaint_text or None},
                request=request)

    await db.commit()
    return RedirectResponse(url="/returns?success=Return+submitted+for+manager+approval",
                            status_code=302)


# ── Manager: pending returns list ─────────────────────────────────────────────

MANAGER_ROLES = (UserRole.admin, UserRole.sales_manager)


@router.get("/returns/pending", response_class=HTMLResponse)
async def pending_returns(request: Request, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    if current_user.role not in MANAGER_ROLES:
        return RedirectResponse(url="/returns?error=Access+denied", status_code=302)
    result = await db.execute(
        select(Return, Device.barcode, Device.brand, Device.model,
               Sale.sale_price, Sale.sale_number)
        .join(Device, Return.device_id == Device.id)
        .join(Sale, Return.sale_id == Sale.id)
        .where(Return.approval_status == 'pending')
        .order_by(Return.return_date.desc())
    )
    pending = result.all()
    return templates.TemplateResponse("sales/returns_pending.html", {
        "request": request, "pending": pending, "current_user": current_user,
    })


# ── Manager: approve return ───────────────────────────────────────────────────

@router.post("/returns/{return_id}/approve")
async def approve_return(
    request: Request,
    return_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in MANAGER_ROLES:
        return RedirectResponse(url="/returns/pending?error=Access+denied", status_code=302)

    ret_result = await db.execute(select(Return).where(Return.id == return_id))
    ret = ret_result.scalar_one_or_none()
    if not ret:
        return RedirectResponse(url="/returns/pending?error=Return+not+found", status_code=302)
    if ret.approval_status != 'pending':
        return RedirectResponse(
            url=f"/returns/pending?error=Return+already+{ret.approval_status}", status_code=302
        )

    # Move device to intended stage
    dev_result = await db.execute(select(Device).where(Device.id == ret.device_id))
    device = dev_result.scalar_one_or_none()
    if device:
        if ret.reentered_stage == "scrapped":
            to_stage = DeviceStage.scrapped
        else:
            to_stage = DeviceStage.iqc

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

        device.current_stage = to_stage
        device.updated_at    = app_now()
        db.add(StageMovement(device_id=device.id, from_stage=prev, to_stage=to_stage,
                             moved_by=current_user.username,
                             notes=f"Return approved ({ret.action_taken}): {ret.reason}"))

    ret.approval_status = 'approved'
    ret.approved_by     = current_user.username
    ret.approved_at     = app_now()

    await audit(db, user=current_user, action="RETURN_APPROVED",
                table_name="returns", record_id=str(ret.id),
                new_value={"approved_by": current_user.username,
                           "reentered_stage": ret.reentered_stage},
                request=request)
    await db.commit()
    return RedirectResponse(url="/returns/pending?success=Return+approved", status_code=302)


# ── Manager: reject return ────────────────────────────────────────────────────

@router.post("/returns/{return_id}/reject")
async def reject_return(
    request: Request,
    return_id: str,
    rejection_reason: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in MANAGER_ROLES:
        return RedirectResponse(url="/returns/pending?error=Access+denied", status_code=302)

    ret_result = await db.execute(select(Return).where(Return.id == return_id))
    ret = ret_result.scalar_one_or_none()
    if not ret:
        return RedirectResponse(url="/returns/pending?error=Return+not+found", status_code=302)
    if ret.approval_status != 'pending':
        return RedirectResponse(
            url=f"/returns/pending?error=Return+already+{ret.approval_status}", status_code=302
        )

    ret.approval_status  = 'rejected'
    ret.approved_by      = current_user.username
    ret.approved_at      = app_now()
    ret.rejection_reason = rejection_reason or None
    # Device stays sold — no stage change on rejection

    await audit(db, user=current_user, action="RETURN_REJECTED",
                table_name="returns", record_id=str(ret.id),
                new_value={"rejected_by": current_user.username,
                           "reason": rejection_reason},
                request=request)
    await db.commit()
    return RedirectResponse(url="/returns/pending?success=Return+rejected", status_code=302)
