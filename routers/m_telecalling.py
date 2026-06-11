"""
Mobile PWA shell routes (HTML) at /m/telecalling/*.
The HTML pages are thin — they bootstrap a Bootstrap-5 layout + a service
worker + JS that consumes /api/v1/telecalling/* JSON endpoints.

JSON traffic lives in routers/api_v1/telecalling.py. This module only renders
templates and gates them by RBAC.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates

from auth.dependencies import get_current_user, ROLE_PERMISSIONS
from models.user import User

router = APIRouter(prefix="/m/telecalling", tags=["mobile-telecalling"])
templates = Jinja2Templates(directory="templates")


def _can_access(user: User) -> bool:
    perms = ROLE_PERMISSIONS.get(user.role, [])
    return "*" in perms or "tc.call.create" in perms or "tc.call.view_own" in perms


def _ctx(request: Request, user: User, **kw) -> dict:
    return {"request": request, "user": user,
            "current_user": user, "page_class": "tc-mobile", **kw}


@router.get("", response_class=HTMLResponse)
async def mobile_dashboard(request: Request, user: User = Depends(get_current_user)):
    if not _can_access(user):
        return templates.TemplateResponse("error.html",
            {"request": request, "message": "Telecalling mobile access not granted"},
            status_code=403)
    return templates.TemplateResponse("m/telecalling/dashboard.html", _ctx(request, user))


@router.get("/queue", response_class=HTMLResponse)
async def mobile_queue(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse("m/telecalling/queue.html", _ctx(request, user))


@router.get("/call/{phone}", response_class=HTMLResponse)
async def mobile_call(phone: str, request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse("m/telecalling/call.html",
        _ctx(request, user, phone=phone))


@router.get("/followups", response_class=HTMLResponse)
async def mobile_followups(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse("m/telecalling/followups.html", _ctx(request, user))


@router.get("/inbox", response_class=HTMLResponse)
async def mobile_inbox(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse("m/telecalling/inbox.html", _ctx(request, user))


# Service worker MUST be served at the SCOPE root (or a parent) — serve at /sw.js
# from main.py too. Here we expose the manifest under the mobile sub-path for
# clarity; service worker registration is from /static/sw.js.
@router.get("/manifest.json")
async def manifest():
    return FileResponse("static/m/telecalling/manifest.json", media_type="application/manifest+json")
