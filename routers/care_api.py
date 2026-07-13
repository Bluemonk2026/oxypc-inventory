"""Customer Care Agent — public device-facing API (/care/api/v1).

The ONLY thing the customer-installed desktop agent talks to. Every route
resolves the caller's pairing via the device-bound bearer token and scopes
all queries to that pairing — no route accepts an arbitrary device_id,
sale_id, or ticket id from the client without verifying ownership first.

Response envelope and error codes follow the spec's section 12.1 contract so
the desktop agent has one shape to parse for every endpoint.
"""
import uuid as uuid_mod
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.care import CareDevicePairing, CareSupportTicket, CareTicketEvent, CareDiagnosticSnapshot, CareOffer, CareAgentEvent
from auth.care_auth import get_current_pairing, _hash_ip
from services.care_service import (
    next_ticket_number, resolve_warranty, validate_diagnostic_payload,
    validate_ticket_description, validate_category, care_audit, CareError,
    PROVISIONING_TOKEN_TTL_MINUTES,
)
from utils.timezone import app_now
from limiter import limiter

router = APIRouter(prefix="/care/api/v1", tags=["care-agent-public"])

MIN_SUPPORTED_AGENT_VERSION = "1.0.0"


def _envelope(data: dict) -> dict:
    return {"success": True, "data": data, "request_id": str(uuid_mod.uuid4()),
            "server_time": app_now().isoformat()}


def _error(code: str, message: str, status_code: int = 400, retryable: bool = False):
    return JSONResponse(status_code=status_code, content={
        "success": False,
        "error": {"code": code, "message": message, "retryable": retryable},
        "request_id": str(uuid_mod.uuid4()), "server_time": app_now().isoformat(),
    })


@router.post("/pair")
@limiter.limit("10/minute")
async def pair(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """One-time provisioning-secret redemption. Single-use, expiring, atomic —
    a second redemption attempt of the same token must fail."""
    body = await request.json()
    provisioning_token = (body.get("provisioning_token") or "").strip()
    bios_serial = (body.get("bios_serial") or "").strip()
    agent_version = (body.get("agent_version") or "")[:20]

    if not provisioning_token:
        return _error("CARE_MISSING_TOKEN", "provisioning_token is required")

    token_hash = CareDevicePairing.hash_token(provisioning_token)
    pairing = (await db.execute(
        select(CareDevicePairing).where(
            CareDevicePairing.provisioning_token_hash == token_hash,
            CareDevicePairing.provisioning_redeemed_at.is_(None),
        )
    )).scalar_one_or_none()

    if not pairing:
        return _error("CARE_INVALID_TOKEN", "Invalid or already-used provisioning token", 401)

    if pairing.provisioning_token_expires_at and app_now() > pairing.provisioning_token_expires_at:
        return _error("CARE_TOKEN_EXPIRED", "Provisioning token has expired", 401)

    if bios_serial and pairing.serial_no and bios_serial.lower() != pairing.serial_no.lower():
        await care_audit(db, "PAIR_SERIAL_MISMATCH", actor_type="system",
                         pairing_id=pairing.id, ip_hash=_hash_ip(request))
        await db.commit()
        return _error("CARE_DEVICE_MISMATCH", "Device identity does not match the expected record", 401)

    raw_device_token, device_token_hash = CareDevicePairing.generate_token()
    now = app_now()

    # Atomic redemption: only succeeds if still un-redeemed at this exact moment
    result = await db.execute(
        update(CareDevicePairing)
        .where(CareDevicePairing.id == pairing.id, CareDevicePairing.provisioning_redeemed_at.is_(None))
        .values(
            provisioning_redeemed_at=now,
            provisioning_token_hash=None,  # invalidate — cannot be redeemed again
            device_token_hash=device_token_hash,
            device_token_issued_at=now,
            paired_at=now,
            agent_version=agent_version or None,
            is_active=True,
        )
    )
    if result.rowcount == 0:
        await db.rollback()
        return _error("CARE_INVALID_TOKEN", "Invalid or already-used provisioning token", 401)

    await care_audit(db, "PAIRING_COMPLETED", actor_type="system", pairing_id=pairing.id,
                     ip_hash=_hash_ip(request))
    db.add(CareAgentEvent(pairing_id=pairing.id, event_type="pairing_completed", agent_version=agent_version))
    await db.commit()

    return _envelope({
        "device_token": raw_device_token,  # shown exactly once — never retrievable again
        "pairing_id": str(pairing.id),
        "minimum_agent_version": MIN_SUPPORTED_AGENT_VERSION,
    })


@router.get("/device")
async def get_device(
    pairing: CareDevicePairing = Depends(get_current_pairing),
    db: AsyncSession = Depends(get_db),
):
    w = await resolve_warranty(db, pairing.device_id, pairing.sale_id)
    open_count = (await db.execute(
        select(CareSupportTicket).where(
            CareSupportTicket.pairing_id == pairing.id,
            CareSupportTicket.status.notin_(["closed", "cancelled", "resolved"]),
        )
    )).scalars().all()
    masked_serial = None
    if pairing.serial_no:
        s = pairing.serial_no
        masked_serial = ("*" * max(len(s) - 4, 0)) + s[-4:]
    return _envelope({
        "model": None,  # populated in Phase 2 device-brief join; MVP keeps this narrow
        "serial_masked": masked_serial,
        "agent_status": "active" if pairing.is_active else "inactive",
        "warranty_status": w["status"],
        "open_ticket_count": len(open_count),
    })


@router.get("/warranty")
async def get_warranty(
    pairing: CareDevicePairing = Depends(get_current_pairing),
    db: AsyncSession = Depends(get_db),
):
    w = await resolve_warranty(db, pairing.device_id, pairing.sale_id)
    return _envelope(w)


@router.get("/offers")
async def get_offers(
    pairing: CareDevicePairing = Depends(get_current_pairing),
    db: AsyncSession = Depends(get_db),
):
    now = app_now()
    offers = (await db.execute(
        select(CareOffer).where(
            CareOffer.is_active == True,  # noqa: E712
            (CareOffer.starts_at.is_(None)) | (CareOffer.starts_at <= now),
            (CareOffer.ends_at.is_(None)) | (CareOffer.ends_at >= now),
            CareOffer.channel.in_(["in_app", "both"]),
        ).order_by(CareOffer.created_at.desc())
    )).scalars().all()
    # target_type filtering happens here (all / model / warranty_window / sale_range) —
    # MVP ships "all" live; model/warranty-window targeting narrows in Phase 2 once
    # get_device's model/warranty join is wired.
    visible = [o for o in offers if o.target_type == "all"]
    return _envelope({"offers": [
        {"id": str(o.id), "title": o.title, "body": o.body, "image_url": o.image_url,
         "cta_label": o.cta_label, "cta_url": o.cta_url}
        for o in visible
    ]})


@router.get("/tickets")
async def list_tickets(
    pairing: CareDevicePairing = Depends(get_current_pairing),
    db: AsyncSession = Depends(get_db),
):
    tickets = (await db.execute(
        select(CareSupportTicket).where(CareSupportTicket.pairing_id == pairing.id)
        .order_by(CareSupportTicket.created_at.desc()).limit(50)
    )).scalars().all()
    return _envelope({"tickets": [
        {"ticket_number": t.ticket_number, "category": t.category, "status": t.status,
         "priority": t.priority, "created_at": t.created_at.isoformat(),
         "customer_visible_notes": t.customer_visible_notes}
        for t in tickets
    ]})


@router.post("/tickets")
@limiter.limit("10/minute")
async def create_ticket(
    request: Request,
    idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
    pairing: CareDevicePairing = Depends(get_current_pairing),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    try:
        category = validate_category(body.get("category"))
        description = validate_ticket_description(body.get("description"))
    except CareError as e:
        return _error(e.code, e.message)

    subcategory = (body.get("subcategory") or "")[:50] or None
    contact_pref = (body.get("customer_contact_preference") or "")[:20] or None
    diagnostics = body.get("diagnostics")  # optional inline snapshot payload

    idem = idempotency_key or body.get("idempotency_key")
    if idem:
        existing = (await db.execute(
            select(CareSupportTicket).where(CareSupportTicket.idempotency_key == idem)
        )).scalar_one_or_none()
        if existing:
            return _envelope({"ticket_number": existing.ticket_number, "status": existing.status,
                              "deduped": True})

    ticket = CareSupportTicket(
        ticket_number=await next_ticket_number(db),
        pairing_id=pairing.id, device_id=pairing.device_id, sale_id=pairing.sale_id,
        category=category, subcategory=subcategory, description=description,
        customer_contact_preference=contact_pref, status="open",
        idempotency_key=idem,
    )
    db.add(ticket)
    await db.flush()

    db.add(CareTicketEvent(ticket_id=ticket.id, event_type="created", new_status="open",
                           actor_type="customer"))

    if diagnostics:
        try:
            clean = validate_diagnostic_payload(diagnostics)
        except CareError as e:
            await db.rollback()
            return _error(e.code, e.message)
        db.add(CareDiagnosticSnapshot(
            pairing_id=pairing.id, ticket_id=ticket.id,
            agent_version=pairing.agent_version, raw_json=clean,
            bios_serial=clean.get("bios_serial"), manufacturer=clean.get("manufacturer"),
            model=clean.get("model"), cpu=clean.get("cpu"), ram_gb=clean.get("ram_gb"),
            storage_summary=clean.get("storage_summary"),
            battery_health_pct=clean.get("battery_health_pct"),
            battery_cycle_count=clean.get("battery_cycle_count"),
            smart_status=clean.get("smart_status"), os_version=clean.get("os_version"),
            hardware_warning_summary=clean.get("hardware_warning_summary"),
            system_error_summary=clean.get("system_error_summary"),
        ))

    await care_audit(db, "TICKET_CREATED", actor_type="customer", pairing_id=pairing.id,
                     ticket_id=ticket.id, ip_hash=_hash_ip(request))
    await db.commit()
    return _envelope({"ticket_number": ticket.ticket_number, "status": ticket.status})


@router.get("/tickets/{ticket_number}")
async def get_ticket(
    ticket_number: str,
    pairing: CareDevicePairing = Depends(get_current_pairing),
    db: AsyncSession = Depends(get_db),
):
    ticket = (await db.execute(
        select(CareSupportTicket).where(
            CareSupportTicket.ticket_number == ticket_number,
            CareSupportTicket.pairing_id == pairing.id,  # object-level scoping — not just auth
        )
    )).scalar_one_or_none()
    if not ticket:
        return _error("CARE_TICKET_NOT_FOUND", "Ticket not found", 404)
    return _envelope({
        "ticket_number": ticket.ticket_number, "status": ticket.status,
        "priority": ticket.priority, "customer_visible_notes": ticket.customer_visible_notes,
        "pickup_required": ticket.pickup_required, "created_at": ticket.created_at.isoformat(),
        "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
    })


@router.post("/diagnostics")
@limiter.limit("20/minute")
async def submit_diagnostics(
    request: Request,
    pairing: CareDevicePairing = Depends(get_current_pairing),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    payload = body.get("diagnostics") or {}
    ticket_number = body.get("ticket_number")
    try:
        clean = validate_diagnostic_payload(payload)
    except CareError as e:
        return _error(e.code, e.message)

    ticket_id = None
    if ticket_number:
        ticket = (await db.execute(
            select(CareSupportTicket).where(
                CareSupportTicket.ticket_number == ticket_number,
                CareSupportTicket.pairing_id == pairing.id,
            )
        )).scalar_one_or_none()
        if not ticket:
            return _error("CARE_TICKET_NOT_FOUND", "Ticket not found", 404)
        ticket_id = ticket.id

    snap = CareDiagnosticSnapshot(
        pairing_id=pairing.id, ticket_id=ticket_id, agent_version=pairing.agent_version,
        raw_json=clean, bios_serial=clean.get("bios_serial"), manufacturer=clean.get("manufacturer"),
        model=clean.get("model"), cpu=clean.get("cpu"), ram_gb=clean.get("ram_gb"),
        storage_summary=clean.get("storage_summary"), battery_health_pct=clean.get("battery_health_pct"),
        battery_cycle_count=clean.get("battery_cycle_count"), smart_status=clean.get("smart_status"),
        os_version=clean.get("os_version"), hardware_warning_summary=clean.get("hardware_warning_summary"),
        system_error_summary=clean.get("system_error_summary"),
    )
    db.add(snap)
    await care_audit(db, "DIAGNOSTIC_SUBMITTED", actor_type="customer", pairing_id=pairing.id,
                     ticket_id=ticket_id, ip_hash=_hash_ip(request))
    await db.commit()
    return _envelope({"snapshot_id": str(snap.id)})


@router.post("/heartbeat")
async def heartbeat(
    request: Request,
    pairing: CareDevicePairing = Depends(get_current_pairing),
    db: AsyncSession = Depends(get_db),
):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    agent_version = (body.get("agent_version") or "")[:20] or pairing.agent_version
    await db.execute(
        update(CareDevicePairing).where(CareDevicePairing.id == pairing.id)
        .values(agent_version=agent_version, last_seen_at=app_now())
    )
    await db.commit()
    return _envelope({
        "minimum_agent_version": MIN_SUPPORTED_AGENT_VERSION,
        "update_required": False,
    })


@router.post("/token/rotate")
@limiter.limit("5/minute")
async def rotate_token(
    request: Request,
    pairing: CareDevicePairing = Depends(get_current_pairing),
    db: AsyncSession = Depends(get_db),
):
    raw_device_token, device_token_hash = CareDevicePairing.generate_token()
    await db.execute(
        update(CareDevicePairing).where(CareDevicePairing.id == pairing.id)
        .values(device_token_hash=device_token_hash, token_last_rotated_at=app_now())
    )
    await care_audit(db, "TOKEN_ROTATED", actor_type="customer", pairing_id=pairing.id,
                     ip_hash=_hash_ip(request))
    await db.commit()
    return _envelope({"device_token": raw_device_token})


@router.post("/deactivate")
async def deactivate(
    request: Request,
    pairing: CareDevicePairing = Depends(get_current_pairing),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(CareDevicePairing).where(CareDevicePairing.id == pairing.id)
        .values(is_active=False, revoked_at=app_now(), revoked_reason="customer_requested")
    )
    await care_audit(db, "PAIRING_DEACTIVATED", actor_type="customer", pairing_id=pairing.id,
                     ip_hash=_hash_ip(request))
    await db.commit()
    return _envelope({"deactivated": True})
