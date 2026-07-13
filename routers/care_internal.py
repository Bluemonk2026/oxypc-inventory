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
from models.care import CareDevicePairing
from auth.dependencies import require_module_perm, verify_csrf
from services.care_service import PROVISIONING_TOKEN_TTL_MINUTES, care_audit
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

    existing = (await db.execute(
        select(CareDevicePairing).where(
            CareDevicePairing.device_id == device_id,
            CareDevicePairing.is_active == True,  # noqa: E712
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Device already has an active pairing — revoke it first")

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
