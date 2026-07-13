"""Customer Care Agent — internal staff-facing endpoints (/care/internal).

Phase 1 scope: the provisioning endpoint imaging tooling calls to create a
pending pairing + one-time secret for a specific unit before dispatch.
Staff ticket/diagnostic screens (Phase 2) mount here too as they're built.
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from models.device import Device
from models.care import CareDevicePairing, CareDispatchException, DISPATCH_EXCEPTION_REASONS
from auth.dependencies import require_module_perm, verify_csrf
from services.care_service import (
    PROVISIONING_TOKEN_TTL_MINUTES, care_audit, resolve_dispatch_readiness,
    has_pending_or_active_pairing,
)
from utils.timezone import app_now

router = APIRouter(prefix="/care/internal", tags=["care-agent-internal"])


@router.post("/pairings")
async def create_pending_pairing(
    request: Request,
    device_id: str = Form(...),
    sale_id: str = Form(default=None),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("care_support", "add")),
    db: AsyncSession = Depends(get_db),
):
    """Called by imaging tooling right before dispatch. Generates a single-use
    provisioning secret (shown once, embedded into that unit's install step —
    never baked into a reusable installer image)."""
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if await has_pending_or_active_pairing(db, device_id):
        raise HTTPException(status_code=409,
                           detail="Device already has an active or pending pairing — revoke it first")

    raw_token, token_hash = CareDevicePairing.generate_token()
    pairing = CareDevicePairing(
        device_id=device_id, sale_id=sale_id or None, serial_no=device.serial_no or device.barcode,
        provisioning_token_hash=token_hash,
        provisioning_token_expires_at=app_now() + timedelta(minutes=PROVISIONING_TOKEN_TTL_MINUTES),
        created_by=current_user.username,
    )
    db.add(pairing)
    await db.flush()
    await care_audit(db, "PAIRING_CREATED", actor_type="staff", actor_id=current_user.username,
                     pairing_id=pairing.id)
    await db.commit()

    return JSONResponse({
        "pairing_id": str(pairing.id),
        "provisioning_token": raw_token,  # shown once — imaging tool must embed it now
        "expires_at": pairing.provisioning_token_expires_at.isoformat(),
    })


@router.post("/pairings/{pairing_id}/revoke")
async def revoke_pairing(
    request: Request,
    pairing_id: str,
    reason: str = Form(...),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("care_support", "edit")),
    db: AsyncSession = Depends(get_db),
):
    pairing = (await db.execute(select(CareDevicePairing).where(CareDevicePairing.id == pairing_id))).scalar_one_or_none()
    if not pairing:
        raise HTTPException(status_code=404, detail="Pairing not found")
    pairing.is_active = False
    pairing.revoked_at = app_now()
    pairing.revoked_reason = reason.strip()[:200]
    await care_audit(db, "PAIRING_REVOKED", actor_type="staff", actor_id=current_user.username,
                     pairing_id=pairing.id, new_value={"reason": pairing.revoked_reason})
    await db.commit()
    return JSONResponse({"revoked": True})


@router.get("/dispatch-readiness/{device_id}")
async def dispatch_readiness(
    device_id: str,
    current_user: User = Depends(require_module_perm("care_support")),
    db: AsyncSession = Depends(get_db),
):
    """Advisory only (spec section 16) — not called by routers/dispatch.py or
    routers/sales.py yet. See models.care.CareDispatchException docstring."""
    return JSONResponse(await resolve_dispatch_readiness(db, device_id))


@router.post("/dispatch-exceptions")
async def create_dispatch_exception(
    request: Request,
    device_id: str = Form(...),
    reason: str = Form(...),
    notes: str = Form(default=""),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("care_support", "add")),
    db: AsyncSession = Depends(get_db),
):
    if reason not in DISPATCH_EXCEPTION_REASONS:
        raise HTTPException(status_code=400, detail=f"Unknown reason. Must be one of {DISPATCH_EXCEPTION_REASONS}")
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    exc = CareDispatchException(
        device_id=device_id, reason=reason, notes=notes.strip()[:1000] or None,
        approved_by=current_user.username,
    )
    db.add(exc)
    await db.flush()
    await care_audit(db, "DISPATCH_EXCEPTION_RECORDED", actor_type="staff", actor_id=current_user.username,
                     new_value={"device_id": str(device_id), "reason": reason})
    await db.commit()
    return JSONResponse({"exception_id": str(exc.id), "reason": exc.reason})
