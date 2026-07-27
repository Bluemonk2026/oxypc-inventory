# routers/settings.py
"""Company Setting — admin can define multiple company profiles, each usable
as the "Company Details" on Quote/PO generation (Account, Buyer Deal, Supplier
Deal detail pages). Application Timezone used to live on this page — it now
lives on Attendance Config (routers/attendance_group_config.py) only."""
import uuid
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from templates_config import templates
from database import get_db
from auth.dependencies import get_current_user, verify_csrf
from models.user import User, UserRole
from models.company import Company

router = APIRouter(prefix="/settings", tags=["settings"])


async def get_company_settings(db: AsyncSession, company_id: str = None) -> dict:
    """Load a company profile dict. If company_id is given, fetch that row;
    otherwise fall back to the first active company (back-compat for any
    caller that hasn't been updated to pass a specific company_id yet)."""
    company = None
    if company_id:
        try:
            company = await db.get(Company, uuid.UUID(company_id))
        except (ValueError, TypeError):
            company = None
    if not company:
        company = (await db.execute(
            select(Company).where(Company.is_active == True).order_by(Company.created_at)
        )).scalars().first()
    if not company:
        return {"name": "", "address": "", "gstin": "", "state": "", "state_code": "", "phone": "", "email": ""}
    return {
        "name": company.company_name or "",
        "address": company.company_address or "",
        "gstin": company.company_gstin or "",
        "state": company.company_state or "",
        "state_code": company.company_state_code or "",
        "phone": company.company_phone or "",
        "email": company.company_email or "",
    }


@router.get("", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.admin:
        return RedirectResponse(url="/?error=Admin+only", status_code=302)
    companies = (await db.execute(
        select(Company).where(Company.is_active == True).order_by(Company.created_at.desc())
    )).scalars().all()

    edit_company = None
    edit_id = request.query_params.get("edit")
    if edit_id:
        try:
            edit_company = await db.get(Company, uuid.UUID(edit_id))
        except (ValueError, TypeError):
            edit_company = None

    return templates.TemplateResponse("admin/settings.html", {
        "request": request, "current_user": current_user,
        "companies": companies, "edit_company": edit_company,
        "success": request.query_params.get("success"),
    })


@router.post("")
async def save_company(
    request: Request,
    _csrf: None = Depends(verify_csrf),
    company_id: str = Form(""),
    company_name: str = Form(...),
    company_address: str = Form(""),
    company_gstin: str = Form(""),
    company_state: str = Form(""),
    company_state_code: str = Form(""),
    company_phone: str = Form(""),
    company_email: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.admin:
        return RedirectResponse(url="/?error=Admin+only", status_code=302)

    company = None
    if company_id.strip():
        try:
            company = await db.get(Company, uuid.UUID(company_id.strip()))
        except (ValueError, TypeError):
            company = None
        if not company:
            raise HTTPException(404, "Company not found")

    if company:
        company.company_name = company_name.strip()
        company.company_address = company_address.strip() or None
        company.company_gstin = company_gstin.strip() or None
        company.company_state = company_state.strip() or None
        company.company_state_code = company_state_code.strip() or None
        company.company_phone = company_phone.strip() or None
        company.company_email = company_email.strip() or None
        msg = "Company+updated"
    else:
        company = Company(
            company_name=company_name.strip(),
            company_address=company_address.strip() or None,
            company_gstin=company_gstin.strip() or None,
            company_state=company_state.strip() or None,
            company_state_code=company_state_code.strip() or None,
            company_phone=company_phone.strip() or None,
            company_email=company_email.strip() or None,
            created_by=current_user.username,
        )
        db.add(company)
        msg = "Company+added"

    await db.commit()
    return RedirectResponse(url=f"/settings?success={msg}", status_code=302)


@router.post("/{company_id}/delete")
async def delete_company(
    company_id: str,
    request: Request,
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.admin:
        return RedirectResponse(url="/?error=Admin+only", status_code=302)
    try:
        cid = uuid.UUID(company_id)
    except ValueError:
        raise HTTPException(404, "Company not found")
    company = await db.get(Company, cid)
    if not company:
        raise HTTPException(404, "Company not found")
    company.is_active = False
    await db.commit()
    return RedirectResponse(url="/settings?success=Company+removed", status_code=302)
