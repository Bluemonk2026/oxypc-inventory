"""Customer Care Agent — staff HTML screens (/care-support).

Ticket queue, ticket detail (diagnostics/timeline/assign/status/notes/
pickup), and pairing list. Guarded by staff JWT + the care_support module
permission — mirrors routers/partner_admin.py conventions so this matches
the rest of the staff app. The narrow public device API stays in
routers/care_api.py; the imaging-tooling JSON endpoints stay in
routers/care_internal.py. This file is HTML only.
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from datetime import timedelta

from database import get_db
from templates_config import templates
from models.user import User
from models.device import Device
from models.sales import Sale
from models.care import (
    CareDevicePairing, CareSupportTicket, CareTicketEvent,
    CareDiagnosticSnapshot, CareDispatchException, DISPATCH_EXCEPTION_REASONS,
    CareOffer, CareOfferDelivery, TICKET_STATUSES, TICKET_PRIORITIES,
)
from auth.dependencies import require_module_perm, verify_csrf
from services.care_service import (
    care_audit, resolve_warranty, resolve_dispatch_readiness,
    resolve_offer_targets, send_offer_whatsapp, record_offer_delivery,
    has_pending_or_active_pairing, PROVISIONING_TOKEN_TTL_MINUTES,
)
from utils.timezone import app_now

router = APIRouter(prefix="/care-support", tags=["care-agent-admin"])


async def _staff_users(db: AsyncSession):
    r = await db.execute(
        select(User.username, User.full_name).where(User.status == True)  # noqa: E712
        .order_by(User.username)
    )
    return r.all()


@router.get("/tickets", response_class=HTMLResponse)
async def ticket_queue(
    request: Request,
    status: str = "",
    priority: str = "",
    q: str = "",
    current_user: User = Depends(require_module_perm("care_support")),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(CareSupportTicket)
        .options(selectinload(CareSupportTicket.pairing))
        .order_by(CareSupportTicket.created_at.desc())
    )
    if status:
        query = query.where(CareSupportTicket.status == status)
    if priority:
        query = query.where(CareSupportTicket.priority == priority)
    tickets = (await db.execute(query.limit(500))).scalars().all()

    device_ids = {t.device_id for t in tickets}
    devices = {}
    if device_ids:
        rows = (await db.execute(select(Device).where(Device.id.in_(device_ids)))).scalars().all()
        devices = {d.id: d for d in rows}

    if q:
        ql = q.lower()
        def _match(t):
            d = devices.get(t.device_id)
            return (ql in (t.ticket_number or "").lower()
                    or (d and ql in (d.barcode or "").lower())
                    or (d and ql in (d.serial_no or "").lower())
                    or (d and ql in (d.model or "").lower()))
        tickets = [t for t in tickets if _match(t)]

    staff = await _staff_users(db)
    return templates.TemplateResponse("care/tickets.html", {
        "request": request, "current_user": current_user,
        "tickets": tickets, "devices": devices, "staff": staff,
        "statuses": TICKET_STATUSES, "priorities": TICKET_PRIORITIES,
        "f_status": status, "f_priority": priority, "q": q,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


async def _get_ticket(db: AsyncSession, ticket_number: str) -> CareSupportTicket:
    ticket = (await db.execute(
        select(CareSupportTicket)
        .options(selectinload(CareSupportTicket.pairing),
                 selectinload(CareSupportTicket.events),
                 selectinload(CareSupportTicket.snapshots))
        .where(CareSupportTicket.ticket_number == ticket_number)
    )).scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@router.get("/tickets/{ticket_number}", response_class=HTMLResponse)
async def ticket_detail(
    request: Request,
    ticket_number: str,
    current_user: User = Depends(require_module_perm("care_support")),
    db: AsyncSession = Depends(get_db),
):
    ticket = await _get_ticket(db, ticket_number)
    device = await db.get(Device, ticket.device_id)
    sale = await db.get(Sale, ticket.sale_id) if ticket.sale_id else None
    warranty = await resolve_warranty(db, ticket.device_id, ticket.sale_id)

    prior = (await db.execute(
        select(CareSupportTicket)
        .where(CareSupportTicket.device_id == ticket.device_id,
               CareSupportTicket.id != ticket.id)
        .order_by(CareSupportTicket.created_at.desc())
    )).scalars().all()

    staff = await _staff_users(db)
    return templates.TemplateResponse("care/ticket_detail.html", {
        "request": request, "current_user": current_user,
        "ticket": ticket, "device": device, "sale": sale, "warranty": warranty,
        "prior_tickets": prior, "staff": staff,
        "statuses": TICKET_STATUSES, "priorities": TICKET_PRIORITIES,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@router.post("/tickets/{ticket_number}/assign")
async def assign_ticket(
    request: Request,
    ticket_number: str,
    assigned_to: str = Form(...),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("care_support", "edit")),
    db: AsyncSession = Depends(get_db),
):
    ticket = await _get_ticket(db, ticket_number)
    ticket.assigned_to = assigned_to
    if ticket.status == "open":
        ticket.status = "assigned"
    db.add(CareTicketEvent(
        ticket_id=ticket.id, event_type="assigned", actor_type="staff",
        actor_id=current_user.username, notes=f"Assigned to {assigned_to}",
        new_status=ticket.status,
    ))
    await care_audit(db, "TICKET_ASSIGNED", actor_type="staff", actor_id=current_user.username,
                     ticket_id=ticket.id, new_value={"assigned_to": assigned_to})
    await db.commit()
    return RedirectResponse(url=f"/care-support/tickets/{ticket_number}?success=Assigned+to+{assigned_to}",
                            status_code=302)


@router.post("/tickets/{ticket_number}/status")
async def change_status(
    request: Request,
    ticket_number: str,
    new_status: str = Form(...),
    notes: str = Form(default=""),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("care_support", "edit")),
    db: AsyncSession = Depends(get_db),
):
    if new_status not in TICKET_STATUSES:
        return RedirectResponse(url=f"/care-support/tickets/{ticket_number}?error=Invalid+status", status_code=302)
    ticket = await _get_ticket(db, ticket_number)
    old_status = ticket.status
    ticket.status = new_status
    now = app_now()
    if new_status == "resolved":
        ticket.resolved_at = now
        ticket.resolved_by = current_user.username
    if new_status == "closed":
        ticket.closed_at = now
    db.add(CareTicketEvent(
        ticket_id=ticket.id, event_type="status_change", actor_type="staff",
        actor_id=current_user.username, notes=notes.strip()[:500] or None,
        old_status=old_status, new_status=new_status,
    ))
    await care_audit(db, "TICKET_STATUS_CHANGED", actor_type="staff", actor_id=current_user.username,
                     ticket_id=ticket.id, old_value={"status": old_status}, new_value={"status": new_status})
    await db.commit()
    return RedirectResponse(url=f"/care-support/tickets/{ticket_number}?success=Status+updated+to+{new_status}",
                            status_code=302)


@router.post("/tickets/{ticket_number}/priority")
async def change_priority(
    request: Request,
    ticket_number: str,
    new_priority: str = Form(...),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("care_support", "edit")),
    db: AsyncSession = Depends(get_db),
):
    if new_priority not in TICKET_PRIORITIES:
        return RedirectResponse(url=f"/care-support/tickets/{ticket_number}?error=Invalid+priority", status_code=302)
    ticket = await _get_ticket(db, ticket_number)
    ticket.priority = new_priority
    db.add(CareTicketEvent(
        ticket_id=ticket.id, event_type="priority_change", actor_type="staff",
        actor_id=current_user.username, notes=f"Priority set to {new_priority}",
    ))
    await db.commit()
    return RedirectResponse(url=f"/care-support/tickets/{ticket_number}?success=Priority+updated",
                            status_code=302)


@router.post("/tickets/{ticket_number}/note")
async def add_note(
    request: Request,
    ticket_number: str,
    note_text: str = Form(...),
    customer_visible: str = Form(default=""),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("care_support", "edit")),
    db: AsyncSession = Depends(get_db),
):
    note_text = note_text.strip()[:2000]
    if not note_text:
        return RedirectResponse(url=f"/care-support/tickets/{ticket_number}?error=Note+cannot+be+empty",
                                status_code=302)
    ticket = await _get_ticket(db, ticket_number)
    if customer_visible == "on":
        ticket.customer_visible_notes = ((ticket.customer_visible_notes or "") +
                                         f"\n[{app_now():%Y-%m-%d %H:%M}] {note_text}").strip()[-4000:]
    db.add(CareTicketEvent(
        ticket_id=ticket.id, event_type="note_added", actor_type="staff",
        actor_id=current_user.username, notes=note_text,
    ))
    await db.commit()
    return RedirectResponse(url=f"/care-support/tickets/{ticket_number}?success=Note+added", status_code=302)


@router.post("/tickets/{ticket_number}/pickup")
async def set_pickup(
    request: Request,
    ticket_number: str,
    pickup_reference: str = Form(default=""),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("care_support", "edit")),
    db: AsyncSession = Depends(get_db),
):
    ticket = await _get_ticket(db, ticket_number)
    ticket.pickup_required = True
    ticket.pickup_reference = pickup_reference.strip()[:50] or None
    if ticket.status not in ("resolved", "closed", "cancelled"):
        ticket.status = "needs_pickup"
    db.add(CareTicketEvent(
        ticket_id=ticket.id, event_type="pickup_scheduled", actor_type="staff",
        actor_id=current_user.username, notes=f"Pickup ref: {ticket.pickup_reference or '—'}",
        new_status=ticket.status,
    ))
    await care_audit(db, "PICKUP_SCHEDULED", actor_type="staff", actor_id=current_user.username,
                     ticket_id=ticket.id, new_value={"pickup_reference": ticket.pickup_reference})
    await db.commit()
    return RedirectResponse(url=f"/care-support/tickets/{ticket_number}?success=Pickup+scheduled", status_code=302)


@router.get("/pairings", response_class=HTMLResponse)
async def pairing_list(
    request: Request,
    q: str = "",
    current_user: User = Depends(require_module_perm("care_support")),
    db: AsyncSession = Depends(get_db),
):
    query = select(CareDevicePairing).order_by(CareDevicePairing.created_at.desc())
    pairings = (await db.execute(query.limit(500))).scalars().all()

    device_ids = {p.device_id for p in pairings}
    devices = {}
    if device_ids:
        rows = (await db.execute(select(Device).where(Device.id.in_(device_ids)))).scalars().all()
        devices = {d.id: d for d in rows}

    if q:
        ql = q.lower()
        pairings = [p for p in pairings
                    if ql in (p.serial_no or "").lower()
                    or (devices.get(p.device_id) and ql in (devices[p.device_id].barcode or "").lower())]

    return templates.TemplateResponse("care/pairings.html", {
        "request": request, "current_user": current_user,
        "pairings": pairings, "devices": devices, "q": q,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@router.post("/pairings/{pairing_id}/revoke")
async def revoke_pairing_html(
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
    return RedirectResponse(url="/care-support/pairings?success=Pairing+revoked", status_code=302)


# ── Phase 4: provisioning + dispatch exceptions ─────────────────────────
# Advisory only — see models.care.CareDispatchException docstring for why
# this doesn't hard-block routers/sales.py or routers/dispatch.py yet.

@router.get("/provision", response_class=HTMLResponse)
async def provision_search(
    request: Request,
    q: str = "",
    current_user: User = Depends(require_module_perm("care_support")),
    db: AsyncSession = Depends(get_db),
):
    devices = []
    if q:
        rows = (await db.execute(
            select(Device).where(
                (Device.barcode.ilike(f"%{q}%")) | (Device.serial_no.ilike(f"%{q}%"))
            ).limit(25)
        )).scalars().all()
        readiness = {}
        for d in rows:
            readiness[d.id] = await resolve_dispatch_readiness(db, d.id)
        devices = [(d, readiness[d.id]) for d in rows]

    return templates.TemplateResponse("care/provision.html", {
        "request": request, "current_user": current_user,
        "q": q, "devices": devices, "reasons": DISPATCH_EXCEPTION_REASONS,
        "token": request.query_params.get("token"),
        "token_expires": request.query_params.get("expires"),
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@router.post("/provision/{device_id}")
async def provision_device(
    request: Request,
    device_id: str,
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("care_support", "add")),
    db: AsyncSession = Depends(get_db),
):
    """HTML wrapper around the same logic as POST /care/internal/pairings —
    shown once on this page (not persisted in query-string history beyond
    this single redirect) since the raw provisioning token is a secret."""
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if not device:
        return RedirectResponse(url="/care-support/provision?error=Device+not+found", status_code=302)

    if await has_pending_or_active_pairing(db, device_id):
        return RedirectResponse(
            url="/care-support/provision?error=Device+already+has+an+active+or+pending+pairing",
            status_code=302)

    raw_token, token_hash = CareDevicePairing.generate_token()
    pairing = CareDevicePairing(
        device_id=device_id, serial_no=device.serial_no or device.barcode,
        provisioning_token_hash=token_hash,
        provisioning_token_expires_at=app_now() + timedelta(minutes=PROVISIONING_TOKEN_TTL_MINUTES),
        created_by=current_user.username,
    )
    db.add(pairing)
    await db.flush()
    await care_audit(db, "PAIRING_CREATED", actor_type="staff", actor_id=current_user.username,
                     pairing_id=pairing.id)
    await db.commit()

    from urllib.parse import quote
    return RedirectResponse(
        url=f"/care-support/provision?q={quote(device.barcode)}&token={quote(raw_token)}"
            f"&expires={pairing.provisioning_token_expires_at.isoformat()}",
        status_code=302,
    )


@router.post("/dispatch-exceptions")
async def record_dispatch_exception_html(
    request: Request,
    device_id: str = Form(...),
    reason: str = Form(...),
    notes: str = Form(default=""),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("care_support", "add")),
    db: AsyncSession = Depends(get_db),
):
    if reason not in DISPATCH_EXCEPTION_REASONS:
        return RedirectResponse(url="/care-support/provision?error=Invalid+reason", status_code=302)
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if not device:
        return RedirectResponse(url="/care-support/provision?error=Device+not+found", status_code=302)

    exc = CareDispatchException(
        device_id=device_id, reason=reason, notes=notes.strip()[:1000] or None,
        approved_by=current_user.username,
    )
    db.add(exc)
    await care_audit(db, "DISPATCH_EXCEPTION_RECORDED", actor_type="staff", actor_id=current_user.username,
                     new_value={"device_id": str(device_id), "reason": reason})
    await db.commit()
    from urllib.parse import quote
    return RedirectResponse(
        url=f"/care-support/provision?q={quote(device.barcode)}&success=Exception+recorded", status_code=302,
    )


# ── Phase 5: offers CRUD + WhatsApp send ────────────────────────────────

@router.get("/offers", response_class=HTMLResponse)
async def offers_list(
    request: Request,
    current_user: User = Depends(require_module_perm("care_support")),
    db: AsyncSession = Depends(get_db),
):
    offers = (await db.execute(select(CareOffer).order_by(CareOffer.created_at.desc()))).scalars().all()
    return templates.TemplateResponse("care/offers.html", {
        "request": request, "current_user": current_user, "offers": offers,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@router.post("/offers")
async def create_offer(
    request: Request,
    title: str = Form(...),
    body: str = Form(default=""),
    cta_label: str = Form(default=""),
    cta_url: str = Form(default=""),
    target_type: str = Form(default="all"),
    target_value: str = Form(default=""),
    channel: str = Form(default="in_app"),
    is_marketing: str = Form(default="on"),
    consent_required: str = Form(default="on"),
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("care_support", "add")),
    db: AsyncSession = Depends(get_db),
):
    offer = CareOffer(
        title=title.strip()[:200], body=body.strip()[:2000] or None,
        cta_label=cta_label.strip()[:50] or None, cta_url=cta_url.strip()[:500] or None,
        target_type=target_type, target_value=target_value.strip()[:200] or None,
        channel=channel, is_marketing=(is_marketing == "on"),
        consent_required=(consent_required == "on"), created_by=current_user.username,
    )
    db.add(offer)
    await db.commit()
    return RedirectResponse(url="/care-support/offers?success=Offer+created", status_code=302)


@router.post("/offers/{offer_id}/toggle")
async def toggle_offer(
    request: Request,
    offer_id: str,
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("care_support", "edit")),
    db: AsyncSession = Depends(get_db),
):
    offer = (await db.execute(select(CareOffer).where(CareOffer.id == offer_id))).scalar_one_or_none()
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    offer.is_active = not offer.is_active
    await db.commit()
    return RedirectResponse(url="/care-support/offers?success=Offer+updated", status_code=302)


@router.post("/offers/{offer_id}/send")
async def send_offer(
    request: Request,
    offer_id: str,
    _csrf=Depends(verify_csrf),
    current_user: User = Depends(require_module_perm("care_support", "edit")),
    db: AsyncSession = Depends(get_db),
):
    """In-app offers need no send action (the agent already polls
    GET /care/api/v1/offers). This only fires for whatsapp/both channel
    offers, and only to pairings that have explicitly opted into marketing
    (CareDevicePairing.marketing_opt_in) when consent_required is set."""
    offer = (await db.execute(select(CareOffer).where(CareOffer.id == offer_id))).scalar_one_or_none()
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if offer.channel not in ("whatsapp", "both"):
        return RedirectResponse(url="/care-support/offers?error=Offer+channel+has+no+WhatsApp+send+step",
                               status_code=302)

    targets = await resolve_offer_targets(db, offer)
    sent, skipped, failed = 0, 0, 0
    for device_id, sale_id in targets:
        pairing = (await db.execute(
            select(CareDevicePairing).where(
                CareDevicePairing.device_id == device_id, CareDevicePairing.is_active == True,  # noqa: E712
            )
        )).scalar_one_or_none()
        if offer.consent_required and (not pairing or not pairing.marketing_opt_in):
            await record_offer_delivery(db, offer.id, device_id, "whatsapp", "skipped_no_consent")
            skipped += 1
            continue
        sale = await db.get(Sale, sale_id) if sale_id else None
        phone = sale.customer_phone if sale else None
        if not phone:
            await record_offer_delivery(db, offer.id, device_id, "whatsapp", "failed", "No phone on file")
            failed += 1
            continue
        status_code, resp = await send_offer_whatsapp(phone, f"{offer.title}\n\n{offer.body or ''}",
                                                       current_user.username)
        if status_code == 200 and resp.get("success"):
            await record_offer_delivery(db, offer.id, device_id, "whatsapp", "sent", sent_by=current_user.username)
            sent += 1
        else:
            await record_offer_delivery(db, offer.id, device_id, "whatsapp", "failed",
                                       resp.get("error", "send failed")[:300], current_user.username)
            failed += 1
    await db.commit()
    return RedirectResponse(
        url=f"/care-support/offers?success=Sent+{sent}%2C+skipped+{skipped}+(no+consent)%2C+failed+{failed}",
        status_code=302,
    )


# ── Phase 6: pilot acceptance-gate dashboard ────────────────────────────

@router.get("/pilot", response_class=HTMLResponse)
async def pilot_dashboard(
    request: Request,
    current_user: User = Depends(require_module_perm("care_support")),
    db: AsyncSession = Depends(get_db),
):
    """Computed from real care_* tables only — no fabricated pilot numbers.
    Shows zeros/blank until real paired devices and tickets exist."""
    total_pairings = (await db.execute(select(func.count(CareDevicePairing.id)))).scalar() or 0
    active_pairings = (await db.execute(
        select(func.count(CareDevicePairing.id)).where(CareDevicePairing.is_active == True)  # noqa: E712
    )).scalar() or 0
    redeemed = (await db.execute(
        select(func.count(CareDevicePairing.id)).where(CareDevicePairing.provisioning_redeemed_at.isnot(None))
    )).scalar() or 0
    pairing_success_pct = round((redeemed / total_pairings) * 100, 1) if total_pairings else None

    total_tickets = (await db.execute(select(func.count(CareSupportTicket.id)))).scalar() or 0
    resolved_tickets = (await db.execute(
        select(func.count(CareSupportTicket.id)).where(CareSupportTicket.status.in_(("resolved", "closed")))
    )).scalar() or 0
    tickets_with_diagnostics = (await db.execute(
        select(func.count(func.distinct(CareDiagnosticSnapshot.ticket_id)))
    )).scalar() or 0
    diagnostic_completion_pct = round((tickets_with_diagnostics / total_tickets) * 100, 1) if total_tickets else None

    dead_letter_note = ("Offline-queue dead-letter counts live on-device only "
                        "(care_agent_windows/service/offline_queue.py) — not yet reported to the server; "
                        "add a queue-health field to the heartbeat call before this can show here.")

    return templates.TemplateResponse("care/pilot.html", {
        "request": request, "current_user": current_user,
        "total_pairings": total_pairings, "active_pairings": active_pairings,
        "pairing_success_pct": pairing_success_pct,
        "total_tickets": total_tickets, "resolved_tickets": resolved_tickets,
        "diagnostic_completion_pct": diagnostic_completion_pct,
        "dead_letter_note": dead_letter_note,
    })
