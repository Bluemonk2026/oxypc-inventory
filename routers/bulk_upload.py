import csv
import io
from datetime import datetime
from utils.timezone import app_now
from templates_config import templates
from fastapi import APIRouter, Depends, File, UploadFile, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceStage, StageMovement
from models.lot import Lot
from models.spare_parts import SparePart
from models.telecalling import TelecallingRecord
from auth.dependencies import get_current_user, require_roles, verify_csrf

router = APIRouter(prefix="/bulk-upload", tags=["bulk_upload"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.inventory_manager)

# CSV template headers
TEMPLATES = {
    "lots": {
        "filename": "lots_template.csv",
        "headers": [
            # Required
            "lot_number", "supplier_name", "buying_price", "qty", "purchase_date",
            # GRN
            "grn_system_number", "grn_number_new", "grn_date",
            # Invoice / GST
            "invoice_no", "invoice_date", "invoice_value",
            "taxable_amount", "sgst", "cgst", "igst",
            # PO / Logistics
            "po_number", "vendor_name", "vehicle_number", "e_way_bill",
            # Misc
            "notes",
        ],
        "example": [
            "LOT-001", "ABC Traders", "50000", "10", "2024-01-15",
            "GRN-178", "178", "2024-01-14",
            "INV-2024-001", "2024-01-14", "59000",
            "50000", "4500", "4500", "0",
            "PO-2024-001", "ABC Suppliers Pvt Ltd", "MH04AB1234", "EWB-123456",
            "First lot - HP laptops",
        ],
    },
    "devices": {
        "filename": "devices_template.csv",
        "headers": ["barcode", "lot_number", "sub_category", "brand", "model", "device_type",
                    "serial_no", "grn_number", "cpu", "generation",
                    "ram_gb", "storage_gb", "storage_type", "hdd_capacity_gb",
                    "screen_size", "battery_health_pct", "bios_password",
                    "color", "grade", "floor", "warehouse", "device_price", "notes"],
        "example": ["OXY-00001", "LOT-001", "Laptop", "HP", "EliteBook 840 G6", "Laptop",
                    "SN123456", "GRN-001", "Intel Core i5-8250U", "8th Gen",
                    "8", "256", "SSD", "",
                    "14.0 FHD", "78", "no",
                    "Silver", "B", "Floor 1", "TRC 1st Floor", "5500", "Minor scratch on lid"],
    },
    "spare_parts": {
        "filename": "spare_parts_template.csv",
        "headers": ["part_code", "name", "category", "unit_price", "min_stock_alert", "supplier", "notes"],
        "example": ["PART-0001", "DDR4 8GB RAM", "RAM", "500", "5", "ABC Electronics", "Samsung OEM"],
    },
    "leads": {
        "filename": "leads_template.csv",
        "headers": [
            "customer_name", "phone", "email", "customer_type",
            "city", "state",
            "category", "brand", "model", "generation",
            "processor", "ram", "hard_disk",
            "product_type", "grade", "qty_required", "budget",
            "lot_reference", "call_outcome", "next_followup", "notes",
        ],
        "example": [
            "Rajesh Kumar", "9876543210", "rajesh@example.com", "corporate",
            "Mumbai", "Maharashtra",
            "Laptop", "Dell", "Latitude 5490", "8th Gen",
            "Intel Core i5-8250U", "16GB", "512GB SSD",
            "Refurbished", "A", "5", "35000",
            "LOT-001", "interested", "2026-04-01", "Needs delivery by month end",
        ],
    },
}


@router.get("", response_class=HTMLResponse)
async def bulk_upload_page(
    request: Request,
    type: str = None,
    current_user: User = Depends(allowed)
):
    # ?type=lots → pre-select lots tab; ?type=devices → pre-select devices tab
    return templates.TemplateResponse("bulk_upload/index.html", {
        "request": request, "current_user": current_user,
        "preselect_type": type or "devices",
    })


@router.get("/template/{upload_type}")
async def download_template(upload_type: str, current_user: User = Depends(get_current_user)):
    if upload_type not in TEMPLATES:
        raise HTTPException(404, "Unknown template type")
    tmpl = TEMPLATES[upload_type]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(tmpl["headers"])
    writer.writerow(tmpl["example"])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={tmpl['filename']}"},
    )


@router.post("/lots")
async def upload_lots(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    content = await file.read()
    text = content.decode("utf-8-sig")  # handle BOM
    reader = csv.DictReader(io.StringIO(text))
    inserted, errors = 0, []

    def _parse_date(s):
        s = (s or "").strip()
        if not s:
            return None
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None

    def _parse_decimal(s, default=None):
        s = (s or "").strip()
        if not s:
            return default
        try:
            return float(s.replace(",", ""))
        except ValueError:
            return default

    def _parse_int(s, default=None):
        s = (s or "").strip()
        if not s:
            return default
        try:
            return int(s)
        except ValueError:
            return default

    for i, row in enumerate(reader, start=2):
        try:
            lot_number = row.get("lot_number", "").strip()
            if not lot_number:
                errors.append(f"Row {i}: lot_number is required")
                continue
            existing = await db.execute(select(Lot).where(Lot.lot_number == lot_number))
            if existing.scalar_one_or_none():
                errors.append(f"Row {i}: lot_number '{lot_number}' already exists")
                continue

            buying_price = _parse_decimal(row.get("buying_price"), 0)
            qty          = _parse_int(row.get("qty"), 1)
            purchase_date = _parse_date(row.get("purchase_date")) or app_now()

            lot = Lot(
                lot_number    = lot_number,
                supplier_name = row.get("supplier_name", "").strip() or "Unknown",
                buying_price  = buying_price,
                qty           = qty,
                purchase_date = purchase_date,
                # GRN
                grn_system_number = row.get("grn_system_number", "").strip() or None,
                grn_number_new    = _parse_int(row.get("grn_number_new")),
                grn_date          = _parse_date(row.get("grn_date")),
                # Invoice / GST
                invoice_no     = row.get("invoice_no", "").strip() or None,
                invoice_date   = _parse_date(row.get("invoice_date")),
                invoice_value  = _parse_decimal(row.get("invoice_value")),
                taxable_amount = _parse_decimal(row.get("taxable_amount")),
                sgst           = _parse_decimal(row.get("sgst")),
                cgst           = _parse_decimal(row.get("cgst")),
                igst           = _parse_decimal(row.get("igst")),
                # PO / Logistics
                po_number      = row.get("po_number", "").strip() or None,
                vendor_name    = row.get("vendor_name", "").strip() or None,
                vehicle_number = row.get("vehicle_number", "").strip() or None,
                e_way_bill     = row.get("e_way_bill", "").strip() or None,
                # Misc
                notes          = row.get("notes", "").strip() or None,
                created_by     = current_user.username,
            )
            db.add(lot)
            inserted += 1
        except Exception as e:
            errors.append(f"Row {i}: {str(e)}")

    await db.commit()
    return templates.TemplateResponse("bulk_upload/result.html", {
        "request": request, "current_user": current_user,
        "upload_type": "Lots", "inserted": inserted, "errors": errors,
        "back_url": "/lots",
    })


@router.post("/devices")
async def upload_devices(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    inserted, errors = 0, []

    # Build lot_number → lot_id map
    lots_result = await db.execute(select(Lot))
    lot_map = {lot.lot_number: lot.id for lot in lots_result.scalars().all()}

    for i, row in enumerate(reader, start=2):
        try:
            barcode = row.get("barcode", "").strip()
            if not barcode:
                errors.append(f"Row {i}: barcode is required")
                continue
            existing = await db.execute(select(Device).where(Device.barcode == barcode))
            if existing.scalar_one_or_none():
                errors.append(f"Row {i}: barcode '{barcode}' already exists")
                continue
            lot_number = row.get("lot_number", "").strip()
            lot_id = lot_map.get(lot_number)
            if not lot_id:
                errors.append(f"Row {i}: lot_number '{lot_number}' not found")
                continue
            ram_gb = row.get("ram_gb", "").strip()
            storage_gb = row.get("storage_gb", "").strip()
            hdd_gb = row.get("hdd_capacity_gb", "").strip()
            battery = row.get("battery_health_pct", "").strip()
            bios_pwd = row.get("bios_password", "no").strip().lower() == "yes"
            dev_price_raw = row.get("device_price", "").strip()
            dev_price = float(dev_price_raw) if dev_price_raw else None
            device = Device(
                barcode=barcode, lot_id=lot_id,
                sub_category=row.get("sub_category", "").strip() or None,
                brand=row.get("brand", "").strip() or None,
                model=row.get("model", "").strip() or None,
                device_type=row.get("device_type", "").strip() or None,
                serial_no=row.get("serial_no", "").strip() or None,
                grn_number=row.get("grn_number", "").strip() or None,
                cpu=row.get("cpu", "").strip() or None,
                generation=row.get("generation", "").strip() or None,
                ram_gb=int(ram_gb) if ram_gb else None,
                storage_gb=int(storage_gb) if storage_gb else None,
                storage_type=row.get("storage_type", "").strip() or None,
                hdd_capacity_gb=int(hdd_gb) if hdd_gb else None,
                screen_size=row.get("screen_size", "").strip() or None,
                battery_health_pct=int(battery) if battery else None,
                bios_password=bios_pwd,
                color=row.get("color", "").strip() or None,
                grade=row.get("grade", "").strip() or None,
                floor=row.get("floor", "").strip() or None,
                warehouse=row.get("warehouse", "").strip() or None,
                device_price=dev_price,
                notes=row.get("notes", "").strip() or None,
                current_stage=DeviceStage.iqc,
            )
            db.add(device)
            await db.flush()
            movement = StageMovement(
                device_id=device.id, from_stage=None, to_stage=DeviceStage.iqc,
                moved_by=current_user.username, notes="Bulk Upload - IQC Entry"
            )
            db.add(movement)
            inserted += 1
        except Exception as e:
            errors.append(f"Row {i}: {str(e)}")

    await db.commit()
    return templates.TemplateResponse("bulk_upload/result.html", {
        "request": request, "current_user": current_user,
        "upload_type": "Devices", "inserted": inserted, "errors": errors,
        "back_url": "/iqc",
    })


@router.post("/spare-parts")
async def upload_spare_parts(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    inserted, errors = 0, []

    for i, row in enumerate(reader, start=2):
        try:
            part_code = row.get("part_code", "").strip()
            name = row.get("name", "").strip()
            if not part_code or not name:
                errors.append(f"Row {i}: part_code and name are required")
                continue
            existing = await db.execute(select(SparePart).where(SparePart.part_code == part_code))
            if existing.scalar_one_or_none():
                errors.append(f"Row {i}: part_code '{part_code}' already exists")
                continue
            unit_price = row.get("unit_price", "0").strip()
            min_alert = row.get("min_stock_alert", "5").strip()
            part = SparePart(
                part_code=part_code, name=name,
                category=row.get("category", "Other").strip(),
                unit_price=float(unit_price) if unit_price else 0,
                min_stock_alert=int(min_alert) if min_alert else 5,
                supplier=row.get("supplier", "").strip() or None,
                notes=row.get("notes", "").strip() or None,
            )
            db.add(part)
            inserted += 1
        except Exception as e:
            errors.append(f"Row {i}: {str(e)}")

    await db.commit()
    return templates.TemplateResponse("bulk_upload/result.html", {
        "request": request, "current_user": current_user,
        "upload_type": "Spare Parts", "inserted": inserted, "errors": errors,
        "back_url": "/spare-parts",
    })


@router.post("/leads")
async def upload_leads(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Bulk upload telecalling leads / lead-gen data from CSV."""
    content = await file.read()
    text    = content.decode("utf-8-sig")
    reader  = csv.DictReader(io.StringIO(text))
    inserted, errors = 0, []

    VALID_OUTCOMES = {"interested", "not_interested", "callback", "order_placed", "no_answer", "do_not_call", ""}
    VALID_CUST_TYPES = {"end_customer", "corporate", "individual", "dealer", "reseller", ""}

    for i, row in enumerate(reader, start=2):
        try:
            phone = row.get("phone", "").strip().replace(" ", "").replace("-", "")
            if not phone:
                errors.append(f"Row {i}: phone is required")
                continue

            # Parse optional numeric fields
            qty_raw    = row.get("qty_required", "").strip()
            budget_raw = row.get("budget", "").strip()
            qty    = int(qty_raw)    if qty_raw    else None
            budget = float(budget_raw) if budget_raw else None

            # Parse next_followup date
            followup_str = row.get("next_followup", "").strip()
            next_followup = None
            if followup_str:
                try:
                    next_followup = datetime.strptime(followup_str, "%Y-%m-%d")
                except ValueError:
                    errors.append(f"Row {i}: next_followup must be YYYY-MM-DD, got '{followup_str}'")
                    continue

            outcome    = row.get("call_outcome", "").strip().lower()
            cust_type  = row.get("customer_type", "").strip().lower()

            record = TelecallingRecord(
                customer_name  = row.get("customer_name", "").strip() or None,
                phone          = phone,
                email          = row.get("email", "").strip() or None,
                customer_type  = cust_type or None,
                city           = row.get("city", "").strip() or None,
                state          = row.get("state", "").strip() or None,
                category       = row.get("category", "").strip() or None,
                brand          = row.get("brand", "").strip() or None,
                model          = row.get("model", "").strip() or None,
                generation     = row.get("generation", "").strip() or None,
                processor      = row.get("processor", "").strip() or None,
                ram            = row.get("ram", "").strip() or None,
                hard_disk      = row.get("hard_disk", "").strip() or None,
                product_type   = row.get("product_type", "").strip() or None,
                grade          = row.get("grade", "").strip() or None,
                lot_reference  = row.get("lot_reference", "").strip() or None,
                quantity_required = qty,
                budget         = budget,
                call_outcome   = outcome or None,
                next_followup  = next_followup,
                notes          = row.get("notes", "").strip() or None,
                called_by      = current_user.username,
                product_interest = row.get("category", "").strip() or None,
            )
            db.add(record)
            inserted += 1
        except Exception as e:
            errors.append(f"Row {i}: {str(e)}")

    await db.commit()
    return templates.TemplateResponse("bulk_upload/result.html", {
        "request": request, "current_user": current_user,
        "upload_type": "Telecalling Leads", "inserted": inserted, "errors": errors,
        "back_url": "/telecalling",
    })
