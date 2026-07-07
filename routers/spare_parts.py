"""
Spare Parts Router — double-entry ledger + negative stock guard + audit
"""
import csv
import io
import secrets
from templates_config import templates
from datetime import datetime
from fastapi import APIRouter, Depends, Form, File, UploadFile, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from models.user import User, UserRole
from models.device import Device
from models.lot import Lot
from models.spare_parts import SparePart, SparePartPurchase, SparePartConsumption, RAMTracking
from models.parts_grn import PartsGRN, PartsGRNLineItem
from utils.master_data import master_values
from models.repair import RepairJob, RepairStatus
from models.engines import SparePartsLedger
from models.part_request import PartRequest, PartSourcingRequest
from auth.dependencies import get_current_user, require_roles, verify_csrf, require_module_perm
from services.audit_engine import audit

router = APIRouter(tags=["spare_parts"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.spare_parts_manager)

BULK_CSV_HEADERS = ["part_name", "category", "part_brand", "part_model", "physical_qty",
                    "price", "invoice_number", "po_number", "vendor_name", "grn_number"]
BULK_CSV_EXAMPLE = ["DDR4 8GB RAM", "RAM", "Samsung", "M471A1K43", "10",
                    "500", "Internal", "Internal", "Internal", "Internal"]


def _new_bulk_part_id() -> str:
    return f"{secrets.randbelow(90_000_000) + 10_000_000:08d}"


async def _next_part_code(db: AsyncSession) -> str:
    result = await db.execute(select(func.count(SparePart.id)))
    count  = (result.scalar() or 0) + 1
    return f"PART-{count:04d}"


async def _computed_stock(part_id, db: AsyncSession) -> int:
    """Derive stock from ledger rather than stored column."""
    in_result  = await db.execute(
        select(func.sum(SparePartsLedger.qty))
        .where(SparePartsLedger.part_id == part_id, SparePartsLedger.entry_type == "IN")
    )
    out_result = await db.execute(
        select(func.sum(SparePartsLedger.qty))
        .where(SparePartsLedger.part_id == part_id, SparePartsLedger.entry_type == "OUT")
    )
    stock_in   = in_result.scalar() or 0
    stock_out  = out_result.scalar() or 0
    return stock_in - stock_out


@router.get("/spare-parts", response_class=HTMLResponse)
async def parts_list(request: Request, db: AsyncSession = Depends(get_db),
                     current_user: User = Depends(allowed)):
    from datetime import date

    # Part master
    result = await db.execute(
        select(SparePart).where(SparePart.is_trashed == False)
        .order_by(SparePart.category, SparePart.name)
    )
    parts  = result.scalars().all()

    # "Consumed" per part — qty handed over (Part Request status="handed_over")
    # that hasn't been deducted from qty_in_stock yet, so the Part Master
    # table's In Stock column can show live availability instead of raw stock.
    consumed_rows = (await db.execute(
        select(PartRequest.part_id, func.sum(PartRequest.qty_handed_over))
        .where(PartRequest.status == "handed_over", PartRequest.part_id.isnot(None))
        .group_by(PartRequest.part_id)
    )).all()
    consumed_by_part = {str(pid): int(total or 0) for pid, total in consumed_rows}

    # Summary stats
    total_part_types = len(parts)
    below_min_count  = sum(1 for p in parts if p.qty_in_stock <= p.min_stock_alert)
    out_of_stock_count = sum(
        1 for p in parts if int(p.qty_in_stock or 0) - consumed_by_part.get(str(p.id), 0) <= 0
    )
    total_stock_value = sum(float(p.unit_price or 0) * int(p.qty_in_stock or 0) for p in parts)

    part_requested_count = (await db.execute(
        select(func.count(PartRequest.id)).where(PartRequest.status == "requested")
    )).scalar() or 0
    part_sourced_count = (await db.execute(
        select(func.count(PartSourcingRequest.id)).where(PartSourcingRequest.status == "open")
    )).scalar() or 0

    # Last 100 purchases (with part name + code)
    purchases_result = await db.execute(
        select(SparePartPurchase, SparePart.name, SparePart.part_code)
        .join(SparePart, SparePartPurchase.part_id == SparePart.id)
        .order_by(SparePartPurchase.purchase_date.desc())
        .limit(100)
    )
    purchases = purchases_result.all()

    # Last 100 consumptions (with part name + code + device barcode)
    consumptions_result = await db.execute(
        select(SparePartConsumption, SparePart.name, SparePart.part_code, Device.barcode)
        .join(SparePart, SparePartConsumption.part_id == SparePart.id)
        .outerjoin(Device, SparePartConsumption.device_id == Device.id)
        .order_by(SparePartConsumption.used_at.desc())
        .limit(100)
    )
    consumptions = consumptions_result.all()

    # Parts consumed this month (count)
    today = date.today()
    consumed_this_month = sum(
        1 for c, *_ in consumptions
        if c.used_at and c.used_at.year == today.year and c.used_at.month == today.month
    )

    # ── Part requests raised by engineers (#11/#14) ──────────────────────────
    part_reqs = (await db.execute(
        select(PartRequest).order_by(PartRequest.created_at.desc()).limit(200)
    )).scalars().all()
    part_stock = {str(p.id): int(p.qty_in_stock or 0) for p in parts}

    # ── Pending part-sourcing requests, mirrored read-only from CRM (#15) ────
    sourcing = (await db.execute(
        select(PartSourcingRequest).order_by(PartSourcingRequest.created_at.desc()).limit(200)
    )).scalars().all()

    # map source_deal_id (UUID string) -> CRMSourcingDeal for download links + display
    from models.crm import CRMSourcingDeal
    deal_map = {}
    valid_ids = []
    for s in sourcing:
        if s.source_deal_id:
            try:
                valid_ids.append(str(__import__("uuid").UUID(s.source_deal_id)))
            except (ValueError, AttributeError, TypeError):
                continue
    if valid_ids:
        dm_r = await db.execute(select(CRMSourcingDeal).where(CRMSourcingDeal.id.in_(valid_ids)))
        for d in dm_r.scalars().all():
            deal_map[str(d.id)] = d

    # ── GRN mapping for Part Master (#new): PartsGRNLineItem.part_id stores the
    # SparePart.part_code (see routers/parts_grn.py _new_part_id upsert). Map
    # each part_code to its most recent GRN line item + parent GRN number.
    part_codes = [p.part_code for p in parts if p.part_code]
    grn_by_part_code = {}
    if part_codes:
        li_rows = (await db.execute(
            select(PartsGRNLineItem, PartsGRN.grn_number)
            .join(PartsGRN, PartsGRNLineItem.grn_id == PartsGRN.id)
            .where(PartsGRNLineItem.part_id.in_(part_codes))
            .order_by(PartsGRN.date_received.desc().nullslast())
        )).all()
        for li, grn_number in li_rows:
            if li.part_id not in grn_by_part_code:
                grn_by_part_code[li.part_id] = {
                    "grn_id": str(li.grn_id), "grn_number": grn_number,
                    "is_harvest": li.is_harvest,
                }

    return templates.TemplateResponse("spare_parts/list.html", {
        "request": request, "parts": parts, "current_user": current_user,
        "purchases": purchases, "consumptions": consumptions,
        "total_part_types": total_part_types,
        "below_min_count": below_min_count,
        "out_of_stock_count": out_of_stock_count,
        "part_requested_count": part_requested_count,
        "part_sourced_count": part_sourced_count,
        "total_stock_value": total_stock_value,
        "consumed_this_month": consumed_this_month,
        "consumed_by_part": consumed_by_part,
        "part_reqs": part_reqs, "part_stock": part_stock, "sourcing": sourcing,
        "deal_map": deal_map,
        "grn_docs": {},
        "grn_by_part_code": grn_by_part_code,
        "harvest_categories": await master_values(db, "iqc_part_category"),
    })


@router.get("/spare-parts/new", response_class=HTMLResponse)
async def new_part_form(request: Request, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(allowed)):
    next_code = await _next_part_code(db)
    return templates.TemplateResponse("spare_parts/part_form.html", {
        "request": request, "next_code": next_code, "categories": await master_values(db, "iqc_part_category"),
        "current_user": current_user, "error": None,
    })


@router.post("/spare-parts/new")
async def create_part(
    request: Request,
    part_code: str = Form(...),
    name: str = Form(...),
    category: str = Form(...),
    unit_price: str = Form("0"),
    min_stock_alert: int = Form(5),
    supplier: str = Form(""),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    _perm: User = Depends(require_module_perm("spare_parts", "add")),
):
    part = SparePart(part_code=part_code, name=name, category=category,
                     unit_price=float(unit_price), min_stock_alert=min_stock_alert,
                     supplier=supplier or None, notes=notes or None, source='new')
    db.add(part)
    await db.commit()
    return RedirectResponse(url="/spare-parts?success=Part+added", status_code=302)


@router.get("/spare-parts/{part_id}/edit", response_class=HTMLResponse)
async def edit_part_form(part_id: str, request: Request,
                         db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(allowed)):
    result = await db.execute(select(SparePart).where(SparePart.id == part_id))
    part = result.scalar_one_or_none()
    if not part:
        raise HTTPException(404, "Part not found")
    return templates.TemplateResponse("spare_parts/edit_form.html", {
        "request": request, "part": part, "categories": await master_values(db, "iqc_part_category"),
        "current_user": current_user, "error": None,
    })


@router.post("/spare-parts/{part_id}/edit")
async def update_part(
    part_id: str,
    name: str = Form(...),
    category: str = Form(...),
    unit_price: str = Form("0"),
    qty_in_stock: int = Form(None),
    min_stock_alert: int = Form(5),
    supplier: str = Form(""),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    result = await db.execute(select(SparePart).where(SparePart.id == part_id))
    part = result.scalar_one_or_none()
    if not part:
        raise HTTPException(404, "Part not found")
    part.name = name; part.category = category; part.unit_price = float(unit_price)
    part.min_stock_alert = min_stock_alert; part.supplier = supplier or None; part.notes = notes or None
    if qty_in_stock is not None:
        new_qty = max(0, int(qty_in_stock))
        old_qty = int(part.qty_in_stock or 0)
        delta = new_qty - old_qty
        if delta != 0:
            # Write a compensating ledger entry so _computed_stock() (ledger-based,
            # used by the negative-stock guard in record_consumption) stays in sync
            # with qty_in_stock (column-based, used by Part Master + Part Request
            # display). Previously this edit path overwrote qty_in_stock directly
            # with no ledger entry, letting the two diverge over time.
            db.add(SparePartsLedger(
                part_id=part.id,
                entry_type="IN" if delta > 0 else "OUT",
                qty=abs(delta),
                cost_per_unit=float(part.unit_price),
                total_cost=abs(delta) * float(part.unit_price),
                reference_type="adjustment",
                reference_id=None,
                created_by=current_user.username,
                notes=f"Part Master manual stock adjustment: {old_qty} -> {new_qty}",
            ))
            await audit(db, action="PART_STOCK_ADJUSTED", user=current_user,
                        table_name="spare_parts_ledger", record_id=str(part.id),
                        notes=f"Adjust {old_qty} -> {new_qty} ({'+' if delta>0 else ''}{delta})")
        part.qty_in_stock = new_qty
    await db.commit()
    return RedirectResponse(url="/spare-parts?success=Part+updated", status_code=302)


@router.post("/spare-parts/{part_id}/delete")
async def delete_part(part_id: str, request: Request,
                      db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(allowed)):
    result = await db.execute(select(SparePart).where(SparePart.id == part_id))
    part = result.scalar_one_or_none()
    if not part:
        raise HTTPException(404, "Part not found")
    part.is_trashed = True
    part.trashed_at = datetime.utcnow()
    await audit(db, action="PART_MASTER_DELETE", user=current_user,
                table_name="spare_parts", record_id=str(part.id))
    await db.commit()
    return RedirectResponse(url="/spare-parts?success=Part+deleted", status_code=302)


@router.get("/spare-parts/bulk-template")
async def download_bulk_template(current_user: User = Depends(get_current_user)):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(BULK_CSV_HEADERS)
    writer.writerow(BULK_CSV_EXAMPLE)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=part_master_bulk_template.csv"},
    )


@router.post("/spare-parts/bulk-upload")
async def bulk_upload_parts(
    request: Request,
    file: UploadFile = File(...),
    source: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Bulk-add Part Master rows from CSV via Download Sample / Upload New /
    Upload Harvest on the Parts Dashboard. Mirrors the manual Part GRN 'Add
    Item' flow: creates a PartsGRN header for the batch, a PartsGRNLineItem
    per row, and upserts the row into SparePart with the given source
    ('new' or 'harvest')."""
    if source not in ("new", "harvest"):
        raise HTTPException(400, "Invalid source")

    content = await file.read()
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise HTTPException(400, "Could not decode file")

    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return RedirectResponse(url="/spare-parts?error=No+rows+found+in+file", status_code=302)

    grn_number = f"BULK-{secrets.randbelow(900_000) + 100_000}"
    grn = PartsGRN(
        grn_number=grn_number,
        po_number="Internal" if source == "harvest" else None,
        vendor_name="Internal" if source == "harvest" else None,
        invoice_number="Internal" if source == "harvest" else None,
        created_by=current_user.username,
    )
    db.add(grn)
    await db.flush()

    inserted, errors = 0, []
    for i, row in enumerate(rows, start=2):
        try:
            part_name = (row.get("part_name") or "").strip()
            if not part_name:
                errors.append(f"Row {i}: part_name is required")
                continue
            part_id = _new_bulk_part_id()
            qty = int((row.get("physical_qty") or "0").strip() or 0)
            price_raw = (row.get("price") or "").strip()
            price = float(price_raw) if price_raw else 0.0
            category = (row.get("category") or "Other").strip() or "Other"
            invoice_number = (row.get("invoice_number") or "Internal").strip() or "Internal"
            po_number = (row.get("po_number") or "Internal").strip() or "Internal"
            vendor_name = (row.get("vendor_name") or "Internal").strip() or "Internal"
            row_grn_number = (row.get("grn_number") or "Internal").strip() or "Internal"

            db.add(PartsGRNLineItem(
                grn_id=grn.id,
                part_id=part_id,
                grn_number=row_grn_number,
                po_number=po_number,
                vendor_name=vendor_name,
                invoice_number=invoice_number,
                part_name=part_name,
                part_brand=(row.get("part_brand") or "").strip() or None,
                part_model=(row.get("part_model") or "").strip() or None,
                invoice_qty=qty,
                physical_qty=qty,
                price=price,
                category=category,
                is_harvest=(source == "harvest"),
            ))

            existing_part = (await db.execute(
                select(SparePart).where(SparePart.part_code == part_id)
            )).scalar_one_or_none()
            if existing_part:
                existing_part.qty_in_stock = int(existing_part.qty_in_stock or 0) + qty
                existing_part.unit_price = price
                existing_part.is_trashed = False
                existing_part.trashed_at = None
            else:
                db.add(SparePart(
                    part_code=part_id, name=part_name, category=category,
                    unit_price=price, qty_in_stock=qty, min_stock_alert=5,
                    supplier=vendor_name, source=source,
                ))
            inserted += 1
        except Exception as e:
            errors.append(f"Row {i}: {str(e)}")

    await audit(db, action="PART_MASTER_BULK_UPLOAD", user=current_user,
                table_name="spare_parts", record_id=str(grn.id),
                new_value={"source": source, "inserted": inserted, "errors": len(errors)})
    await db.commit()
    return templates.TemplateResponse("bulk_upload/result.html", {
        "request": request, "current_user": current_user,
        "upload_type": f"Part Master ({'Harvest' if source == 'harvest' else 'New'})",
        "inserted": inserted, "errors": errors,
        "back_url": "/spare-parts",
    })


@router.get("/spare-parts/purchase", response_class=HTMLResponse)
async def purchase_log(request: Request, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(allowed)):
    result = await db.execute(
        select(SparePartPurchase, SparePart.name, SparePart.part_code)
        .join(SparePart, SparePartPurchase.part_id == SparePart.id)
        .order_by(SparePartPurchase.purchase_date.desc())
    )
    purchases   = result.all()
    parts_result= await db.execute(select(SparePart).order_by(SparePart.name))
    parts       = parts_result.scalars().all()
    return templates.TemplateResponse("spare_parts/purchase.html", {
        "request": request, "purchases": purchases, "parts": parts, "current_user": current_user,
    })


@router.post("/spare-parts/purchase")
async def record_purchase(
    request: Request,
    part_id: str = Form(...),
    qty: int = Form(...),
    unit_price: str = Form(...),
    supplier: str = Form(""),
    invoice_no: str = Form(""),
    purchase_date: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    total = float(unit_price) * qty
    purchase = SparePartPurchase(
        part_id=part_id, qty=qty, unit_price=float(unit_price), total_price=total,
        supplier=supplier or None, invoice_no=invoice_no or None,
        purchase_date=datetime.strptime(purchase_date, "%Y-%m-%d"),
        purchased_by=current_user.username,
    )
    db.add(purchase)

    # ── Ledger entry: IN ──────────────────────────────────────────────────
    db.add(SparePartsLedger(
        part_id=part_id, entry_type="IN", qty=qty,
        cost_per_unit=float(unit_price), total_cost=total,
        reference_type="purchase", reference_id=None,
        created_by=current_user.username,
    ))

    # Keep qty_in_stock in sync (for read performance)
    result = await db.execute(select(SparePart).where(SparePart.id == part_id))
    part = result.scalar_one_or_none()
    if part:
        part.qty_in_stock += qty
        part.unit_price   = float(unit_price)

    log = await audit(db, action="PARTS_PURCHASED", user=current_user,
                      table_name="spare_parts_ledger",
                      notes=f"IN {qty}x part {part_id} @ {unit_price}")
    db.add(log)

    await db.commit()
    return RedirectResponse(url="/spare-parts/purchase?success=Purchase+recorded", status_code=302)


@router.get("/spare-parts/consume", response_class=HTMLResponse)
async def consume_log(request: Request, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    result = await db.execute(
        select(SparePartConsumption, SparePart.name, Device.barcode)
        .join(SparePart, SparePartConsumption.part_id == SparePart.id)
        .outerjoin(Device, SparePartConsumption.device_id == Device.id)
        .order_by(SparePartConsumption.used_at.desc())
    )
    consumptions = result.all()
    parts_result = await db.execute(
        select(SparePart).where(SparePart.qty_in_stock > 0).order_by(SparePart.name)
    )
    parts      = parts_result.scalars().all()
    lots_result= await db.execute(select(Lot).order_by(Lot.lot_number))
    lots       = lots_result.scalars().all()
    return templates.TemplateResponse("spare_parts/consume.html", {
        "request": request, "consumptions": consumptions, "parts": parts,
        "lots": lots, "current_user": current_user,
    })


@router.post("/spare-parts/consume")
async def record_consumption(
    request: Request,
    part_id: str = Form(...),
    qty_used: int = Form(...),
    device_barcode: str = Form(""),
    lot_id: str = Form(""),
    stage: str = Form(""),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    part_result = await db.execute(select(SparePart).where(SparePart.id == part_id))
    part = part_result.scalar_one_or_none()
    if not part:
        raise HTTPException(404, "Part not found")

    # ── Negative stock guard (BR-05 / BR-16) ─────────────────────────────
    current_stock = await _computed_stock(part_id, db)
    if current_stock < qty_used:
        raise HTTPException(
            409,
            f"INVENTORY ENGINE: Insufficient stock — available {current_stock}, "
            f"requested {qty_used}. Consumption blocked."
        )

    device_id = None
    repair_job_id = None
    if device_barcode:
        dev_result = await db.execute(select(Device).where(Device.barcode == device_barcode))
        dev = dev_result.scalar_one_or_none()
        if dev:
            device_id = dev.id
            # Auto-link to the open repair job for this device (if any)
            job_result = await db.execute(
                select(RepairJob)
                .where(
                    RepairJob.device_id == dev.id,
                    RepairJob.status == RepairStatus.in_progress,
                )
                .order_by(RepairJob.started_at.desc())
                .limit(1)
            )
            open_job = job_result.scalars().first()
            if open_job:
                repair_job_id = open_job.id

    total = float(part.unit_price) * qty_used
    consumption = SparePartConsumption(
        part_id=part_id, qty_used=qty_used,
        unit_cost=float(part.unit_price), total_cost=total,
        device_id=device_id,
        repair_job_id=repair_job_id,
        lot_id=lot_id or None, stage=stage or None,
        used_by=current_user.username, notes=notes or None,
    )
    db.add(consumption)

    # ── Ledger entry: OUT ─────────────────────────────────────────────────
    db.add(SparePartsLedger(
        part_id=part_id, entry_type="OUT", qty=qty_used,
        cost_per_unit=float(part.unit_price), total_cost=total,
        reference_type="device_repair",
        reference_id=str(device_id) if device_id else None,
        device_id=device_id,
        created_by=current_user.username,
        notes=notes or None,
    ))

    # Keep qty_in_stock in sync
    part.qty_in_stock = max(0, part.qty_in_stock - qty_used)

    # ── Update device_costing if device is known ──────────────────────────
    if device_id:
        from services.cost_engine import refresh_parts_cost
        dev_r = await db.execute(select(Device).where(Device.id == device_id))
        dev   = dev_r.scalar_one_or_none()
        if dev:
            await refresh_parts_cost(dev, db)

    log = await audit(db, action="PARTS_CONSUMED", user=current_user,
                      table_name="spare_parts_ledger",
                      notes=f"OUT {qty_used}x {part.name} for device {device_barcode or 'N/A'}")
    db.add(log)

    await db.commit()
    return RedirectResponse(url="/spare-parts/consume?success=Consumption+recorded", status_code=302)


@router.get("/ram-tracking", response_class=HTMLResponse)
async def ram_list(request: Request, db: AsyncSession = Depends(get_db),
                   current_user: User = Depends(allowed)):
    result = await db.execute(
        select(RAMTracking, Device.barcode)
        .outerjoin(Device, RAMTracking.device_id == Device.id)
        .order_by(RAMTracking.at.desc())
    )
    entries = result.all()
    devices_result = await db.execute(select(Device).order_by(Device.barcode))
    devices = devices_result.scalars().all()
    return templates.TemplateResponse("spare_parts/ram.html", {
        "request": request, "entries": entries, "devices": devices, "current_user": current_user,
    })


@router.post("/ram-tracking")
async def record_ram(
    action: str = Form(...),
    device_barcode: str = Form(""),
    destination_barcode: str = Form(""),
    ram_gb: int = Form(...),
    ram_type: str = Form(""),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    device_id = None; dest_id = None
    if device_barcode:
        r = await db.execute(select(Device).where(Device.barcode == device_barcode))
        d = r.scalar_one_or_none()
        if d:
            device_id = d.id
            if action == "removed":
                d.ram_gb = max(0, (d.ram_gb or 0) - ram_gb)
    if destination_barcode:
        r = await db.execute(select(Device).where(Device.barcode == destination_barcode))
        d = r.scalar_one_or_none()
        if d:
            dest_id = d.id
            if action in ("added", "cannibalized"):
                d.ram_gb = (d.ram_gb or 0) + ram_gb
    db.add(RAMTracking(action=action, device_id=device_id, destination_device_id=dest_id,
                       ram_gb=ram_gb, ram_type=ram_type or None,
                       by_user=current_user.username, notes=notes or None))
    await db.commit()
    return RedirectResponse(url="/ram-tracking?success=RAM+logged", status_code=302)


@router.post("/spare-parts/{part_id}/procure")
async def procure_from_master(part_id: str, request: Request,
                              db: AsyncSession = Depends(get_db),
                              current_user: User = Depends(allowed)):
    import uuid as _uuid
    try:
        uid = _uuid.UUID(part_id)
    except ValueError:
        raise HTTPException(404, "Part not found")
    part = (await db.execute(select(SparePart).where(SparePart.id == uid))).scalar_one_or_none()
    if not part:
        raise HTTPException(404, "Part not found")
    db.add(PartSourcingRequest(
        part_id=part.id,
        part_code=part.part_code,
        part_name=part.name,
        qty_requested=1,
        raised_by=current_user.username,
        status="open",
    ))
    await audit(db, action="PART_MASTER_PROCURE", user=current_user,
                table_name="part_sourcing_requests", record_id=str(part.id))
    await db.commit()
    return RedirectResponse(url="/spare-parts?success=Sent+to+sourcing", status_code=302)
