"""Terms & Conditions admin — reusable payment/delivery/disclaimer policies,
embedded into generated Purchase Order documents."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from templates_config import templates
from database import get_db
from models.user import User, UserRole
from models.terms import TermsCondition, TERM_TYPES, TERM_TYPE_LABELS
from auth.dependencies import require_roles, verify_csrf

router = APIRouter(prefix="/admin/terms-conditions", tags=["terms_conditions"],
                   dependencies=[Depends(verify_csrf)])
admin_only = require_roles(UserRole.admin)


async def get_active_terms(db: AsyncSession, term_type: str) -> list[TermsCondition]:
    """All active policies of a type, ordered — used when generating PO documents."""
    return (await db.execute(
        select(TermsCondition)
        .where(TermsCondition.term_type == term_type, TermsCondition.is_active == True)
        .order_by(TermsCondition.display_order, TermsCondition.created_at)
    )).scalars().all()


@router.get("", response_class=HTMLResponse)
async def list_terms(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    rows = (await db.execute(
        select(TermsCondition).order_by(
            TermsCondition.term_type, TermsCondition.display_order, TermsCondition.created_at
        )
    )).scalars().all()
    grouped: dict = {t: [] for t, _ in TERM_TYPES}
    for r in rows:
        grouped.setdefault(r.term_type, []).append(r)
    return templates.TemplateResponse("admin/terms_conditions.html", {
        "request": request, "current_user": current_user,
        "grouped": grouped, "term_types": TERM_TYPES, "term_labels": TERM_TYPE_LABELS,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@router.post("/add")
async def add_term(
    request: Request,
    term_type: str = Form(...),
    title: str = Form(...),
    content: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    if term_type not in TERM_TYPE_LABELS:
        return RedirectResponse(url="/admin/terms-conditions?error=Invalid+policy+type", status_code=302)
    if not title.strip() or not content.strip():
        return RedirectResponse(url="/admin/terms-conditions?error=Title+and+content+required", status_code=302)
    db.add(TermsCondition(
        term_type=term_type, title=title.strip(), content=content.strip(),
        created_by=current_user.username,
    ))
    await db.commit()
    return RedirectResponse(url="/admin/terms-conditions?success=Policy+added", status_code=302)


@router.post("/{term_id}/edit")
async def edit_term(
    term_id: str,
    title: str = Form(...),
    content: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    row = (await db.execute(select(TermsCondition).where(TermsCondition.id == term_id))).scalar_one_or_none()
    if row:
        row.title = title.strip()
        row.content = content.strip()
        await db.commit()
    return RedirectResponse(url="/admin/terms-conditions?success=Policy+updated", status_code=302)


@router.post("/{term_id}/toggle")
async def toggle_term(
    term_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    row = (await db.execute(select(TermsCondition).where(TermsCondition.id == term_id))).scalar_one_or_none()
    if row:
        row.is_active = not row.is_active
        await db.commit()
    return RedirectResponse(url="/admin/terms-conditions?success=Status+updated", status_code=302)


@router.post("/{term_id}/delete")
async def delete_term(
    term_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    row = (await db.execute(select(TermsCondition).where(TermsCondition.id == term_id))).scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()
    return RedirectResponse(url="/admin/terms-conditions?success=Policy+deleted", status_code=302)
