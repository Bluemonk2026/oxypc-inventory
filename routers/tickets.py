"""Ticket raising system — users log feedback, can see own tickets."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from templates_config import templates
from database import get_db
from auth.dependencies import get_current_user, verify_csrf
from models.user import User
from models.ticket import Ticket
from utils.timezone import app_now

router = APIRouter(
    prefix="/tickets",
    tags=["tickets"],
    dependencies=[Depends(verify_csrf)],
)


async def _next_ticket_id(db: AsyncSession) -> str:
    result = await db.execute(select(func.count(Ticket.id)))
    n = (result.scalar() or 0) + 1
    return str(10000000 + n)  # Always 8 digits, starts at 10000001


def _age_pill(raised_on) -> tuple[str, str]:
    """Return (label, bootstrap colour class) for ticket ageing."""
    if not raised_on:
        return "—", "secondary"
    now = app_now()
    days = max(0, (now - raised_on).days)
    if days == 0:
        return "Today", "success"
    if days <= 7:
        return f"{days}d", "info text-dark"
    if days <= 30:
        return f"{days}d", "warning text-dark"
    return f"{days}d", "danger"


def _ticket_ctx(t: Ticket) -> dict:
    age_label, age_cls = _age_pill(t.raised_on)
    return {
        "ticket_id":  t.ticket_id,
        "status":     t.status,
        "raised_on":  t.raised_on.strftime("%d-%m-%Y %H:%M") if t.raised_on else "—",
        "raised_by":  t.raised_by,
        "feedback":   t.feedback or "",
        "notes":      t.notes or "",
        "age_label":  age_label,
        "age_cls":    age_cls,
    }


# ── LIST ─────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def list_tickets(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Ticket)
        .where(Ticket.raised_by == current_user.username)
        .order_by(Ticket.raised_on.desc())
    )
    tickets = [_ticket_ctx(t) for t in result.scalars().all()]
    return templates.TemplateResponse("tickets/list.html", {
        "request": request,
        "tickets": tickets,
    })


# ── RAISE ────────────────────────────────────────────────────────────────────

@router.post("/raise")
async def raise_ticket(
    feedback: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not feedback.strip():
        return JSONResponse({"error": "Feedback cannot be empty."}, status_code=400)
    ticket = Ticket(
        ticket_id=await _next_ticket_id(db),
        raised_by=current_user.username,
        feedback=feedback.strip(),
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    return JSONResponse({"ok": True, "ticket_id": ticket.ticket_id})


# ── CLOSE ────────────────────────────────────────────────────────────────────

@router.post("/{ticket_id}/close")
async def close_ticket(
    ticket_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Ticket).where(
            Ticket.ticket_id == ticket_id,
            Ticket.raised_by == current_user.username,
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        return JSONResponse({"error": "Ticket not found."}, status_code=404)
    if ticket.status == "Closed":
        return JSONResponse({"error": "Already closed."}, status_code=400)
    ticket.status = "Closed"
    ticket.updated_at = app_now()
    await db.commit()
    return JSONResponse({"ok": True})
