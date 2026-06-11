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
from sqlalchemy import select
from database import get_db
from models.user import User, UserRole
from models.device import Device, DeviceStage, StageMovement
from models.lot import Lot
from auth.dependencies import get_current_user, require_roles, verify_csrf, require_module_perm

router = APIRouter(prefix="/cosmetic", tags=["cosmetic"], dependencies=[Depends(verify_csrf)])
allowed = require_roles(UserRole.admin, UserRole.inventory_manager)

# Ordered cosmetic pipeline — each stage advances to the next
COSMETIC_PIPELINE = [
    DeviceStage.cleaning,
    DeviceStage.dry_sanding,
    DeviceStage.masking,
    DeviceStage.painting,
    DeviceStage.water_sanding,
    DeviceStage.final_qc,
]

NEXT_COSMETIC = {
    DeviceStage.qc_check:    DeviceStage.cleaning,
    DeviceStage.cleaning:    DeviceStage.dry_sanding,
    DeviceStage.dry_sanding: DeviceStage.masking,
    DeviceStage.masking:     DeviceStage.painting,
    DeviceStage.painting:    DeviceStage.water_sanding,
    DeviceStage.water_sanding: DeviceStage.final_qc,
    DeviceStage.final_qc:    DeviceStage.ready_to_sale,
}

STAGE_LABELS = {
    DeviceStage.cleaning:     "Cleaning",
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
    return templates.TemplateResponse("cosmetic/stage.html", {
        "request": request, "current_user": current_user,
        "stage": stage, "stage_label": STAGE_LABELS[stage],
        "devices": devices,
        "next_stage": next_stage,
        "next_stage_label": STAGE_LABELS.get(next_stage, "Ready to Sale") if next_stage else "Ready to Sale",
        "pipeline": COSMETIC_PIPELINE, "stage_labels": STAGE_LABELS,
    })


@router.post("/advance")
async def advance_stage(
    barcode: str = Form(...),
    notes: str = Form(""),
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

    # Final QC: apply spec corrections + handle fail
    if current == DeviceStage.final_qc:
        if updated_make: device.brand = updated_make
        if updated_model: device.model = updated_model
        if updated_cpu: device.cpu = updated_cpu
        if updated_generation: device.generation = updated_generation
        if grade: device.grade = grade
        if warehouse: device.warehouse = warehouse
        if final_qc_status == "fail":
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
