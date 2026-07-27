"""CRM Dashboard router — its content (KPIs, funnels, follow-ups, Part
Sourcing table) moved to /procure-dashboard. This route now just redirects
there so existing links/bookmarks still land somewhere useful."""
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from auth.dependencies import get_current_user
from models.user import User

router = APIRouter(prefix="/crm", tags=["crm-dashboard"])


@router.get("/")
async def crm_dashboard(current_user: User = Depends(get_current_user)):
    return RedirectResponse(url="/procure-dashboard", status_code=303)
