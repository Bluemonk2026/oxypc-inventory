"""Company Settings — legacy helper module, kept only for its
get_company_settings() function (still imported by routers/dealers.py and
routers/dealer_quotations.py to auto-fill "Company Detail" on a Dealer
Quotation). The admin-facing page itself has been retired in favor of the
multi-company "/settings" page (routers/settings.py) — the two used to be
separate surfaces backed by separate data, which is what caused "added
company not showing" confusion. This module now reads from the same
`companies` table as /settings, using the first active company as the
single-company fallback these older callers expect."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models.user import User, UserRole
from models.company import Company
from auth.dependencies import require_roles

router = APIRouter(prefix="/admin/company-settings", tags=["company_settings"])
admin_only = require_roles(UserRole.admin)


async def get_company_settings(db: AsyncSession) -> dict:
    """Fetch the first active company's details (empty string default for any
    unset field) — same key names as before (company_name, company_address,
    company_gstin, company_phone, company_email) for template back-compat."""
    company = (await db.execute(
        select(Company).where(Company.is_active == True).order_by(Company.created_at)
    )).scalars().first()
    if not company:
        return {"company_name": "", "company_address": "", "company_gstin": "",
                "company_phone": "", "company_email": ""}
    return {
        "company_name": company.company_name or "",
        "company_address": company.company_address or "",
        "company_gstin": company.company_gstin or "",
        "company_phone": company.company_phone or "",
        "company_email": company.company_email or "",
    }


@router.get("")
async def company_settings_redirect(request: Request, current_user: User = Depends(admin_only)):
    return RedirectResponse(url="/settings", status_code=302)
