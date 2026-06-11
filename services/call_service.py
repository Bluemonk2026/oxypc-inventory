"""
services/call_service.py — SINGLE write-path for call records.

Routes that record a call (mobile PWA, desktop form, future AI voice agent
inbound, webhooks) MUST go through this service. Direct INSERTs into
telecalling_records from routers are a code-review blocker as of sprint
2026-05 — see services/call_service_spec.py for the contract.

Side-effects per save_call() (all in one DB transaction):
  1. UPSERT telecalling_records by idempotency_key (dedup offline replays)
  2. UPSERT CRMContact by phone (auto-link or create)
  3. INSERT CRMActivity (timeline)
  4. If call_outcome == 'order_placed' OR create_draft_order:
       -> stub DealerOrderService.create_draft (wire in D5)
  5. If quote_items provided:
       -> stub QuoteService.create_draft + WhatsApp send (wire in D5)
  6. UPDATE matching telecalling_assignments to status='done'
  7. PUBLISH event_bus EventType.CALL_LOGGED (audit trigger fires on INSERT)
"""
from __future__ import annotations

import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Any

from fastapi import BackgroundTasks
from sqlalchemy import select, and_, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.telecalling import TelecallingRecord, TelecallingAssignment
from models.crm import CRMContact, CRMActivity
from services.event_bus import EventType, publish


# Reusable in-process counter for CRM contact codes
async def _next_contact_code(db: AsyncSession) -> str:
    row = await db.execute(
        text("SELECT COUNT(*)+1 FROM crm_contacts WHERE contact_code LIKE 'CRM%'")
    )
    n = row.scalar() or 1
    return f"CRM{n:05d}"


async def _set_audit_session_vars(
    db: AsyncSession,
    username: str,
    user_id: Optional[uuid.UUID] = None,
    ip: Optional[str] = None,
) -> None:
    """Set Postgres session GUC vars consumed by fn_audit_central() trigger."""
    await db.execute(text("SELECT set_config('app.username', :u, true)"), {"u": username or ""})
    if user_id is not None:
        await db.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id)})
    if ip:
        await db.execute(text("SELECT set_config('app.ip', :i, true)"), {"i": ip})


class CallServiceError(Exception):
    """Base class for CallService failures."""


class IdempotencyConflict(CallServiceError):
    """Same key seen with a materially different payload."""


class CallService:
    """Orchestrator. Statelessness: every call passes its own AsyncSession."""

    async def save_call(
        self,
        db: AsyncSession,
        *,
        payload: dict,
        actor_username: str,
        actor_user_id: Optional[uuid.UUID] = None,
        idempotency_key: str,
        device_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> dict:
        """
        Idempotent. Same idempotency_key returns the existing record
        without firing side-effects again.

        Returns a dict matching openapi_telecalling_v1.yaml#CallResult.
        """
        if not idempotency_key:
            raise CallServiceError("idempotency_key required")
        if not payload.get("phone"):
            raise CallServiceError("phone required")

        await _set_audit_session_vars(db, actor_username, actor_user_id, ip_address)

        # 1. Idempotency check — return existing if key matches
        existing = await db.execute(
            select(TelecallingRecord).where(
                TelecallingRecord.idempotency_key == idempotency_key
            )
        )
        existing_row = existing.scalar_one_or_none()
        if existing_row:
            return self._result_dict(existing_row, replay=True)

        # 2. CRMContact upsert by phone
        contact_id = await self._upsert_crm_contact(
            db,
            phone=payload["phone"],
            name=payload.get("customer_name"),
            city=payload.get("city"),
            state=payload.get("state"),
            email=payload.get("email"),
            created_by=actor_username,
        )

        # 3. Insert telecalling_records (audit trigger fires)
        rec = TelecallingRecord(
            id=uuid.uuid4(),
            dealer_id=payload.get("dealer_id"),
            crm_contact_id=contact_id,
            call_source=payload.get("call_source", "prospect"),
            customer_name=payload.get("customer_name"),
            phone=payload["phone"],
            email=payload.get("email"),
            customer_type=payload.get("customer_type"),
            city=payload.get("city"),
            state=payload.get("state"),
            category=payload.get("category"),
            brand=payload.get("brand"),
            model=payload.get("model"),
            grade=payload.get("grade"),
            lot_id=payload.get("lot_id"),
            lot_line_item_id=payload.get("lot_line_item_id"),
            called_by=actor_username,
            call_date=payload.get("call_date") or datetime.utcnow(),
            call_outcome=payload.get("call_outcome"),
            quantity_required=payload.get("quantity_required"),
            budget=_to_decimal(payload.get("budget")),
            next_followup=payload.get("next_followup"),
            notes=payload.get("notes"),
            idempotency_key=idempotency_key,
            device_id=device_id or payload.get("device_id"),
            latitude=_to_decimal(payload.get("latitude")),
            longitude=_to_decimal(payload.get("longitude")),
            call_duration_secs=payload.get("call_duration_secs"),
            is_active=True,
        )
        db.add(rec)
        await db.flush()  # need rec.id for activity link

        # 4. CRMActivity log
        activity = CRMActivity(
            id=uuid.uuid4(),
            contact_id=contact_id,
            activity_type="call",
            activity_date=rec.call_date,
            next_followup=rec.next_followup,
            outcome=rec.call_outcome,
            notes=rec.notes,
            created_by=actor_username,
        )
        db.add(activity)

        # 5. Mark matching assignment 'done' (best-effort)
        assignment_id = await self._close_matching_assignment(
            db, agent=actor_username, phone=rec.phone, call_record_id=rec.id
        )

        # 6. DNC propagation
        if rec.call_outcome == "do_not_call":
            await db.execute(
                CRMContact.__table__.update()
                .where(CRMContact.id == contact_id)
                .values(do_not_contact=True,
                        do_not_contact_reason=f"Set by telecaller {actor_username}")
            )

        # 7. Draft DealerOrder hook (stub — wire in D5)
        dealer_order_id = None
        if rec.call_outcome == "order_placed" or payload.get("create_draft_order"):
            dealer_order_id = await self._stub_create_draft_order(
                db, dealer_id=rec.dealer_id, agent=actor_username, call_id=rec.id
            )
            if dealer_order_id:
                rec.dealer_order_id = dealer_order_id

        # 8. Quote + WhatsApp hook (stub — wire in D5)
        crm_quote_id = None
        whatsapp_message_id = None
        if payload.get("send_quote_via_whatsapp") and payload.get("quote_items"):
            crm_quote_id, whatsapp_message_id = await self._stub_send_quote(
                db,
                contact_id=contact_id,
                call_id=rec.id,
                items=payload["quote_items"],
                actor=actor_username,
            )
            if crm_quote_id:
                rec.crm_quote_id = crm_quote_id

        await db.commit()

        # 9. Publish event (after commit — handlers run in background)
        event_payload = {
            "call_id": str(rec.id),
            "agent": actor_username,
            "phone": rec.phone,
            "outcome": rec.call_outcome,
            "dealer_id": str(rec.dealer_id) if rec.dealer_id else None,
            "crm_contact_id": str(contact_id),
            "dealer_order_id": str(dealer_order_id) if dealer_order_id else None,
            "crm_quote_id": str(crm_quote_id) if crm_quote_id else None,
        }
        publish(EventType.CALL_LOGGED, event_payload, background_tasks)
        if dealer_order_id:
            publish(EventType.CALL_ORDER_PLACED, event_payload, background_tasks)
        if crm_quote_id:
            publish(EventType.CALL_QUOTE_SENT, event_payload, background_tasks)
        if rec.call_outcome == "do_not_call":
            publish(EventType.CALL_DNC_SET, event_payload, background_tasks)

        return {
            "record_id": str(rec.id),
            "crm_contact_id": str(contact_id),
            "crm_activity_id": str(activity.id),
            "dealer_order_id": str(dealer_order_id) if dealer_order_id else None,
            "crm_quote_id": str(crm_quote_id) if crm_quote_id else None,
            "whatsapp_message_id": str(whatsapp_message_id) if whatsapp_message_id else None,
            "assignment_id": str(assignment_id) if assignment_id else None,
        }

    async def cancel_call(
        self, db: AsyncSession, *, record_id: uuid.UUID, actor: str, reason: str
    ) -> None:
        await _set_audit_session_vars(db, actor)
        await db.execute(
            TelecallingRecord.__table__.update()
            .where(TelecallingRecord.id == record_id)
            .values(is_active=False, deleted_at=datetime.utcnow(),
                    notes=func.coalesce(TelecallingRecord.notes, "") +
                          f"\n[CANCELLED by {actor}] {reason}")
        )
        await db.commit()

    # ── private helpers ─────────────────────────────────────────────────

    async def _upsert_crm_contact(
        self, db: AsyncSession, *,
        phone: str, name: Optional[str], city: Optional[str],
        state: Optional[str], email: Optional[str], created_by: str,
    ) -> uuid.UUID:
        row = await db.execute(
            select(CRMContact).where(CRMContact.phone == phone).limit(1)
        )
        existing = row.scalar_one_or_none()
        if existing:
            return existing.id

        contact = CRMContact(
            id=uuid.uuid4(),
            contact_code=await _next_contact_code(db),
            contact_type="buyer",
            company_name=name or f"Lead {phone[-4:]}",
            contact_person=name,
            phone=phone,
            whatsapp=phone,
            email=email,
            city=city,
            state=state,
            buyer_type="retail",
            status="active",
            assigned_to=created_by,
            created_by=created_by,
        )
        db.add(contact)
        await db.flush()
        return contact.id

    async def _close_matching_assignment(
        self, db: AsyncSession, *, agent: str, phone: str, call_record_id: uuid.UUID,
    ) -> Optional[uuid.UUID]:
        row = await db.execute(
            select(TelecallingAssignment).where(and_(
                TelecallingAssignment.agent_username == agent,
                TelecallingAssignment.lead_phone == phone,
                TelecallingAssignment.status.in_(("pending", "in_progress")),
                TelecallingAssignment.is_active.is_(True),
                func.date(TelecallingAssignment.due_date) == date.today(),
            )).limit(1)
        )
        assignment = row.scalar_one_or_none()
        if not assignment:
            return None
        assignment.status = "done"
        assignment.call_record_id = call_record_id
        await db.flush()
        return assignment.id

    async def _stub_create_draft_order(
        self, db: AsyncSession, *, dealer_id, agent: str, call_id: uuid.UUID
    ) -> Optional[uuid.UUID]:
        """STUB. D5: wire to existing POST /dealers/{id}/orders/new path
        (routers/dealers.py:838) extracted into a DealerOrderService."""
        return None  # No-op until D5

    async def _stub_send_quote(
        self, db: AsyncSession, *,
        contact_id: uuid.UUID, call_id: uuid.UUID, items: list[dict], actor: str,
    ) -> tuple[Optional[uuid.UUID], Optional[uuid.UUID]]:
        """STUB. D5: wire to QuoteService.create_draft + routers/whatsapp.py:send_message."""
        return None, None

    def _result_dict(self, rec: TelecallingRecord, *, replay: bool = False) -> dict:
        return {
            "record_id": str(rec.id),
            "crm_contact_id": str(rec.crm_contact_id) if rec.crm_contact_id else None,
            "crm_activity_id": None,
            "dealer_order_id": str(rec.dealer_order_id) if rec.dealer_order_id else None,
            "crm_quote_id": str(rec.crm_quote_id) if rec.crm_quote_id else None,
            "whatsapp_message_id": None,
            "assignment_id": None,
            "replay": replay,
        }


def _to_decimal(v: Any) -> Optional[Decimal]:
    if v in (None, ""):
        return None
    return Decimal(str(v))


# Singleton for routers
call_service = CallService()
