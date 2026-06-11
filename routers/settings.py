# routers/settings.py
"""App-wide company settings — admin only."""
from datetime import datetime
from utils.timezone import app_now, set_app_timezone
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from templates_config import templates
from database import get_db
from auth.dependencies import get_current_user, verify_csrf
from models.user import User, UserRole
from models.settings import AppSetting

router = APIRouter(prefix="/settings", tags=["settings"])

# (key, label, default_value)
SETTING_DEFS = [
    ("company_name",       "Company Name",        "OxyPC"),
    ("company_address",    "Address",             "Your Address Here, Delhi - 110001"),
    ("company_gstin",      "GSTIN",               "07XXXXX0000X1XX"),
    ("company_state",      "State",               "Delhi"),
    ("company_state_code", "State Code (2-digit)","07"),
    ("company_phone",      "Phone",               "+91-XXXXXXXXXX"),
    ("company_email",      "Email",               "info@oxypc.in"),
    ("app_timezone",       "Application Timezone", "Asia/Kolkata"),
]


async def get_company_settings(db: AsyncSession) -> dict:
    """Load company dict from DB; falls back to defaults for missing keys."""
    rows = (await db.execute(select(AppSetting))).scalars().all()
    stored = {r.key: r.value for r in rows if r.value}
    defaults = {k: d for k, _, d in SETTING_DEFS}
    merged = {**defaults, **stored}
    return {
        "name":       merged["company_name"],
        "address":    merged["company_address"],
        "gstin":      merged["company_gstin"],
        "state":      merged["company_state"],
        "state_code": merged["company_state_code"],
        "phone":      merged["company_phone"],
        "email":      merged["company_email"],
    }


@router.get("", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.admin:
        return RedirectResponse(url="/?error=Admin+only", status_code=302)
    rows = (await db.execute(select(AppSetting))).scalars().all()
    stored = {r.key: r.value for r in rows}
    return templates.TemplateResponse("admin/settings.html", {
        "request": request, "current_user": current_user,
        "setting_defs": SETTING_DEFS, "stored": stored,
    })


@router.post("")
async def save_settings(
    request: Request,
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.admin:
        return RedirectResponse(url="/?error=Admin+only", status_code=302)
    form = await request.form()
    for key, _, _ in SETTING_DEFS:
        value = (form.get(key) or "").strip()
        existing = await db.get(AppSetting, key)
        if existing:
            existing.value = value
            existing.updated_by = current_user.username
            existing.updated_at = app_now()
        else:
            db.add(AppSetting(key=key, value=value, updated_by=current_user.username))
    await db.commit()
    # Apply timezone change immediately to the running process
    tz_val = (form.get("app_timezone") or "Asia/Kolkata").strip()
    set_app_timezone(tz_val)
    return RedirectResponse(url="/settings?success=Settings+saved", status_code=302)
