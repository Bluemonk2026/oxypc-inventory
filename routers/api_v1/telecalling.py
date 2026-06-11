"""
/api/v1/telecalling/* — JSON layer for the mobile PWA.

Source-of-truth contract: output/OxyPC/Telecalling-Mobile/openapi_telecalling_v1.yaml
Single write path: services.call_service.CallService — do NOT INSERT into
telecalling_records from this module. Reads may go direct.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from utils.timezone import app_now
from typing import Optional

from fastapi import (
    APIRouter, Depends, BackgroundTasks, Header, HTTPException, Query, Request, status,
)
from pydantic import BaseModel, Field
from sqlalchemy import select, text, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from auth.dependencies import get_current_user, ROLE_PERMISSIONS
from models.user import User, UserRole
from models.telecalling import TelecallingRecord, TelecallingAssignment
from services.call_service import call_service, CallServiceError

router = APIRouter(prefix="/telecalling", tags=["api-v1-telecalling"])


# ── helpers ─────────────────────────────────────────────────────────────────

def _has(user: User, perm: str) -> bool:
    perms = ROLE_PERMISSIONS.get(user.role, [])
    return "*" in perms or perm in perms


def _require(user: User, perm: str) -> None:
    if not _has(user, perm):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing permission: {perm}")


# ── Pydantic schemas (match openapi_telecalling_v1.yaml) ────────────────────

class QuoteItem(BaseModel):
    lot_line_item_id: uuid.UUID
    qty: int
    unit_price: float


class CallPayloadIn(BaseModel):
    phone: str
    call_source: str = "prospect"
    dealer_id: Optional[uuid.UUID] = None
    crm_contact_id: Optional[uuid.UUID] = None
    customer_name: Optional[str] = None
    customer_type: Optional[str] = None
    email: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    call_outcome: Optional[str] = None
    call_duration_secs: Optional[int] = None
    quantity_required: Optional[int] = None
    budget: Optional[float] = None
    next_followup: Optional[datetime] = None
    notes: Optional[str] = None
    lot_id: Optional[uuid.UUID] = None
    lot_line_item_id: Optional[uuid.UUID] = None
    category: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    grade: Optional[str] = None
    device_id: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    create_draft_order: bool = False
    send_quote_via_whatsapp: bool = False
    quote_items: list[QuoteItem] = Field(default_factory=list)


class AssignmentLead(BaseModel):
    dealer_id: Optional[uuid.UUID] = None
    crm_contact_id: Optional[uuid.UUID] = None
    lead_phone: str
    customer_name: Optional[str] = None
    priority: str = "normal"
    notes: Optional[str] = None


class AssignmentBulk(BaseModel):
    agent_username: str
    due_date: date
    leads: list[AssignmentLead]


# ── /session/today ──────────────────────────────────────────────────────────

@router.get("/session/today")
async def session_today(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require(user, "tc.call.view_own")
    today = date.today()
    kpi_row = await db.execute(
        text("SELECT * FROM sp_telecalling_kpi(:u, :d, :d)"),
        {"u": user.username, "d": today},
    )
    kpi = kpi_row.mappings().first() or {}

    pending = await db.execute(
        select(func.count()).select_from(TelecallingAssignment).where(and_(
            TelecallingAssignment.agent_username == user.username,
            TelecallingAssignment.due_date == today,
            TelecallingAssignment.status.in_(("pending", "in_progress")),
            TelecallingAssignment.is_active.is_(True),
        ))
    )
    overdue = await db.execute(
        select(func.count()).select_from(TelecallingRecord).where(and_(
            TelecallingRecord.called_by == user.username,
            TelecallingRecord.next_followup < app_now(),
            TelecallingRecord.is_active.is_(True),
        ))
    )
    return {
        "agent_username": user.username,
        "date": today.isoformat(),
        "calls_made": kpi.get("total_calls", 0),
        "connected": kpi.get("connected", 0),
        "interested": kpi.get("interested", 0),
        "orders_placed": kpi.get("orders_placed", 0),
        "target_calls": kpi.get("target_calls", 50),
        "attainment_pct": float(kpi.get("attainment_pct", 0) or 0),
        "avg_duration_secs": int(kpi.get("avg_duration_secs", 0) or 0),
        "pending_assignments": pending.scalar() or 0,
        "overdue_followups": overdue.scalar() or 0,
    }


# ── /assigned-leads ─────────────────────────────────────────────────────────

@router.get("/assigned-leads")
async def assigned_leads(
    target_date: Optional[date] = Query(default=None, alias="date"),
    status_filter: str = Query(default="open", alias="status"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require(user, "tc.queue.view_own")
    d = target_date or date.today()
    rows = await db.execute(
        text("SELECT * FROM sp_telecalling_daily_queue(:u, :d)"),
        {"u": user.username, "d": d},
    )
    return [dict(r) for r in rows.mappings()]


# ── /assignments (POST) — sales_manager only ────────────────────────────────

@router.post("/assignments", status_code=201)
async def create_assignments(
    body: AssignmentBulk,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require(user, "tc.assign.create")
    # Sales-manager may only assign to direct reports
    if user.role == UserRole.sales_manager:
        target = await db.execute(
            select(User).where(User.username == body.agent_username)
        )
        target_user = target.scalar_one_or_none()
        if not target_user or target_user.manager_username != user.username:
            raise HTTPException(403, "agent is not in your team")

    created = []
    for lead in body.leads:
        rec = TelecallingAssignment(
            id=uuid.uuid4(),
            agent_username=body.agent_username,
            lead_phone=lead.lead_phone,
            dealer_id=lead.dealer_id,
            crm_contact_id=lead.crm_contact_id,
            customer_name=lead.customer_name,
            priority=lead.priority,
            assigned_by=user.username,
            due_date=body.due_date,
            status="pending",
            notes=lead.notes,
        )
        db.add(rec)
        created.append(rec.id)
    await db.commit()
    return {"created": [str(x) for x in created]}


# ── /calls (POST) — THE WRITE PATH ──────────────────────────────────────────

@router.post("/calls", status_code=201)
async def create_call(
    payload: CallPayloadIn,
    request: Request,
    background_tasks: BackgroundTasks,
    idempotency_key: str = Header(..., alias="Idempotency-Key", max_length=64),
    x_device_id: Optional[str] = Header(default=None, alias="X-Device-Id"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require(user, "tc.call.create")
    try:
        result = await call_service.save_call(
            db,
            payload=payload.model_dump(mode="json"),
            actor_username=user.username,
            actor_user_id=user.id,
            idempotency_key=idempotency_key,
            device_id=x_device_id,
            ip_address=(request.client.host if request.client else None),
            background_tasks=background_tasks,
        )
        return result
    except CallServiceError as e:
        raise HTTPException(400, str(e))


# ── /calls (GET) — list with RBAC scoping ───────────────────────────────────

@router.get("/calls")
async def list_calls(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    agent: Optional[str] = None,
    outcome: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Scope by permission
    q = select(TelecallingRecord).where(TelecallingRecord.is_active.is_(True))
    if _has(user, "tc.call.view_all") or user.role == UserRole.admin:
        if agent:
            q = q.where(TelecallingRecord.called_by == agent)
    elif _has(user, "tc.call.view_team"):
        team = await db.execute(
            select(User.username).where(User.manager_username == user.username)
        )
        usernames = [r[0] for r in team] + [user.username]
        q = q.where(TelecallingRecord.called_by.in_(usernames))
        if agent and agent in usernames:
            q = q.where(TelecallingRecord.called_by == agent)
    else:
        _require(user, "tc.call.view_own")
        q = q.where(TelecallingRecord.called_by == user.username)

    if outcome:
        q = q.where(TelecallingRecord.call_outcome == outcome)
    if date_from:
        q = q.where(func.date(TelecallingRecord.call_date) >= date_from)
    if date_to:
        q = q.where(func.date(TelecallingRecord.call_date) <= date_to)
    q = q.order_by(TelecallingRecord.call_date.desc()).limit(limit)

    rows = await db.execute(q)
    items = []
    for r in rows.scalars():
        items.append({
            "id": str(r.id), "phone": r.phone,
            "customer_name": r.customer_name,
            "called_by": r.called_by,
            "call_date": r.call_date.isoformat() if r.call_date else None,
            "call_outcome": r.call_outcome,
            "call_duration_secs": r.call_duration_secs,
            "next_followup": r.next_followup.isoformat() if r.next_followup else None,
            "dealer_id": str(r.dealer_id) if r.dealer_id else None,
            "crm_contact_id": str(r.crm_contact_id) if r.crm_contact_id else None,
            "dealer_order_id": str(r.dealer_order_id) if r.dealer_order_id else None,
            "crm_quote_id": str(r.crm_quote_id) if r.crm_quote_id else None,
        })
    return {"items": items, "next_cursor": None}


# ── /calls/{id}/timeline ────────────────────────────────────────────────────

@router.get("/calls/{call_id}/timeline")
async def call_timeline(
    call_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require(user, "tc.call.view_own")
    # Resolve the lead behind this call
    row = await db.execute(
        select(TelecallingRecord).where(TelecallingRecord.id == call_id)
    )
    rec = row.scalar_one_or_none()
    if not rec:
        raise HTTPException(404, "call not found")

    contact_id = rec.crm_contact_id
    timeline_rows = await db.execute(text("""
        SELECT 'call'::text AS event_type,
               tr.id::text  AS event_id,
               tr.call_date AS occurred_at,
               tr.called_by AS actor,
               COALESCE(tr.call_outcome,'') || ' — ' || COALESCE(tr.notes,'') AS summary,
               jsonb_build_object('phone', tr.phone, 'duration', tr.call_duration_secs) AS meta
        FROM telecalling_records tr
        WHERE tr.crm_contact_id = :c AND tr.is_active = TRUE

        UNION ALL
        SELECT 'activity', a.id::text, a.activity_date, a.created_by,
               COALESCE(a.activity_type,'') || ' — ' || COALESCE(a.outcome,''),
               jsonb_build_object('notes', a.notes)
        FROM crm_activities a WHERE a.contact_id = :c

        UNION ALL
        SELECT 'whatsapp', w.id::text, COALESCE(w.sent_at, w.created_at), w.sent_by,
               COALESCE(w.message_text, w.message_type),
               jsonb_build_object('status', w.status, 'quote_id', w.crm_quote_id)
        FROM whatsapp_messages w
        WHERE (w.call_id IN (SELECT id FROM telecalling_records WHERE crm_contact_id = :c))
           OR (w.recipient_phone IN
               (SELECT phone FROM telecalling_records WHERE crm_contact_id = :c))

        ORDER BY occurred_at DESC LIMIT 25
    """), {"c": contact_id})
    return [dict(r) for r in timeline_rows.mappings()]


# ── /followups/today ────────────────────────────────────────────────────────

@router.get("/followups/today")
async def followups_today(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require(user, "tc.followup.view_own")
    rows = await db.execute(text("""
        SELECT source_id, agent_username, type, subject, phone,
               due_at, call_record_id, assignment_id
        FROM v_telecalling_reminders
        WHERE agent_username = :u
        ORDER BY due_at ASC
    """), {"u": user.username})
    return [dict(r) for r in rows.mappings()]


# ── /kpi/dashboard ──────────────────────────────────────────────────────────

@router.get("/kpi/dashboard")
async def kpi_dashboard(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    df = date_from or date.today()
    dt = date_to or date.today()
    rows = await db.execute(
        text("SELECT * FROM sp_telecalling_kpi(:u, :df, :dt)"),
        {"u": user.username, "df": df, "dt": dt},
    )
    r = rows.mappings().first() or {}
    return dict(r)


# ── /kpi/team — sales_manager rollup ────────────────────────────────────────

@router.get("/kpi/team")
async def kpi_team(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require(user, "tc.kpi.view_team")
    df = date_from or (date.today() - timedelta(days=7))
    dt = date_to or date.today()
    rows = await db.execute(
        text("SELECT * FROM sp_telecalling_team_kpi(:u, :df, :dt)"),
        {"u": user.username, "df": df, "dt": dt},
    )
    return [dict(r) for r in rows.mappings()]


# ── /lots/{lot_id}/skus — quick-capture dropdown ────────────────────────────

@router.get("/lots/{lot_id}/skus")
async def lot_skus(
    lot_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(text("""
        SELECT id AS lot_line_item_id, lot_id, brand, model, cpu,
               ram_gb, storage_gb, storage_type, grade,
               COALESCE(qty,0) AS available_qty
        FROM lot_line_items
        WHERE lot_id = :l
        ORDER BY brand, model
    """), {"l": lot_id})
    return [dict(r) for r in rows.mappings()]
