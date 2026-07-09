"""Trade Partner portal authentication — completely separate from staff auth.

Dealers authenticate with portal_phone + password and receive a `partner_token`
httponly JWT cookie. A partner JWT can never open internal routes (different
cookie name + a `typ: partner` claim) and staff JWTs can never open /partner
routes. CSRF uses a parallel double-submit cookie `partner_csrf_token`.
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models.dealers import Dealer
from config import SECRET_KEY

ALGORITHM = "HS256"
PARTNER_TOKEN_COOKIE = "partner_token"
PARTNER_CSRF_COOKIE = "partner_csrf_token"
PARTNER_SESSION_MINUTES = 12 * 60  # dealers stay logged in for a working day


def create_partner_token(dealer: Dealer) -> str:
    payload = {
        "typ": "partner",
        "sub": str(dealer.id),
        "pv": dealer.portal_password_version or 1,  # bump on password reset → old tokens die
        "exp": datetime.utcnow() + timedelta(minutes=PARTNER_SESSION_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def new_partner_csrf() -> str:
    return secrets.token_hex(32)


def _login_redirect() -> HTTPException:
    return HTTPException(status_code=302, headers={"Location": "/partner/login"})


async def get_current_partner(request: Request, db: AsyncSession = Depends(get_db)) -> Dealer:
    """Resolve the logged-in dealer. Redirects to /partner/login on any failure.

    Re-checks portal_enabled + status on every request so a disabled dealer is
    cut off immediately, and pv (password version) so admin resets kill live JWTs.
    """
    token = request.cookies.get(PARTNER_TOKEN_COOKIE)
    if not token:
        raise _login_redirect()
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("typ") != "partner":
            raise _login_redirect()
        dealer_id = payload.get("sub")
        if not dealer_id:
            raise _login_redirect()
    except JWTError:
        raise _login_redirect()

    result = await db.execute(select(Dealer).where(Dealer.id == dealer_id))
    dealer = result.scalar_one_or_none()
    if (
        not dealer
        or not dealer.portal_enabled
        or dealer.status != "active"
        or (dealer.portal_password_version or 1) != payload.get("pv")
    ):
        raise _login_redirect()
    return dealer


async def verify_partner_csrf(request: Request) -> None:
    """Double-submit CSRF for dealer-portal mutating requests (mirrors verify_csrf)."""
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return
    cookie_token = request.cookies.get(PARTNER_CSRF_COOKIE, "")
    if not cookie_token:
        raise _login_redirect()
    try:
        form = await request.form()
        form_token = form.get("csrf_token", "")
    except Exception:
        form_token = ""
    if not form_token:
        form_token = request.headers.get("X-CSRF-Token", "")
    if not form_token or form_token != cookie_token:
        raise _login_redirect()


def normalize_phone(raw: str) -> str:
    """Normalize an Indian mobile number to its last 10 digits for login matching."""
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits
