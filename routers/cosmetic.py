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
from sqlalchemy import select, func, update
from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceStage, StageMovement
from models.bucket import Bucket, _new_bucket_number
from models.lot import Lot
from models.iqc_inspection import IQCInspection
from models.repair import RepairJob
from models.part_request import PartRequest
from models.spare_parts import SparePart, SparePartConsumption
from services.parts_required import compute_required
from services.audit_engine import audit
from services.notifications import create_notification
from auth.dependencies import get_current_user, require_roles, verify_csrf, require_module_perm
from models.work_order import WorkOrder
from routers.transfers import _gen_work_id
import uuid as uuid_module

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


async def _bucket_group(db: AsyncSession, stage: DeviceStage, status_val: str):
    """Group active, bucket-linked devices at `stage` (with `final_qc_status`
    == status_val) by their bucket — feeds the Devices Passed / Devices
    Failed tables on the Final QC page."""
    rows = (await db.execute(
        select(Device).where(
            Device.current_stage == stage,
            Device.final_qc_status == status_val,
            Device.is_active == True,
            Device.bucket_id.isnot(None),
        )
    )).scalars().all()
    bucket_ids = {d.bucket_id for d in rows}
    buckets_by_id = {}
    if bucket_ids:
        b_rows = (await db.execute(select(Bucket).where(Bucket.id.in_(bucket_ids)))).scalars().all()
        buckets_by_id = {b.id: b for b in b_rows}
    grouped = {}
    for d in rows:
        b = buckets_by_id.get(d.bucket_id)
        if not b:
            continue
        g = grouped.setdefault(b.id, {
            "bucket_id": str(b.id), "bucket_name": b.name or b.bucket_number, "bucket_number": b.bucket_number,
            "count": 0, "failure_reason": None, "pass_notes": None,
        })
        g["count"] += 1
        g["failure_reason"] = g["failure_reason"] or d.fqc_failure_reason
        g["pass_notes"] = g["pass_notes"] or d.fqc_pass_notes
    return list(grouped.values())


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

        bucket_ids_for_page = {d.bucket_id for d, _ in devices if d.bucket_id}
        bucket_name_map = {}
        if bucket_ids_for_page:
            b_rows = (await db.execute(select(Bucket).where(Bucket.id.in_(bucket_ids_for_page)))).scalars().all()
            bname_by_id = {b.id: b.name for b in b_rows}
            # Pre-fills the Bucket Name text box on the Final QC Decision tab
            # for a device that already carries a bucket_id — "" (not a dash)
            # since this feeds a form value, not read-only display text.
            bucket_name_map = {str(d.id): bname_by_id.get(d.bucket_id, "") for d, _ in devices if d.bucket_id}

        passed_buckets = await _bucket_group(db, DeviceStage.final_qc_pass_hold, "pass")
        failed_buckets = await _bucket_group(db, DeviceStage.final_qc_fail_hold, "fail")

        return templates.TemplateResponse("cosmetic/final_qc.html", {
            "request": request, "current_user": current_user,
            "stage": stage, "stage_label": STAGE_LABELS[stage],
            "devices": devices, "iqc_map": iqc_map, "repairs_map": repairs_map,
            "parts_map": parts_map, "price_map": price_map,
            "pipeline": COSMETIC_NAV_STAGES, "stage_labels": STAGE_LABELS,
            "bucket_name_map": bucket_name_map,
            "passed_buckets": passed_buckets, "failed_buckets": failed_buckets,
        })

    # ── Most recent L1/L2 Engineer per device, for the "L1/L2 Engineer" column
    # and to pre-populate the Fail modal's context — same resolution as the
    # Stress Test page (routers/qc.py qc_list) and routers/repair.py's own
    # "assigned to me" queries: latest WorkOrder at stage="l1" wins.
    device_ids = [d.id for d, _ in devices]
    l1l2_engineer_map: dict[str, str] = {}
    if device_ids:
        wo_rows = await db.execute(
            select(WorkOrder.device_id, WorkOrder.assigned_name, WorkOrder.assigned_at)
            .where(WorkOrder.device_id.in_(device_ids), WorkOrder.stage == "l1",
                   WorkOrder.assigned_name.isnot(None))
            .order_by(WorkOrder.assigned_at.desc())
        )
        for did, name, _ in wo_rows.all():
            l1l2_engineer_map.setdefault(str(did), name)

    # ── L1/L2 engineer pool for the Fail modal's dropdown — identical pool to
    # the Stress Test page's own Fail modal (routers/qc.py qc_list).
    l1l2_result = await db.execute(
        select(User).where(
            User.role.in_([UserRole.l1_engineer, UserRole.l2_engineer]),
            User.status == True,
        ).order_by(User.full_name)
    )
    l1l2_engineers = [
        {"id": str(u.id), "name": u.full_name or u.username, "role": u.role.value}
        for u in l1l2_result.scalars().all()
    ]

    return templates.TemplateResponse("cosmetic/stage.html", {
        "request": request, "current_user": current_user,
        "stage": stage, "stage_label": STAGE_LABELS[stage],
        "devices": devices,
        "next_stage": next_stage,
        "next_stage_label": STAGE_LABELS.get(next_stage, "Ready to Sale") if next_stage else "Ready to Sale",
        "pipeline": COSMETIC_NAV_STAGES, "stage_labels": STAGE_LABELS,
        "l1l2_engineer_map": l1l2_engineer_map, "l1l2_engineers": l1l2_engineers,
    })


@router.post("/advance")
async def advance_stage(
    barcode: str = Form(...),
    notes: str = Form(""),
    target: str = Form(""),
    final_qc_status: str = Form("pass"),
    failure_reason: str = Form(""),
    pass_notes: str = Form(""),
    bucket_name: str = Form(""),
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
        # Bucket is a free-text Bucket Name here, not a dropdown of existing
        # buckets — typing a name that doesn't exist yet creates it. Before
        # attaching the current device, every OTHER device already linked to
        # that bucket gets its bucket_id cleared UNLESS it is itself sitting
        # at Final QC Pass/Fail Hold — those are left alone so several tags
        # decided into the same Bucket Name keep accumulating together.
        # Anything else sharing the bucket_id (long since sold, scrapped, or
        # mid-repair from an earlier, unrelated use of the same name) is what
        # a later "move bucket to Production" would otherwise sweep in.
        bucket_name = bucket_name.strip()
        if bucket_name:
            bucket = (await db.execute(
                select(Bucket).where(func.lower(Bucket.name) == bucket_name.lower())
            )).scalars().first()
            if not bucket:
                bucket = Bucket(name=bucket_name, bucket_number=_new_bucket_number(),
                                 created_by=current_user.username)
                db.add(bucket)
                await db.flush()
            await db.execute(
                update(Device)
                .where(Device.bucket_id == bucket.id,
                       Device.id != device.id,
                       Device.current_stage.notin_(
                           [DeviceStage.final_qc_pass_hold, DeviceStage.final_qc_fail_hold]))
                .values(bucket_id=None)
            )
            device.bucket_id = bucket.id
        else:
            device.bucket_id = None
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
            # Hold here instead of auto-advancing to Cleaning — the device now
            # sits in the "Devices Failed" table until a human clicks
            # "Move to Production" (see /cosmetic/final-qc/move-to-production).
            device.fqc_failure_reason = (failure_reason or "").strip() or None
            device.current_stage = DeviceStage.final_qc_fail_hold
            device.updated_at = app_now()
            movement = StageMovement(
                device_id=device.id, from_stage=current, to_stage=DeviceStage.final_qc_fail_hold,
                moved_by=current_user.username,
                notes=f"Final QC Failed — {failure_reason or 'Rework'}. {notes}"
            )
            db.add(movement)
            await db.commit()
            return RedirectResponse(
                url="/cosmetic/final_qc?warning=Final+QC+Failed+for+" + barcode + "+%E2%80%94+recorded+successfully",
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

        # Hold here instead of auto-advancing to Ready to Sale — the device
        # now sits in the "Devices Passed" table until a human clicks
        # "Move to Inventory" (see /cosmetic/final-qc/move-to-inventory).
        device.fqc_pass_notes = (pass_notes or "").strip() or None
        device.current_stage = DeviceStage.final_qc_pass_hold
        device.updated_at = app_now()
        db.add(StageMovement(
            device_id=device.id, from_stage=current, to_stage=DeviceStage.final_qc_pass_hold,
            moved_by=current_user.username,
            notes=f"Final QC Passed — {pass_notes or ''}".strip(),
        ))
        await db.commit()
        return RedirectResponse(
            url="/cosmetic/final_qc?success=Final+QC+Passed+for+" + barcode,
            status_code=302
        )

    prev = current
    # A device arriving at Final QC releases any bucket it still carries from
    # an earlier stage (e.g. a Stock In bucket never explicitly released) — a
    # stale bucket_id here is how an unrelated old tag sharing that reused
    # bucket number ended up swept into a later bulk bucket action against it.
    # Final QC's own Bucket dropdown starts every arriving device clean.
    if next_stage == DeviceStage.final_qc:
        device.bucket_id = None
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


@router.post("/final-qc/move-to-inventory/{bucket_id}")
async def fqc_move_to_inventory(bucket_id: str, db: AsyncSession = Depends(get_db),
                                 current_user: User = Depends(allowed)):
    """Devices Passed → Final QC Pass (Buckets) on Inventory Manager."""
    import uuid as _u
    try:
        bid = _u.UUID(bucket_id)
    except ValueError:
        raise HTTPException(404)
    devices = (await db.execute(
        select(Device).where(
            Device.bucket_id == bid,
            Device.current_stage == DeviceStage.final_qc_pass_hold,
            Device.is_active == True,
        )
    )).scalars().all()
    if not devices:
        raise HTTPException(404, "No devices found in this bucket at Final QC Pass Hold.")
    for device in devices:
        device.current_stage = DeviceStage.ready_to_sale
        device.updated_at = app_now()
        db.add(StageMovement(
            device_id=device.id, from_stage=DeviceStage.final_qc_pass_hold, to_stage=DeviceStage.ready_to_sale,
            moved_by=current_user.username, notes="Moved to Inventory from Final QC Pass",
        ))
    await db.commit()
    return {"ok": True, "moved": len(devices)}


@router.post("/final-qc/move-to-production/{bucket_id}")
async def fqc_move_to_production(bucket_id: str, db: AsyncSession = Depends(get_db),
                                  current_user: User = Depends(allowed)):
    """Devices Failed → Final QC Fail (Bucket) on Production Manager, ready for Assign."""
    import uuid as _u
    try:
        bid = _u.UUID(bucket_id)
    except ValueError:
        raise HTTPException(404)
    devices = (await db.execute(
        select(Device).where(
            Device.bucket_id == bid,
            Device.current_stage == DeviceStage.final_qc_fail_hold,
            Device.is_active == True,
        )
    )).scalars().all()
    if not devices:
        raise HTTPException(404, "No devices found in this bucket at Final QC Fail Hold.")
    for device in devices:
        device.current_stage = DeviceStage.l1
        device.updated_at = app_now()
        db.add(StageMovement(
            device_id=device.id, from_stage=DeviceStage.final_qc_fail_hold, to_stage=DeviceStage.l1,
            moved_by=current_user.username, notes="Moved to Production from Final QC Fail",
        ))
    bucket = (await db.execute(select(Bucket).where(Bucket.id == bid))).scalar_one_or_none()
    if bucket:
        bucket.assigned_to_production = False
    await db.commit()
    return {"ok": True, "moved": len(devices)}


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


@router.post("/{barcode}/fail")
async def cosmetic_fail_assign(
    barcode: str,
    engineer_user_id: str = Form(...),
    notes: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """'Fail' on the Cleaning / Water Sanding pages — assign the device to an
    L1/L2 engineer. Same "Fail — Assign to L1/L2 Engineer" modal and the same
    WorkOrder + stage-move mechanism as the Stress Test page's own Fail
    action (routers/stress_api.py stress_fail_assign) — kept as a separate
    endpoint rather than reused directly so the note/notification wording
    says what actually failed (a cosmetic stage, not a stress test) and
    lands in device.repair_notes (the shared Repair Notes field) rather than
    the stress-test-specific device.stress_notes.
    """
    device = (await db.execute(select(Device).where(Device.barcode == barcode))).scalar_one_or_none()
    if not device:
        raise HTTPException(404, f"Device {barcode} not found")
    if device.current_stage not in (DeviceStage.cleaning, DeviceStage.water_sanding):
        raise HTTPException(400, "This device is not at Cleaning or Water Sanding")

    try:
        eng_uuid = uuid_module.UUID(engineer_user_id)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(400, "Invalid engineer selected")

    engineer = (await db.execute(select(User).where(User.id == eng_uuid))).scalar_one_or_none()
    if not engineer or engineer.role not in (UserRole.l1_engineer, UserRole.l2_engineer):
        raise HTTPException(400, "Selected user is not an active L1/L2 engineer")

    from_stage_label = STAGE_LABELS.get(device.current_stage, device.current_stage.value)
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

    device.current_stage = DeviceStage.l1
    # Same fresh-cycle reset as the Stress Test page's Fail action — a device
    # returning from a cosmetic fail starts a new repair cycle.
    device.l1l2_status = "New"
    device.l34_status = None
    device.updated_at = app_now()

    repair_note = f"{from_stage_label} Failed — assigned to {engineer.full_name or engineer.username}"
    if notes:
        repair_note += f". {notes}"
    device.repair_notes = repair_note

    db.add(StageMovement(device_id=device.id, from_stage=prev_stage, to_stage=DeviceStage.l1,
                         moved_by=current_user.username, notes=repair_note))

    work_id = await _gen_work_id(db)
    db.add(WorkOrder(
        work_id=work_id, device_id=device.id, barcode=device.barcode,
        stage="l1", assigned_role=engineer.role.value,
        assigned_user_id=engineer.id, assigned_username=engineer.username,
        assigned_name=engineer.full_name, status="pending",
        created_by=current_user.username,
    ))

    await create_notification(
        db, user_id=engineer.id, title="Device Assigned to You",
        message=(f"{device.barcode} failed {from_stage_label} and has been assigned to you for "
                 f"L1/L2 repair (WorkID: {work_id})."),
        notification_type="warning",
        barcode=device.barcode, brand=device.brand, model=device.model,
        stage=DeviceStage.l1.value,
    )

    await audit(db, user=current_user, action="COSMETIC_FAIL_ASSIGNED",
                table_name="devices", record_id=str(device.id),
                new_value={"from_stage": prev_stage.value, "assigned_to": engineer.username,
                           "work_id": work_id, "notes": notes},
                request=None)

    await db.commit()
    return RedirectResponse(
        url=f"/cosmetic/{prev_stage.value}?success=Device+failed+%26+assigned+to+" +
            (engineer.full_name or engineer.username).replace(" ", "+"),
        status_code=302,
    )
