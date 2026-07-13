import csv
import io
import re
import uuid
from datetime import datetime
from utils.timezone import app_now
from templates_config import templates
from fastapi import APIRouter, Depends, File, Form, UploadFile, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceStage, StageMovement, STAGE_LABELS
from models.iqc_inspection import IQCInspection
from models.lot import Lot
from models.spare_parts import SparePart
from models.telecalling import TelecallingRecord
from auth.dependencies import get_current_user, require_roles, verify_csrf
from services.audit_engine import audit
from services.control_engine import validate_transition

router = APIRouter(prefix="/bulk-upload", tags=["bulk_upload"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.inventory_manager)

# ── Devices template column order — mirrors every field on the IQC entry
# page (templates/iqc/form.html) so a bulk upload can fully replace manual
# entry. First 9 columns per the fixed lead-in spec; everything else (the
# remaining Device columns, then the full physical inspection checklist)
# follows. Shared by both the template download and the upload parser so
# the two can never drift apart. ────────────────────────────────────────────
DEVICE_CORE_FIELDS = [
    "Tag No", "serial_no", "brand", "model", "cpu", "generation", "ram_gb", "storage_gb",
    "category", "lot_number",
]
DEVICE_REST_FIELDS = [
    "device_type", "storage_type", "hdd_capacity_gb",
    "screen_size", "battery_health_pct", "bios_password", "color", "grade",
    "floor", "warehouse", "grn_number", "qty", "device_price", "notes",
]
IQC_INSPECTION_FIELDS = [
    "power_on", "all_ok", "status",
    "screen_dot", "screen_line", "screen_functional", "screen_discoloration",
    "screen_patch", "screen_broken", "screen_flickering", "screen_scratch",
    "screen_loose", "screen_missing", "screen_hinge_broken", "screen_colour_spread",
    "screen_keyboard_mark", "screen_hard_press",
    "panel_a_scratch", "panel_a_broken", "panel_a_missing", "panel_a_dent", "panel_a_colour_fade",
    "panel_b_scratch", "panel_b_colour_fade", "panel_b_rubber_cut", "panel_b_broken", "panel_b_missing",
    "panel_c_scratch", "panel_c_broken", "panel_c_missing", "panel_c_dent", "panel_c_colour_fade",
    "panel_d_dent", "panel_d_colour_fade", "panel_d_scratch", "panel_d_broken", "panel_d_missing",
    "keyboard_working", "keyboard_colour_fade", "keyboard_key_missing", "keyboard_hard_press",
    "speaker_status",
    "touchpad_working", "touchpad_click_working", "touchpad_scratch", "touchpad_colour_fade", "touchpad_missing",
    "port_hdmi", "port_usb_working", "port_audio_jack", "usb_a_ports", "usb_c_ports", "ethernet_ports",
    "wifi_status", "webcam_status", "hdd_connector", "hdd_casing", "battery_present", "battery_cable",
    "charging_port", "dvd_drive",
    "cover_ram", "cover_dvd", "cover_storage",
    "hinge_condition", "hinge_cover", "touchpad_logicboard",
    "storage_health_pct", "fan_sound_dba", "fan_working",
    "r2v3_grade_category", "remarks",
]
DEVICE_CSV_HEADERS = DEVICE_CORE_FIELDS + DEVICE_REST_FIELDS + IQC_INSPECTION_FIELDS

# Only a handful of illustrative inspection values in the sample row — the rest
# are left blank since the checklist is optional and 70+ filled columns would
# make the example row unreadable.
_IQC_EXAMPLE_MAP = {
    "power_on": "Yes", "all_ok": "Yes", "status": "Power On",
    "screen_functional": "Yes", "screen_scratch": "No",
    "keyboard_working": "Yes", "touchpad_working": "Yes",
    "port_hdmi": "Yes", "port_usb_working": "Yes", "port_audio_jack": "Yes",
    "usb_a_ports": "2", "usb_c_ports": "1", "ethernet_ports": "1",
    "wifi_status": "Working", "webcam_status": "Ok",
    "battery_present": "Yes", "fan_working": "Yes",
    "r2v3_grade_category": "C3",
}

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
        "headers": DEVICE_CSV_HEADERS,
        "example": (
            ["OXY-00001", "SN123456", "HP", "EliteBook 840 G6", "Intel Core i5-8250U",
             "8", "256", "Laptop", "LOT-001"]
            + ["Laptop", "8th Gen", "SSD", "", "14.0 FHD", "78", "no", "Silver", "B",
               "Floor 1", "TRC 1st Floor", "GRN-001", "1", "5500", "Minor scratch on lid"]
            + [_IQC_EXAMPLE_MAP.get(f, "") for f in IQC_INSPECTION_FIELDS]
        ),
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
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("utf-16")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    inserted, errors = 0, []
    # Rows held back for the duplicate-review modal instead of hard-erroring —
    # a duplicate Tag No (barcode already exists elsewhere) or a lot_number the
    # file references but which doesn't exist yet in Lot Management. Both used
    # to be silently skipped as an error row; now they're surfaced so the user
    # can resolve them in bulk (Approve Move / Add Lot) instead of fixing the
    # CSV and re-uploading one row at a time.
    tag_duplicates: list[dict] = []
    lot_duplicates: dict[str, dict] = {}   # lot_number -> row, de-duped

    # Build lot_number → lot_id map
    lots_result = await db.execute(select(Lot))
    lot_map = {lot.lot_number: lot.id for lot in lots_result.scalars().all()}

    # Existing barcodes, fetched once up front (not per row) so a large CSV
    # doesn't do a DB round-trip per row — this is what was slow enough to
    # trip a reverse-proxy timeout ("upstream error"). Also tracks barcodes
    # added earlier in this same batch (no longer flushed row-by-row) so
    # in-batch duplicates are still caught instead of failing the whole
    # commit with a unique-constraint error.
    existing_barcodes = set((await db.execute(select(Device.barcode))).scalars().all())
    # Existing devices by barcode, for the duplicate-tag review table (current
    # stage). Fetched lazily below only if a duplicate is actually found.
    existing_devices_by_barcode: dict[str, Device] = {}

    def _s(row, key):
        return (row.get(key) or "").strip() or None

    def _i(row, key):
        # Accept any value without restriction — pull the first integer out of
        # whatever was typed (e.g. "256GB" -> 256, "8 GB" -> 8) instead of
        # silently discarding the whole cell just because it wasn't a bare digit.
        v = (row.get(key) or "").strip()
        m = re.search(r"-?\d+", v)
        return int(m.group()) if m else None

    for i, row in enumerate(reader, start=2):
        try:
            barcode = _s(row, "Tag No")
            if not barcode:
                errors.append(f"Row {i}: Tag No is required")
                continue
            if barcode in existing_barcodes:
                if barcode not in existing_devices_by_barcode:
                    ed = (await db.execute(select(Device).where(Device.barcode == barcode))).scalar_one_or_none()
                    if ed:
                        existing_devices_by_barcode[barcode] = ed
                ed = existing_devices_by_barcode.get(barcode)
                tag_duplicates.append({
                    "tag_number": barcode,
                    "grade": _s(row, "grade") or "—",
                    "current_stage": ed.current_stage.value if ed else None,
                    "current_stage_label": STAGE_LABELS.get(ed.current_stage, ed.current_stage) if ed else "—",
                    "file_stage": DeviceStage.iqc.value,
                    "file_stage_label": STAGE_LABELS.get(DeviceStage.iqc, "IQC"),
                    # Full CSV row, round-tripped through the modal so "Update"/
                    # "Update All" can apply this row's values without needing
                    # the original file re-uploaded.
                    "row": {k: (v or "") for k, v in row.items()},
                })
                continue
            lot_number = _s(row, "lot_number")
            lot_id = lot_map.get(lot_number)
            if not lot_id:
                if lot_number and lot_number not in lot_duplicates:
                    lot_duplicates[lot_number] = {
                        "lot_number": lot_number,
                        "purchase_date": app_now().strftime("%Y-%m-%d"),
                        "vendor_name": "Unknown",
                    }
                errors.append(f"Row {i}: lot_number '{lot_number}' not found")
                continue
            bios_pwd_raw = (row.get("bios_password") or "").strip().lower()
            qty_raw = _i(row, "qty")
            dev_price_raw = (row.get("device_price") or "").strip()
            dev_price = float(dev_price_raw) if dev_price_raw else None
            # Generate the PK explicitly rather than relying on the column
            # default — that default only fires on flush, so device.id would
            # still be None when building the StageMovement below now that
            # rows are no longer flushed one at a time.
            dev_id = uuid.uuid4()
            device = Device(
                id=dev_id, barcode=barcode, lot_id=lot_id,
                sub_category=_s(row, "category"),
                brand=_s(row, "brand"), model=_s(row, "model"),
                device_type=_s(row, "device_type"),
                serial_no=_s(row, "serial_no"),
                grn_number=_s(row, "grn_number"),
                cpu=_s(row, "cpu"), generation=_s(row, "generation"),
                ram_gb=_i(row, "ram_gb"), storage_gb=_i(row, "storage_gb"),
                storage_type=_s(row, "storage_type"),
                hdd_capacity_gb=_i(row, "hdd_capacity_gb"),
                screen_size=_s(row, "screen_size"),
                battery_health_pct=_i(row, "battery_health_pct"),
                bios_password=(bios_pwd_raw == "yes"),
                color=_s(row, "color"), grade=_s(row, "grade"),
                floor=_s(row, "floor"), warehouse=_s(row, "warehouse"),
                qty=qty_raw or 1,
                device_price=dev_price,
                notes=_s(row, "notes"),
                current_stage=DeviceStage.iqc,
            )
            db.add(device)
            existing_barcodes.add(barcode)
            movement = StageMovement(
                device_id=device.id, from_stage=None, to_stage=DeviceStage.iqc,
                moved_by=current_user.username, notes="Bulk Upload - IQC Entry"
            )
            db.add(movement)

            # ── Physical inspection checklist (mirrors the manual IQC entry
            # form's IQCInspection creation) — entirely optional per-row. ──
            inspection = IQCInspection(
                device_id=device.id,
                inspector_name=current_user.full_name,
                bios_password=("Yes" if bios_pwd_raw == "yes" else "No" if bios_pwd_raw == "no" else None),
                **{f: _s(row, f) for f in IQC_INSPECTION_FIELDS
                   if f not in ("usb_a_ports", "usb_c_ports", "ethernet_ports",
                                 "storage_health_pct", "fan_sound_dba", "bios_password")},
                usb_a_ports=_i(row, "usb_a_ports"), usb_c_ports=_i(row, "usb_c_ports"),
                ethernet_ports=_i(row, "ethernet_ports"),
                storage_health_pct=_i(row, "storage_health_pct"),
                fan_sound_dba=_i(row, "fan_sound_dba"),
            )
            db.add(inspection)
            inserted += 1
        except Exception as e:
            errors.append(f"Row {i}: {str(e)}")

    # Single flush/commit for the whole batch — a flush per row was causing a
    # DB round-trip per device, slow enough on larger CSVs to trip a reverse
    # proxy's upstream timeout ("upstream error") before the response returned.
    await db.commit()
    return templates.TemplateResponse("bulk_upload/result.html", {
        "request": request, "current_user": current_user,
        "upload_type": "Devices", "inserted": inserted, "errors": errors,
        "back_url": "/iqc",
        "tag_duplicates": tag_duplicates,
        "lot_duplicates": list(lot_duplicates.values()),
    })


@router.post("/duplicates/approve-move")
async def approve_duplicate_move(
    request: Request,
    tag_number: str = Form(...),
    to_stage: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Approve-Move button on the duplicate-review modal's Tag Number table —
    moves a single already-existing device from its current stage to the
    stage requested by the uploaded file. Reuses the same validated-transition
    engine as every other stage-move flow in the app (services/control_engine)
    so bulk corrections can't skip stages the rest of the system assumes are
    sequential. Returns JSON (not a redirect) — the modal must stay open."""
    result = await db.execute(select(Device).where(Device.barcode == tag_number))
    device = result.scalar_one_or_none()
    if not device:
        return JSONResponse({"success": False, "error": f"Tag Number '{tag_number}' not found"}, status_code=404)

    is_admin = current_user.role.value == "admin"
    try:
        new_stage = DeviceStage(to_stage)
    except ValueError:
        return JSONResponse({"success": False, "error": f"Invalid stage '{to_stage}'"}, status_code=400)
    try:
        await validate_transition(device, new_stage, db, override_admin=is_admin)
    except HTTPException as e:
        return JSONResponse({"success": False, "error": e.detail}, status_code=e.status_code)

    prev = device.current_stage
    device.current_stage = new_stage
    device.updated_at = app_now()
    db.add(StageMovement(device_id=device.id, from_stage=prev, to_stage=new_stage,
                          moved_by=current_user.username, notes="Bulk Upload — duplicate review, Approve Move"))
    await audit(db, action="STAGE_MOVED", user=current_user,
                table_name="devices", record_id=str(device.id),
                old_value={"stage": str(prev)}, new_value={"stage": to_stage}, request=request)
    await db.commit()
    return JSONResponse({"success": True, "new_stage": new_stage.value,
                          "new_stage_label": STAGE_LABELS.get(new_stage, new_stage.value)})


def _apply_row_to_device(device: Device, row: dict) -> None:
    """Apply one CSV row's field values onto an already-existing device —
    shared by the single-row Update and bulk Update All actions on the
    duplicate-review modal. Never touches barcode/lot_number (identity)."""
    def s(key):
        return (row.get(key) or "").strip() or None

    def i(key):
        v = (row.get(key) or "").strip()
        m = re.search(r"-?\d+", v)
        return int(m.group()) if m else None

    if s("brand"): device.brand = s("brand")
    if s("model"): device.model = s("model")
    if s("device_type"): device.device_type = s("device_type")
    if s("serial_no"): device.serial_no = s("serial_no")
    if s("cpu"): device.cpu = s("cpu")
    if s("generation"): device.generation = s("generation")
    if i("ram_gb") is not None: device.ram_gb = i("ram_gb")
    if i("storage_gb") is not None: device.storage_gb = i("storage_gb")
    if s("storage_type"): device.storage_type = s("storage_type")
    if i("hdd_capacity_gb") is not None: device.hdd_capacity_gb = i("hdd_capacity_gb")
    if s("screen_size"): device.screen_size = s("screen_size")
    if i("battery_health_pct") is not None: device.battery_health_pct = i("battery_health_pct")
    if s("color"): device.color = s("color")
    if s("grade"): device.grade = s("grade")
    if s("grn_number"): device.grn_number = s("grn_number")
    device.updated_at = app_now()


@router.post("/duplicates/update")
async def update_duplicate_device(
    request: Request,
    tag_number: str = Form(...),
    row_json: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Update button on the duplicate-review modal's Tag Number table — applies
    this row's uploaded field values onto the existing device. Returns JSON so
    the modal stays open."""
    import json
    try:
        row = json.loads(row_json)
    except (ValueError, TypeError):
        return JSONResponse({"success": False, "error": "Malformed row data"}, status_code=400)
    device = (await db.execute(select(Device).where(Device.barcode == tag_number))).scalar_one_or_none()
    if not device:
        return JSONResponse({"success": False, "error": f"Tag Number '{tag_number}' not found"}, status_code=404)
    _apply_row_to_device(device, row)
    await audit(db, action="DEVICE_UPDATED", user=current_user,
                table_name="devices", record_id=str(device.id),
                new_value={"source": "bulk_upload_duplicate_update"}, request=request)
    await db.commit()
    return JSONResponse({"success": True})


@router.post("/duplicates/update-all")
async def update_all_duplicate_devices(
    request: Request,
    rows_json: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Update All button — applies every listed duplicate row's uploaded
    values to its matching existing device in one pass."""
    import json
    try:
        rows = json.loads(rows_json)
    except (ValueError, TypeError):
        return JSONResponse({"success": False, "error": "Malformed row data"}, status_code=400)
    if not isinstance(rows, list):
        return JSONResponse({"success": False, "error": "Expected a list of rows"}, status_code=400)

    barcodes = [r.get("tag_number") for r in rows if r.get("tag_number")]
    devices = {d.barcode: d for d in (await db.execute(
        select(Device).where(Device.barcode.in_(barcodes))
    )).scalars().all()}

    updated, missing = [], []
    for r in rows:
        tag = r.get("tag_number")
        device = devices.get(tag)
        if not device:
            missing.append(tag)
            continue
        _apply_row_to_device(device, r.get("row") or {})
        updated.append(tag)

    if updated:
        await audit(db, action="DEVICE_UPDATED", user=current_user,
                    table_name="devices", record_id=None,
                    new_value={"source": "bulk_upload_duplicate_update_all", "tags": updated}, request=request)
        await db.commit()
    return JSONResponse({"success": True, "updated": updated, "missing": missing})


@router.post("/duplicates/add-lot")
async def add_duplicate_lot(
    request: Request,
    lot_number: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Add Lot button on the duplicate-review modal's Lot table — registers
    the lot shell (lot_number + today's purchase date + Unknown vendor) in
    Lot Management so a later normal upload/GRN can attach devices to it.
    Returns JSON (not a redirect) — the modal must stay open."""
    lot_number = (lot_number or "").strip()
    if not lot_number:
        return JSONResponse({"success": False, "error": "Lot Number is required"}, status_code=400)
    existing = (await db.execute(select(Lot).where(Lot.lot_number == lot_number))).scalar_one_or_none()
    if existing:
        return JSONResponse({"success": False, "error": f"Lot '{lot_number}' already exists"}, status_code=409)

    lot = Lot(
        lot_number=lot_number,
        supplier_name="Unknown",
        vendor_name="Unknown",
        buying_price=0,
        qty=1,
        purchase_date=app_now(),
        created_by=current_user.username if current_user else None,
    )
    db.add(lot)
    await db.flush()
    await audit(db, action="LOT_CREATED_FROM_DUPLICATE_REVIEW", user=current_user,
                table_name="lots", record_id=str(lot.id),
                new_value={"lot_number": lot.lot_number}, request=request)
    await db.commit()
    return JSONResponse({"success": True, "lot_id": str(lot.id)})


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
