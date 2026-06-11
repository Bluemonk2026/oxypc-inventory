import secrets
import time
from templates_config import templates
from datetime import datetime, timedelta
from utils.timezone import app_now
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from database import get_db
from models.user import User, LoginLog
from auth.dependencies import verify_password, create_access_token, get_current_user, verify_csrf
from config import ACCESS_TOKEN_EXPIRE_MINUTES, COOKIE_SECURE
from limiter import limiter

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = None):
    # Pre-issue a csrf_token cookie so the login form CSRF check works before session exists
    csrf_tok = secrets.token_hex(32)
    resp = templates.TemplateResponse("login.html", {
        "request": request,
        "error": error,
        "login_csrf": csrf_tok,
    })
    resp.set_cookie("csrf_token", csrf_tok, httponly=False, samesite="strict", secure=COOKIE_SECURE)
    return resp


@router.post("/login")
@limiter.limit("5/minute")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    _csrf=Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    def _login_error_resp(request, error_msg):
        """Return login page with a fresh CSRF token on error (re-render for retry)."""
        tok = secrets.token_hex(32)
        resp = templates.TemplateResponse(
            "login.html", {"request": request, "error": error_msg, "login_csrf": tok}
        )
        resp.set_cookie("csrf_token", tok, httponly=False, samesite="strict", secure=COOKIE_SECURE)
        return resp

    if user:
        # Lockout: count failed attempts in the last LOCKOUT_MINUTES
        cutoff = app_now() - timedelta(minutes=LOCKOUT_MINUTES)
        fail_r = await db.execute(
            select(func.count(LoginLog.id)).where(
                LoginLog.user_id == user.id,
                LoginLog.action == "login_failed",
                LoginLog.timestamp >= cutoff,
            )
        )
        if (fail_r.scalar() or 0) >= MAX_FAILED_ATTEMPTS:
            return _login_error_resp(request,
                f"Account locked — too many failed attempts. "
                f"Try again in {LOCKOUT_MINUTES} minutes.")

    if not user or not verify_password(password, user.password_hash):
        # Log the failure against the real account (prevents FK violation; generic message
        # avoids user-enumeration via different error text)
        if user:
            db.add(LoginLog(user_id=user.id, action="login_failed",
                            ip_address=request.client.host))
            await db.commit()
        return _login_error_resp(request, "Invalid username or password")
    if not user.status:
        return _login_error_resp(request, "Account is disabled. Contact admin.")

    token = create_access_token({"sub": user.username, "role": user.role})

    await db.execute(
        update(User).where(User.id == user.id).values(last_login=app_now())
    )
    log = LoginLog(user_id=user.id, action="login", ip_address=request.client.host)
    db.add(log)
    await db.commit()

    csrf_tok = secrets.token_hex(32)
    response = RedirectResponse(url="/", status_code=302)
    _max_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    _expires_epoch = int(time.time()) + _max_age
    response.set_cookie("access_token", token, httponly=True, samesite="strict",
                        max_age=_max_age, secure=COOKIE_SECURE)
    response.set_cookie("csrf_token", csrf_tok, httponly=False, samesite="strict",
                        max_age=_max_age, secure=COOKIE_SECURE)
    # session_expires: non-httponly so JS can read it for the warning popup
    response.set_cookie("session_expires", str(_expires_epoch), httponly=False,
                        samesite="strict", max_age=_max_age, secure=COOKIE_SECURE)
    return response


@router.post("/logout")
async def logout(request: Request, _csrf=Depends(verify_csrf), db: AsyncSession = Depends(get_db)):
    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie("access_token")
    response.delete_cookie("csrf_token")
    return response


@router.get("/extend-session")
async def extend_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Re-issues JWT and session_expires cookies without a page reload.
    Called by the session warning popup's 'Stay Logged In' button via fetch().
    Returns JSON {ok: true} on success, 401 if the current token is expired/invalid.
    """
    from fastapi.responses import JSONResponse
    try:
        current_user = await get_current_user(request, db)
    except Exception:
        return JSONResponse({"ok": False, "reason": "session_expired"}, status_code=401)

    token = create_access_token({"sub": current_user.username, "role": current_user.role})
    csrf_tok = secrets.token_hex(32)
    _max_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    _expires_epoch = int(time.time()) + _max_age

    response = JSONResponse({"ok": True})
    response.set_cookie("access_token", token, httponly=True, samesite="strict", max_age=_max_age, secure=COOKIE_SECURE)
    response.set_cookie("csrf_token", csrf_tok, httponly=False, samesite="strict", max_age=_max_age, secure=COOKIE_SECURE)
    response.set_cookie("session_expires", str(_expires_epoch), httponly=False,
                        samesite="strict", max_age=_max_age, secure=COOKIE_SECURE)
    return response
