"""
Cosmetic Refurbishment Pipeline
Stages: QC Check → Cleaning → Dry Sanding → Masking → Painting → Water Sanding → Final QC → Ready to Sale
"""
from templates_config import templates
from datetime import datetime
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceStage, StageMovement
from models.lot import Lot
from models.iqc_inspection import IQCInspection
from models.repair import RepairJob
from models.part_request import PartRequest
from models.spare_parts import SparePart, SparePartConsumption
from services.parts_required import compute_required
from services.audit_engine import audit
from auth.dependencies import get_current_user, require_roles, verify_csrf, require_module_perm

router = APIRouter(prefix="/cosmetic", tags=["cosmetic"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.inventory_manager, UserRole.qc_inspector,
                         UserRole.sales_manager)

# Ordered cosmetic pipeline — each stage advances to the next
COSMETIC_PIPELINE = [
    DeviceStage.cleaning,
    DeviceStage.putty,
    DeviceStage.dry_sanding,
    DeviceStage.masking,
    DeviceStage.painting,
    DeviceStage.water_sanding,
    DeviceStage.final_qc,
]

# Nav tab bar excludes Final QC — that page is reached via "Done & Move to
# Final QC" from Cleaning or by finishing the pipeline, not a direct jump.
COSMETIC_NAV_STAGES = [s for s in COSMETIC_PIPELINE if s != DeviceStage.final_qc]

NEXT_COSMETIC = {
    DeviceStage.qc_check:    DeviceStage.cleaning,
    DeviceStage.cleaning:    DeviceStage.putty,
    DeviceStage.putty:       DeviceStage.dry_sanding,
    DeviceStage.dry_sanding: DeviceStage.masking,
    DeviceStage.masking:     DeviceStage.painting,
    DeviceStage.painting:    DeviceStage.water_sanding,
    DeviceStage.water_sanding: DeviceStage.final_qc,
    DeviceStage.final_qc:    DeviceStage.ready_to_sale,
}

STAGE_LABELS = {
    DeviceStage.cleaning:     "Cleaning",
    DeviceStage.putty:        "Putty",
    DeviceStage.dry_sanding:  "Dry Sanding",
    DeviceStage.masking:      "Masking",
    DeviceStage.painting:     "Painting",
    DeviceStage.water_sanding:"Water Sanding",
    DeviceStage.final_qc:     "Final QC",
}


async def _get_devices_at_stage(db: AsyncSession, stage: DeviceStage):
    result = await db.execute(
        select(Device, Lot.lot_number)
        .join(Lot, Device.lot_id == Lot.id)
        .where(Device.current_stage == stage)
        .order_by(Device.updated_at.desc())
    )
    return result.all()


@router.get("", response_class=HTMLResponse)
async def cosmetic_dashboard(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(allowed)):
    """Overview of all cosmetic pipeline stages."""
    stage_data = {}
    for stage in COSMETIC_PIPELINE:
        devices = await _get_devices_at_stage(db, stage)
        stage_data[stage] = {
            "label": STAGE_LABELS[stage],
            "devices": devices,
            "count": len(devices),
        }
    return templates.TemplateResponse("cosmetic/dashboard.html", {
        "request": request, "current_user": current_user,
        "stage_data": stage_data, "pipeline": COSMETIC_PIPELINE,
    })


@router.get("/{stage_name}", response_class=HTMLResponse)
async def cosmetic_stage_list(stage_name: str, request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(allowed)):
    try:
        stage = DeviceStage(stage_name)
    except ValueError:
        raise HTTPException(404)
    if stage not in COSMETIC_PIPELINE:
        raise HTTPException(404)
    devices = await _get_devices_at_stage(db, stage)
    next_stage = NEXT_COSMETIC.get(stage)

    # Final QC (#18): show IQC data + post-repair data read-only, then grade + Ready to Sale
    if stage == DeviceStage.final_qc:
        device_ids = [d.id for d, _ in devices]
        iqc_map, repairs_map = {}, {}
        if device_ids:
            iqcs = (await db.execute(
                select(IQCInspection).where(IQCInspection.device_id.in_(device_ids))
            )).scalars().all()
            for i in iqcs:
                iqc_map[str(i.device_id)] = i
            rjs = (await db.execute(
                select(RepairJob).where(RepairJob.device_id.in_(device_ids))
                .order_by(RepairJob.started_at.desc())
            )).scalars().all()
            for r in rjs:
                repairs_map.setdefault(str(r.device_id), []).append(r)
        # ── Parts consumed: required parts (from IQC) + whether the part request
        #    was Received → "Changed", else "Not Changed". ─────────────────────
        parts_map = {}
        if device_ids:
            prs = (await db.execute(
                select(PartRequest).where(PartRequest.device_id.in_(device_ids))
                .order_by(PartRequest.created_at.desc())
            )).scalars().all()
            pr_by_dev_part = {}
            for r in prs:
                pr_by_dev_part.setdefault(str(r.device_id), {}).setdefault(r.part_name, r)
            for d, _ in devices:
                rows = compute_required(iqc_map.get(str(d.id)), d)
                plist = []
                for row in rows:
                    if row.get("required"):
                        req = pr_by_dev_part.get(str(d.id), {}).get(row["label"])
                        plist.append({"label": row["label"],
                                      "changed": bool(req and req.status == "received")})
                parts_map[str(d.id)] = plist

            # ── Changed parts' pricing (Part Master unit price × Device Detail's
            #    verified/handed-over qty) — feeds into the Pricing section below.
            changed_reqs = [r for r in prs if r.status == "received" and r.part_id]
            changed_part_ids = {r.part_id for r in changed_reqs}
            spare_parts_by_id = {}
            if changed_part_ids:
                sp_rows = (await db.execute(
                    select(SparePart).where(SparePart.id.in_(changed_part_ids))
                )).scalars().all()
                spare_parts_by_id = {sp.id: sp for sp in sp_rows}
            changed_parts_pricing = {}
            for r in changed_reqs:
                sp = spare_parts_by_id.get(r.part_id)
                if not sp:
                    continue
                qty = r.qty_handed_over or 0
                unit_price = float(sp.unit_price or 0)
                changed_parts_pricing.setdefault(str(r.device_id), []).append({
                    "label": r.part_name, "unit_price": unit_price,
                    "qty": qty, "total": unit_price * qty,
                })

        # ── Pricing: current unit price → after-repair price (parts actually
        #    consumed, real cost) → updated price shown to the user. ─────────
        price_map = {}
        if device_ids:
            cost_rows = (await db.execute(
                select(
                    SparePartConsumption.device_id,
                    func.coalesce(func.sum(SparePartConsumption.total_cost), 0).label("parts_cost"),
                )
                .where(SparePartConsumption.device_id.in_(device_ids))
                .group_by(SparePartConsumption.device_id)
            )).all()
            parts_cost_by_device = {str(r.device_id): float(r.parts_cost or 0) for r in cost_rows}
            for d, _ in devices:
                current_price = float(d.device_price or 0)
                parts_cost = parts_cost_by_device.get(str(d.id), 0.0)
                changed_cost = sum(p["total"] for p in changed_parts_pricing.get(str(d.id), []))
                after_repair_price = current_price + parts_cost + changed_cost
                price_map[str(d.id)] = {
                    "current_price": current_price,
                    "parts_cost": parts_cost,
                    "changed_parts": changed_parts_pricing.get(str(d.id), []),
                    "changed_parts_cost": changed_cost,
                    "after_repair_price": after_repair_price,
                    "updated_price": after_repair_price,
                }

        return templates.TemplateResponse("cosmetic/final_qc.html", {
            "request": request, "current_user": current_user,
            "stage": stage, "stage_label": STAGE_LABELS[stage],
            "devices": devices, "iqc_map": iqc_map, "repairs_map": repairs_map,
            "parts_map": parts_map, "price_map": price_map,
            "pipeline": COSMETIC_NAV_STAGES, "stage_labels": STAGE_LABELS,
        })

    return templates.TemplateResponse("cosmetic/stage.html", {
        "request": request, "current_user": current_user,
        "stage": stage, "stage_label": STAGE_LABELS[stage],
        "devices": devices,
        "next_stage": next_stage,
        "next_stage_label": STAGE_LABELS.get(next_stage, "Ready to Sale") if next_stage else "Ready to Sale",
        "pipeline": COSMETIC_NAV_STAGES, "stage_labels": STAGE_LABELS,
    })


@router.post("/advance")
async def advance_stage(
    barcode: str = Form(...),
    notes: str = Form(""),
    target: str = Form(""),
    final_qc_status: str = Form("pass"),
    failure_reason: str = Form(""),
    grade: str = Form(""),
    warehouse: str = Form(""),
    updated_make: str = Form(""),
    updated_model: str = Form(""),
    updated_cpu: str = Form(""),
    updated_generation: str = Form(""),
    updated_ram: str = Form(""),
    updated_hdd: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    _perm: User = Depends(require_module_perm("cosmetic", "edit")),
):
    """Move a device to the next cosmetic stage."""
    result = await db.execute(select(Device).where(Device.barcode == barcode))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(404, f"Device {barcode} not found")

    current = device.current_stage
    next_stage = NEXT_COSMETIC.get(current)
    if not next_stage:
        raise HTTPException(400, f"Device {barcode} is not in a cosmetic pipeline stage")

    # "Skip Cosmetic" — jump straight to Final QC from any cosmetic stage
    if target == "final_qc" and current in COSMETIC_PIPELINE and current != DeviceStage.final_qc:
        next_stage = DeviceStage.final_qc

    # Final QC: apply spec corrections + handle fail
    if current == DeviceStage.final_qc:
        if updated_make: device.brand = updated_make
        if updated_model: device.model = updated_model
        if updated_cpu: device.cpu = updated_cpu
        if updated_generation: device.generation = updated_generation
        if warehouse: device.warehouse = warehouse
        # Case-insensitive: master data stores "Fail"/"Pass" (title case), so an exact
        # == "fail" match silently treats every Fail as a Pass in production.
        _is_fail = final_qc_status.strip().lower() == "fail"
        device.final_qc_status = "fail" if _is_fail else "pass"
        if _is_fail:
            device.current_stage = DeviceStage.cleaning
            device.updated_at = app_now()
            movement = StageMovement(
                device_id=device.id, from_stage=current, to_stage=DeviceStage.cleaning,
                moved_by=current_user.username,
                notes=f"Final QC Failed — {failure_reason or 'Rework'}. {notes}"
            )
            db.add(movement)
            await db.commit()
            return RedirectResponse(
                url="/cosmetic/final_qc?error=Final+QC+Failed,+sent+back+for+rework",
                status_code=302
            )

        # Pass only — the Grade dropdown is hidden on fail but still posts its value.
        if grade: device.grade = grade

        # Pricing gate: on Final QC pass, finalize the device price as
        # acquisition price + consumed parts + changed (received) parts —
        # the same arithmetic the Final QC page's Pricing panel displays.
        # Run at most once per device (a rework loop that passes Final QC a
        # second time must not add the same parts costs again).
        already_priced = (await db.execute(
            select(StageMovement.id).where(
                StageMovement.device_id == device.id,
                StageMovement.notes.like("Final QC Passed — price finalized%"),
            ).limit(1)
        )).scalar_one_or_none()
        if not already_priced:
            try:
                parts_cost = float((await db.execute(
                    select(func.coalesce(func.sum(SparePartConsumption.total_cost), 0))
                    .where(SparePartConsumption.device_id == device.id)
                )).scalar() or 0)
                changed_cost = 0.0
                _prs = (await db.execute(
                    select(PartRequest).where(PartRequest.device_id == device.id,
                                              PartRequest.status == "received",
                                              PartRequest.part_id.isnot(None))
                )).scalars().all()
                _pids = {r.part_id for r in _prs}
                if _pids:
                    _sps = {sp.id: sp for sp in (await db.execute(
                        select(SparePart).where(SparePart.id.in_(_pids))
                    )).scalars().all()}
                    for r in _prs:
                        sp = _sps.get(r.part_id)
                        if sp:
                            changed_cost += float(sp.unit_price or 0) * (r.qty_handed_over or 0)
                base_price = float(device.device_price or 0)
                device.device_price = base_price + parts_cost + changed_cost
                db.add(StageMovement(
                    device_id=device.id, from_stage=current, to_stage=current,
                    moved_by=current_user.username,
                    notes=(f"Final QC Passed — price finalized: ₹{base_price:,.0f} + "
                           f"parts ₹{parts_cost:,.0f} + changed ₹{changed_cost:,.0f} "
                           f"= ₹{float(device.device_price):,.0f}")))
            except Exception:
                pass  # pricing snapshot must never block the QC pass itself

    prev = current
    device.current_stage = next_stage
    device.updated_at = app_now()
    movement = StageMovement(
        device_id=device.id, from_stage=prev, to_stage=next_stage,
        moved_by=current_user.username,
        notes=notes or f"Advanced from {STAGE_LABELS.get(prev, prev.value)} to {STAGE_LABELS.get(next_stage, next_stage.value)}"
    )
    db.add(movement)
    await db.commit()

    if next_stage == DeviceStage.ready_to_sale:
        return RedirectResponse(url="/sales/ready?success=Device+moved+to+Ready+to+Sale", status_code=302)

    stage_name = next_stage.value
    return RedirectResponse(url=f"/cosmetic/{stage_name}?success=Device+{barcode}+moved+to+{stage_name.replace('_', '+')}", status_code=302)


@router.post("/send-to-cosmetic")
async def send_to_cosmetic(
    barcode: str = Form(...),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    _perm: User = Depends(require_module_perm("cosmetic", "add")),
):
    """Send a device from QC Check to the Cleaning stage to begin cosmetic refurb."""
    result = await db.execute(select(Device).where(Device.barcode == barcode))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(404, f"Device {barcode} not found")

    prev = device.current_stage
    device.current_stage = DeviceStage.cleaning
    device.updated_at = app_now()
    movement = StageMovement(
        device_id=device.id, from_stage=prev, to_stage=DeviceStage.cleaning,
        moved_by=current_user.username,
        notes=notes or "Sent to Cosmetic Refurbishment"
    )
    db.add(movement)
    await db.commit()
    return RedirectResponse(url="/cosmetic/cleaning?success=Device+sent+to+Cleaning", status_code=302)


# ── Revalidate IQC (item 12 — Final QC page redesign) ───────────────────────
# Editable re-entry of the physical inspection checklist, callable from the
# Final QC page's "Revalidate IQC" tab so QC can correct a defect the
# original IQC pass missed, without leaving Final QC. Whitelisted against
# IQCInspection's real columns (minus identity/system fields) so this can't
# be used to set arbitrary attributes.
IQC_REVALIDATE_FIELDS = [
    "power_on", "bios_password", "all_ok", "status",
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
    "remarks",
]


@router.post("/revalidate-iqc")
async def revalidate_iqc(
    request: Request,
    barcode: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
    _perm: User = Depends(require_module_perm("cosmetic", "edit")),
):
    device = (await db.execute(select(Device).where(Device.barcode == barcode))).scalar_one_or_none()
    if not device:
        raise HTTPException(404, f"Device {barcode} not found")
    iqc = (await db.execute(
        select(IQCInspection).where(IQCInspection.device_id == device.id)
    )).scalar_one_or_none()
    if not iqc:
        raise HTTPException(404, "No IQC inspection record found for this device")

    form = await request.form()
    changed = {}
    for field in IQC_REVALIDATE_FIELDS:
        if field not in form:
            continue
        new_val = form.get(field).strip() or None
        if getattr(iqc, field) != new_val:
            setattr(iqc, field, new_val)
            changed[field] = new_val
    if changed:
        await audit(db, action="IQC_REVALIDATED", user=current_user,
                    table_name="iqc_inspections", record_id=str(iqc.id),
                    new_value=changed, request=request)
        await db.commit()
    return RedirectResponse(
        url=f"/cosmetic/final_qc?success=IQC+revalidated+for+{barcode}#dev-{device.id}",
        status_code=302)
