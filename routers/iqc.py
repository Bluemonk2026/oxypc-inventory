from templates_config import templates
import csv
import io
from datetime import datetime as _dtnow
from fastapi import APIRouter, Depends, Form, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceStage, StageMovement
from models.lot import Lot, LotLineItem
from models.iqc_inspection import IQCInspection
from auth.dependencies import get_current_user, require_roles, verify_csrf, require_module_perm
from services.audit_engine import audit

router = APIRouter(prefix="/iqc", tags=["iqc"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.inventory_manager, UserRole.iqc_inspector)


def _find_usb_iqc_file():
    """Scan removable drives for the OxyQC 'latest' inspection file written by the
    USB app (<USB>\\oxyqc_offline\\latest_iqc.json). Returns Path or None."""
    import platform
    from pathlib import Path
    candidates_rel = ["oxyqc_offline/latest_iqc.json", "latest_iqc.json"]
    roots = []
    if platform.system() == "Windows":
        try:
            import ctypes, string
            DRIVE_REMOVABLE = 2
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    root = f"{letter}:\\"
                    if ctypes.windll.kernel32.GetDriveTypeW(root) == DRIVE_REMOVABLE:
                        roots.append(Path(root))
                bitmask >>= 1
        except Exception:
            pass
    else:
        for base in ("/media", "/mnt", "/run/media"):
            p = Path(base)
            if p.exists():
                roots.extend(p.glob("*"))
    best = None
    for r in roots:
        for rel in candidates_rel:
            f = r / rel
            try:
                if f.exists() and (best is None or f.stat().st_mtime > best.stat().st_mtime):
                    best = f
            except Exception:
                pass
    return best


@router.get("/usb-import")
async def usb_import(current_user: User = Depends(allowed)):
    """Auto-pick the latest IQC data file from a connected OxyQC USB drive and
    return the saved payload (used by the IQC form to prefill all fields)."""
    import json as _json
    f = _find_usb_iqc_file()
    if not f:
        raise HTTPException(404, "No OxyQC USB data file found. Plug in the OxyQC USB drive.")
    try:
        data = _json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(422, f"Could not read USB data file: {e}")
    data = {k: v for k, v in data.items() if not str(k).startswith("_")}
    return {"source": str(f), "data": data}


@router.get("", response_class=HTMLResponse)
async def iqc_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    base_q = (
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.current_stage == DeviceStage.iqc, Device.is_active.is_(True), Device.is_trashed == False)
    )
    total_result = await db.execute(select(func.count()).select_from(
        select(Device.id).where(Device.current_stage == DeviceStage.iqc, Device.is_active.is_(True), Device.is_trashed == False).subquery()
    ))
    total = total_result.scalar() or 0
    total_pages = max(1, (total + page_size - 1) // page_size)

    result = await db.execute(
        base_q.order_by(Device.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    devices = result.all()
    lots_result = await db.execute(select(Lot).order_by(Lot.lot_number))
    lots = lots_result.scalars().all()
    return templates.TemplateResponse("iqc/list.html", {
        "request": request, "devices": devices, "lots": lots, "current_user": current_user,
        "page": page, "page_size": page_size, "total": total, "total_pages": total_pages,
    })


@router.get("/export-csv")
async def iqc_export_csv(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    """Export all IQC-stage devices as CSV."""
    result = await db.execute(
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.current_stage == DeviceStage.iqc, Device.is_active.is_(True))
        .order_by(Device.created_at.desc())
    )
    devices = result.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "barcode", "brand", "model", "lot_number", "grade",
        "ram_gb", "storage_gb", "storage_type", "battery_health_pct",
        "cpu", "serial_no", "floor", "added_date",
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
            device.battery_health_pct if device.battery_health_pct is not None else "",
            device.cpu or "",
            device.serial_no or "",
            device.floor or "",
            device.created_at.strftime("%Y-%m-%d") if device.created_at else "",
        ])
    filename = f"iqc-devices-{_dtnow.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/new", response_class=HTMLResponse)
async def iqc_new_form(request: Request, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(allowed),
                       lot_id: str = Query(default=""), grn_number: str = Query(default="")):
    lots_result = await db.execute(select(Lot).order_by(Lot.lot_number))
    lots = lots_result.scalars().all()
    return templates.TemplateResponse("iqc/form.html", {
        "request": request, "lots": lots, "current_user": current_user, "error": None,
        "prefill_lot_id": lot_id, "prefill_grn": grn_number,
    })


@router.post("/new")
async def iqc_create(
    request: Request,
    barcode: str = Form(...),
    lot_id: str = Form(...),
    sub_category: str = Form(""),
    device_type: str = Form(""),
    brand: str = Form(""),
    model: str = Form(""),
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
    bios_password: str = Form(""),
    color: str = Form(""),
    grade: str = Form(""),
    floor: str = Form(""),
    warehouse: str = Form(""),
    notes: str = Form(""),
    lot_line_item_id: str = Form(""),
    qty: str = Form(""),
    device_price_input: str = Form(""),  # manual override field
    # ── Functional status ────────────────────────────────────────────────────
    power_on: str = Form(""),
    status: str = Form(""),
    all_ok: str = Form(""),
    r2v3_grade_category: str = Form(""),
    # ── Screen condition ─────────────────────────────────────────────────────
    screen_dot: str = Form(""),
    screen_line: str = Form(""),
    screen_functional: str = Form(""),
    screen_discoloration: str = Form(""),
    screen_patch: str = Form(""),
    screen_broken: str = Form(""),
    screen_flickering: str = Form(""),
    screen_scratch: str = Form(""),
    screen_loose: str = Form(""),
    screen_missing: str = Form(""),
    screen_hinge_broken: str = Form(""),
    screen_colour_spread: str = Form(""),
    screen_keyboard_mark: str = Form(""),
    screen_hard_press: str = Form(""),
    # ── Panel A ──────────────────────────────────────────────────────────────
    panel_a_scratch: str = Form(""),
    panel_a_broken: str = Form(""),
    panel_a_missing: str = Form(""),
    panel_a_dent: str = Form(""),
    panel_a_colour_fade: str = Form(""),
    # ── Panel B ──────────────────────────────────────────────────────────────
    panel_b_scratch: str = Form(""),
    panel_b_colour_fade: str = Form(""),
    panel_b_rubber_cut: str = Form(""),
    panel_b_broken: str = Form(""),
    panel_b_missing: str = Form(""),
    # ── Panel C ──────────────────────────────────────────────────────────────
    panel_c_scratch: str = Form(""),
    panel_c_broken: str = Form(""),
    panel_c_missing: str = Form(""),
    panel_c_dent: str = Form(""),
    panel_c_colour_fade: str = Form(""),
    # ── Panel D ──────────────────────────────────────────────────────────────
    panel_d_dent: str = Form(""),
    panel_d_colour_fade: str = Form(""),
    panel_d_scratch: str = Form(""),
    panel_d_broken: str = Form(""),
    panel_d_missing: str = Form(""),
    # ── Keyboard ─────────────────────────────────────────────────────────────
    keyboard_working: str = Form(""),
    keyboard_colour_fade: str = Form(""),
    keyboard_key_missing: str = Form(""),
    keyboard_hard_press: str = Form(""),
    # ── Speaker ──────────────────────────────────────────────────────────────
    speaker_status: str = Form(""),
    # ── Touchpad ─────────────────────────────────────────────────────────────
    touchpad_working: str = Form(""),
    touchpad_click_working: str = Form(""),
    touchpad_scratch: str = Form(""),
    touchpad_colour_fade: str = Form(""),
    touchpad_missing: str = Form(""),
    # ── Ports ────────────────────────────────────────────────────────────────
    port_hdmi: str = Form(""),
    port_usb_working: str = Form(""),
    port_audio_jack: str = Form(""),
    # ── Other components ─────────────────────────────────────────────────────
    wifi_status: str = Form(""),
    webcam_status: str = Form(""),
    hdd_connector: str = Form(""),
    hdd_casing: str = Form(""),
    battery_present: str = Form(""),
    battery_cable: str = Form(""),
    dvd_drive: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    _perm: User = Depends(require_module_perm("iqc", "add")),
):
    existing = await db.execute(select(Device).where(Device.barcode == barcode))
    if existing.scalar_one_or_none():
        lots_result = await db.execute(select(Lot).order_by(Lot.lot_number))
        lots = lots_result.scalars().all()
        return templates.TemplateResponse("iqc/form.html", {
            "request": request, "lots": lots, "current_user": current_user,
            "error": f"Barcode {barcode} already exists"
        })

    # ── Validate UUID inputs ─────────────────────────────────────────────────
    # A non-UUID lot_id / lot_line_item_id (e.g. from a stale barcode autofill or
    # an unselected dropdown) would otherwise hit Postgres' "invalid input syntax
    # for type uuid" and get masked as a misleading 404. Fail cleanly instead.
    import uuid as _uuid

    def _is_uuid(v):
        try:
            _uuid.UUID(str(v))
            return True
        except (ValueError, AttributeError, TypeError):
            return False

    if not _is_uuid(lot_id):
        lots_result = await db.execute(select(Lot).order_by(Lot.lot_number))
        lots = lots_result.scalars().all()
        return templates.TemplateResponse("iqc/form.html", {
            "request": request, "lots": lots, "current_user": current_user,
            "error": "Please select a valid Lot from the dropdown before adding to IQC.",
        })
    # Ignore a malformed line-item id rather than crashing the insert
    if lot_line_item_id and not _is_uuid(lot_line_item_id):
        lot_line_item_id = ""

    device = Device(
        barcode=barcode, lot_id=lot_id,
        sub_category=sub_category or None,
        brand=brand or None, model=model or None, device_type=device_type or None,
        serial_no=serial_no or None,
        grn_number=grn_number or None,
        cpu=cpu or None, generation=generation or None,
        ram_gb=int(ram_gb) if ram_gb else None,
        storage_gb=int(storage_gb) if storage_gb else None,
        storage_type=storage_type or None,
        hdd_capacity_gb=int(hdd_capacity_gb) if hdd_capacity_gb else None,
        screen_size=screen_size or None,
        battery_health_pct=int(battery_health_pct) if battery_health_pct else None,
        bios_password=(bios_password == "yes"),
        color=color or None,
        grade=grade or None, current_stage=DeviceStage.iqc,
        floor=floor or None, warehouse=warehouse or None, notes=notes or None,
        lot_line_item_id=lot_line_item_id or None,
        qty=int(qty) if qty else 1,
    )

    # Auto-set device_price from LotLineItem unit_price (or lot average as fallback)
    if lot_line_item_id:
        li_result = await db.execute(
            select(LotLineItem).where(LotLineItem.id == lot_line_item_id)
        )
        line_item = li_result.scalar_one_or_none()
        if line_item and line_item.unit_price:
            device.device_price = float(line_item.unit_price)
    if not device.device_price:
        lot_result = await db.execute(select(Lot).where(Lot.id == lot_id))
        lot_obj = lot_result.scalar_one_or_none()
        if lot_obj and lot_obj.buying_price and lot_obj.qty:
            device.device_price = float(lot_obj.buying_price / lot_obj.qty)

    # Manual price override — takes priority over auto-calculated value
    if device_price_input:
        try:
            device.device_price = float(device_price_input)
        except ValueError:
            pass  # silently ignore non-numeric input

    db.add(device)
    await db.flush()

    # Save physical inspection data
    def _v(s): return s or None
    inspection = IQCInspection(
        device_id=device.id,
        inspector_name=current_user.full_name,
        power_on=_v(power_on), status=_v(status), all_ok=_v(all_ok),
        bios_password=_v(bios_password) if bios_password not in ("", "yes", "no") else ("Yes" if bios_password == "yes" else None),
        r2v3_grade_category=_v(r2v3_grade_category),
        screen_dot=_v(screen_dot), screen_line=_v(screen_line),
        screen_functional=_v(screen_functional), screen_discoloration=_v(screen_discoloration),
        screen_patch=_v(screen_patch), screen_broken=_v(screen_broken),
        screen_flickering=_v(screen_flickering), screen_scratch=_v(screen_scratch),
        screen_loose=_v(screen_loose), screen_missing=_v(screen_missing),
        screen_hinge_broken=_v(screen_hinge_broken), screen_colour_spread=_v(screen_colour_spread),
        screen_keyboard_mark=_v(screen_keyboard_mark), screen_hard_press=_v(screen_hard_press),
        panel_a_scratch=_v(panel_a_scratch), panel_a_broken=_v(panel_a_broken),
        panel_a_missing=_v(panel_a_missing), panel_a_dent=_v(panel_a_dent),
        panel_a_colour_fade=_v(panel_a_colour_fade),
        panel_b_scratch=_v(panel_b_scratch), panel_b_colour_fade=_v(panel_b_colour_fade),
        panel_b_rubber_cut=_v(panel_b_rubber_cut), panel_b_broken=_v(panel_b_broken),
        panel_b_missing=_v(panel_b_missing),
        panel_c_scratch=_v(panel_c_scratch), panel_c_broken=_v(panel_c_broken),
        panel_c_missing=_v(panel_c_missing), panel_c_dent=_v(panel_c_dent),
        panel_c_colour_fade=_v(panel_c_colour_fade),
        panel_d_dent=_v(panel_d_dent), panel_d_colour_fade=_v(panel_d_colour_fade),
        panel_d_scratch=_v(panel_d_scratch), panel_d_broken=_v(panel_d_broken),
        panel_d_missing=_v(panel_d_missing),
        keyboard_working=_v(keyboard_working), keyboard_colour_fade=_v(keyboard_colour_fade),
        keyboard_key_missing=_v(keyboard_key_missing), keyboard_hard_press=_v(keyboard_hard_press),
        speaker_status=_v(speaker_status),
        touchpad_working=_v(touchpad_working), touchpad_click_working=_v(touchpad_click_working),
        touchpad_scratch=_v(touchpad_scratch), touchpad_colour_fade=_v(touchpad_colour_fade),
        touchpad_missing=_v(touchpad_missing),
        port_hdmi=_v(port_hdmi), port_usb_working=_v(port_usb_working),
        port_audio_jack=_v(port_audio_jack),
        wifi_status=_v(wifi_status), webcam_status=_v(webcam_status),
        hdd_connector=_v(hdd_connector), hdd_casing=_v(hdd_casing),
        battery_present=_v(battery_present), battery_cable=_v(battery_cable),
        dvd_drive=_v(dvd_drive),
    )
    db.add(inspection)

    movement = StageMovement(
        device_id=device.id, from_stage=None, to_stage=DeviceStage.iqc,
        moved_by=current_user.username, notes="IQC Entry"
    )
    db.add(movement)

    await audit(db, action="DEVICE_IQC_REGISTERED", user=current_user,
                table_name="devices", record_id=str(device.id),
                new_value={"barcode": barcode, "lot_id": lot_id, "brand": brand,
                           "model": model, "grade": grade, "status": status},
                request=request)

    await db.commit()
    return RedirectResponse(url="/iqc?success=Device+added+to+IQC", status_code=302)


@router.get("/lookup", response_class=JSONResponse)
async def lookup_device(barcode: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.barcode == barcode, Device.is_active.is_(True))
    )
    row = result.first()
    if not row:
        return JSONResponse({"found": False})
    device, lot_number = row
    return JSONResponse({
        "found": True,
        "barcode": device.barcode,
        "brand": device.brand,
        "model": device.model,
        "device_type": device.device_type,
        "sub_category": device.sub_category,
        "serial_no": device.serial_no,
        "grn_number": device.grn_number,
        "cpu": device.cpu,
        "generation": device.generation,
        "ram_gb": device.ram_gb,
        "storage_gb": device.storage_gb,
        "storage_type": device.storage_type,
        "hdd_capacity_gb": device.hdd_capacity_gb,
        "screen_size": device.screen_size,
        "battery_health_pct": device.battery_health_pct,
        "bios_password": device.bios_password,
        "color": device.color,
        "grade": device.grade,
        "floor": device.floor,
        "warehouse": device.warehouse,
        "current_stage": device.current_stage,
        "lot_number": lot_number,
        "lot_id": str(device.lot_id),
    })
