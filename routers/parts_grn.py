"""
Parts GRN Router — Goods Receipt Note for spare parts procurement
"""
import os
import json
import secrets
from decimal import Decimal, InvalidOperation
from datetime import datetime
from templates_config import templates
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Form, File, UploadFile, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from models.user import User, UserRole
from models.parts_grn import PartsGRN, PartsGRNLineItem
from models.spare_parts import SparePart
from auth.dependencies import get_current_user, require_roles, verify_csrf
from services.audit_engine import audit
from config import UPLOADS_DIR

router = APIRouter(prefix="/parts-grn", tags=["parts_grn"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.spare_parts_manager)

PARTS_GRN_DIR = os.path.join(UPLOADS_DIR, "parts_grn")
os.makedirs(PARTS_GRN_DIR, exist_ok=True)

MAIN_CATEGORIES = ["Hardware", "Accessories", "Consumables", "Other"]
CATEGORIES = ["RAM", "HDD", "SSD", "Battery", "Screen", "Keyboard",
              "Charger", "Motherboard", "Cable", "Adapter", "Fan", "Speaker", "Webcam", "Other"]


def _f(v: str | None) -> str | None:
    return v.strip() if v and v.strip() else None


def _i(v) -> int | None:
    if v is None:
        return None
    try:
        return int(str(v).strip())
    except (ValueError, TypeError):
        return None


def _d(v) -> Decimal | None:
    if v is None:
        return None
    try:
        s = str(v).strip()
        return Decimal(s) if s else None
    except InvalidOperation:
        return None


def _parse_date(s: str | None) -> datetime | None:
    if not s or not s.strip():
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except ValueError:
        return None


async def _save_upload(upload: UploadFile | None, prefix: str) -> str | None:
    if not upload or not upload.filename:
        return None
    data = await upload.read()
    if not data:
        return None
    safe = upload.filename.replace("/", "_").replace("\\", "_")
    stored = f"{prefix}_{safe}"
    with open(os.path.join(PARTS_GRN_DIR, stored), "wb") as f:
        f.write(data)
    return stored


async def _next_grn_number(db: AsyncSession) -> str:
    result = await db.execute(select(func.count(PartsGRN.id)))
    count = (result.scalar() or 0) + 1
    return f"{count:012d}"


def _new_part_id() -> str:
    return f"{secrets.randbelow(90_000_000) + 10_000_000:08d}"


@router.get("", response_class=HTMLResponse)
async def grn_list(request: Request, db: AsyncSession = Depends(get_db),
                   current_user: User = Depends(allowed)):
    result = await db.execute(
        select(PartsGRN).order_by(PartsGRN.created_at.desc()).limit(200)
    )
    grns = result.scalars().all()
    return templates.TemplateResponse("spare_parts/parts_grn_list.html", {
        "request": request, "current_user": current_user, "grns": grns,
    })


@router.get("/new", response_class=HTMLResponse)
async def grn_new_form(request: Request, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(allowed)):
    grn_number = await _next_grn_number(db)
    return templates.TemplateResponse("spare_parts/parts_grn_form.html", {
        "request": request, "current_user": current_user,
        "grn": None, "grn_number": grn_number, "line_items": [],
        "main_categories": MAIN_CATEGORIES, "categories": CATEGORIES,
    })


@router.post("/new", response_class=HTMLResponse)
async def grn_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    po_number: str = Form(default=""),
    po_date: str = Form(default=""),
    invoice_number: str = Form(default=""),
    invoice_date: str = Form(default=""),
    eway_bill_number: str = Form(default=""),
    eway_bill_date: str = Form(default=""),
    vehicle_number: str = Form(default=""),
    date_received: str = Form(default=""),
    vendor_name: str = Form(default=""),
    invoice_value: str = Form(default=""),
    sgst: str = Form(default=""),
    cgst: str = Form(default=""),
    igst: str = Form(default=""),
    tax_amount: str = Form(default=""),
    total_po_qty: str = Form(default=""),
    total_invoice_qty: str = Form(default=""),
    total_physical_qty: str = Form(default=""),
    total_amount_invoice: str = Form(default=""),
    line_items_json: str = Form(default="[]"),
    po_file: UploadFile = File(default=None),
    invoice_file: UploadFile = File(default=None),
    eway_bill_file: UploadFile = File(default=None),
    vehicle_seal_file: UploadFile = File(default=None),
    vehicle_image_file: UploadFile = File(default=None),
):
    grn_number = await _next_grn_number(db)
    pfx = grn_number

    grn = PartsGRN(
        grn_number=grn_number,
        po_number=_f(po_number),
        po_date=_parse_date(po_date),
        po_file=await _save_upload(po_file, f"{pfx}_po"),
        invoice_number=_f(invoice_number),
        invoice_date=_parse_date(invoice_date),
        invoice_file=await _save_upload(invoice_file, f"{pfx}_inv"),
        eway_bill_number=_f(eway_bill_number),
        eway_bill_date=_parse_date(eway_bill_date),
        eway_bill_file=await _save_upload(eway_bill_file, f"{pfx}_eway"),
        vehicle_number=_f(vehicle_number),
        vehicle_seal_file=await _save_upload(vehicle_seal_file, f"{pfx}_seal"),
        vehicle_image_file=await _save_upload(vehicle_image_file, f"{pfx}_veh"),
        date_received=_parse_date(date_received),
        vendor_name=_f(vendor_name),
        invoice_value=_d(invoice_value),
        sgst=_d(sgst),
        cgst=_d(cgst),
        igst=_d(igst),
        tax_amount=_d(tax_amount),
        total_po_qty=_i(total_po_qty),
        total_invoice_qty=_i(total_invoice_qty),
        total_physical_qty=_i(total_physical_qty),
        total_amount_invoice=_d(total_amount_invoice),
        created_by=current_user.username,
    )
    db.add(grn)
    await db.flush()

    try:
        items = json.loads(line_items_json or "[]")
    except json.JSONDecodeError:
        items = []

    for item in items:
        db.add(PartsGRNLineItem(
            grn_id=grn.id,
            part_id=item.get("part_id") or _new_part_id(),
            lot_number=_f(item.get("lot_number")),
            po_number=_f(item.get("po_number")) or grn.po_number,
            grn_number=grn_number,
            vendor_name=_f(item.get("vendor_name")) or grn.vendor_name,
            invoice_number=_f(item.get("invoice_number")) or grn.invoice_number,
            product_description=_f(item.get("product_description")),
            item_name=_f(item.get("item_name")),
            part_brand=_f(item.get("part_brand")),
            part_model=_f(item.get("part_model")),
            part_name=_f(item.get("part_name")),
            invoice_qty=_i(item.get("invoice_qty")),
            physical_qty=_i(item.get("physical_qty")),
            price=_d(item.get("price")),
            main_category=_f(item.get("main_category")),
            category=_f(item.get("category")),
            vehicle_number=_f(item.get("vehicle_number")) or grn.vehicle_number,
            invoice_ref=_f(item.get("invoice_ref")),
            remarks=_f(item.get("remarks")),
            is_harvest=False,
        ))

    await db.commit()
    await audit(db, action="PARTS_GRN_CREATE", user=current_user,
                table_name="parts_grn", record_id=str(grn.id))
    return RedirectResponse(f"/parts-grn/{grn.id}", status_code=303)


@router.get("/{grn_id}", response_class=HTMLResponse)
async def grn_detail(grn_id: str, request: Request, db: AsyncSession = Depends(get_db),
                     current_user: User = Depends(allowed)):
    try:
        import uuid as _uuid
        uid = _uuid.UUID(grn_id)
    except ValueError:
        raise HTTPException(404, "GRN not found")
    result = await db.execute(select(PartsGRN).where(PartsGRN.id == uid))
    grn = result.scalar_one_or_none()
    if not grn:
        raise HTTPException(404, "GRN not found")
    items_res = await db.execute(
        select(PartsGRNLineItem).where(PartsGRNLineItem.grn_id == grn.id)
        .order_by(PartsGRNLineItem.created_at)
    )
    line_items = items_res.scalars().all()
    return templates.TemplateResponse("spare_parts/parts_grn_form.html", {
        "request": request, "current_user": current_user,
        "grn": grn, "grn_number": grn.grn_number, "line_items": line_items,
        "main_categories": MAIN_CATEGORIES, "categories": CATEGORIES,
    })


@router.post("/harvest", response_class=JSONResponse)
async def harvest_part(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    lot_number: str = Form(default=""),
    product_description: str = Form(default=""),
    part_name: str = Form(default=""),
    part_brand: str = Form(default=""),
    part_model: str = Form(default=""),
    physical_qty: str = Form(default="1"),
    price: str = Form(default=""),
    main_category: str = Form(default=""),
    category: str = Form(default=""),
    vehicle_number: str = Form(default=""),
    invoice_ref: str = Form(default=""),
    remarks: str = Form(default=""),
):
    grn_number = await _next_grn_number(db)
    grn = PartsGRN(
        grn_number=grn_number,
        po_number="Harvest",
        vendor_name="Internal",
        invoice_number="Internal",
        created_by=current_user.username,
    )
    db.add(grn)
    await db.flush()

    part_id = _new_part_id()
    qty = _i(physical_qty) or 1
    db.add(PartsGRNLineItem(
        grn_id=grn.id,
        part_id=part_id,
        grn_number="Not Available",
        lot_number=_f(lot_number),
        po_number="Harvest",
        vendor_name="Internal",
        invoice_number="Internal",
        product_description=_f(product_description),
        part_name=_f(part_name),
        part_brand=_f(part_brand),
        part_model=_f(part_model),
        physical_qty=qty,
        invoice_qty=qty,
        price=_d(price),
        main_category=_f(main_category),
        category=_f(category),
        vehicle_number=_f(vehicle_number),
        invoice_ref=_f(invoice_ref),
        remarks=_f(remarks),
        is_harvest=True,
    ))
    # Mirror into Part Master so harvest parts appear in Parts Dashboard
    sp_name = _f(part_name) or _f(product_description) or "Harvest Part"
    sp_cat = _f(category) if _f(category) else "Other"
    sp_price = _d(price)
    db.add(SparePart(
        part_code=part_id,
        name=sp_name,
        category=sp_cat,
        unit_price=float(sp_price) if sp_price is not None else 0.0,
        qty_in_stock=qty,
        min_stock_alert=5,
        supplier="Internal",
        notes=_f(product_description),
        source="harvest",
    ))
    await db.commit()
    await audit(db, action="HARVEST_PART_ADD", user=current_user,
                table_name="parts_grn_line_items", record_id=part_id)
    return JSONResponse({"ok": True, "part_id": part_id, "grn_number": grn_number})
