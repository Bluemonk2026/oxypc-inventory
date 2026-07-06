"""Company Settings — admin-editable company details (name, address, GSTIN,
phone, email) used to auto-fill the "Company Detail" section of a Dealer
Quotation. Stored as AppSetting rows (key/value), same pattern as the Landing
Pages page-title cache."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from templates_config import templates
from database import get_db
from models.user import User, UserRole
from models.settings import AppSetting
from auth.dependencies import require_roles, verify_csrf

router = APIRouter(prefix="/admin/company-settings", tags=["company_settings"])
admin_only = require_roles(UserRole.admin)

SETTING_KEYS = ["company_name", "company_address", "company_gstin", "company_phone", "company_email"]


async def get_company_settings(db: AsyncSession) -> dict:
    """Fetch current Company Settings values (empty string default for any unset key)."""
    rows = (await db.execute(
        select(AppSetting).where(AppSetting.key.in_(SETTING_KEYS))
    )).scalars().all()
    values = {r.key: r.value or "" for r in rows}
    return {key: values.get(key, "") for key in SETTING_KEYS}


@router.get("", response_class=HTMLResponse)
async def company_settings_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    settings = await get_company_settings(db)
    return templates.TemplateResponse("admin/company_settings.html", {
        "request": request,
        "current_user": current_user,
        "settings": settings,
        "success": request.query_params.get("success"),
    })


@router.post("/save", dependencies=[Depends(verify_csrf)])
async def save_company_settings(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    form = await request.form()
    for key in SETTING_KEYS:
        value = (form.get(key) or "").strip()
        existing = (await db.execute(select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
        if existing:
            existing.value = value
            existing.updated_by = current_user.username
        else:
            db.add(AppSetting(key=key, value=value, description="Company Settings (Quotation autofill)",
                               updated_by=current_user.username))
    await db.commit()
    return RedirectResponse(url="/admin/company-settings?success=Company+Settings+saved", status_code=302)
