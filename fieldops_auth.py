"""FieldOps authentication — entirely separate from the OxyPC session.

The app is reachable by anyone with the URL, so this is the only thing standing
between the public internet and the Reliance inventory. Deliberately boring:
bcrypt hashes, a signed cookie scoped to /fieldops, failed-attempt lockout, and
server-side checks on every request rather than trust in the client.

An OxyPC login grants nothing here, and a FieldOps login grants nothing in
OxyPC — the cookies have different names and different audiences.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import COOKIE_SECURE, SECRET_KEY
from fieldops_db import FieldOpsAudit, FieldOpsUser, configured, get_fieldops_db

ALGORITHM = "HS256"
COOKIE_NAME = "fieldops_session"
COOKIE_PATH = "/fieldops"
SESSION_HOURS = 12

# Brute-force limits, per account.
MAX_FAILED = 8
LOCKOUT_MINUTES = 15

# Audience claim keeps a FieldOps token from ever being accepted elsewhere,
# even though it is signed with the same key.
AUDIENCE = "fieldops"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_session_token(user: FieldOpsUser) -> str:
    payload = {
        "sub": user.username,
        "uid": user.id,
        "role": user.role,
        "aud": AUDIENCE,
        "iat": _now(),
        "exp": _now() + timedelta(hours=SESSION_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path=COOKIE_PATH,
        max_age=SESSION_HOURS * 3600,
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)


class NotAuthenticated(HTTPException):
    def __init__(self, detail: str = "Not signed in"):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


async def current_user_optional(
    request: Request, db: AsyncSession = Depends(get_fieldops_db)
) -> Optional[FieldOpsUser]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], audience=AUDIENCE)
    except JWTError:
        return None
    username = payload.get("sub")
    if not username:
        return None
    user = (
        await db.execute(select(FieldOpsUser).where(FieldOpsUser.username == username))
    ).scalar_one_or_none()
    if not user or user.status != "active" or not user.password_hash:
        return None
    return user


async def require_user(
    user: Optional[FieldOpsUser] = Depends(current_user_optional),
) -> FieldOpsUser:
    if not configured():
        raise HTTPException(
            status_code=503,
            detail="FieldOps is not configured on this server (FIELDOPS_DATABASE_URL).",
        )
    if user is None:
        raise NotAuthenticated()
    return user


async def require_admin(user: FieldOpsUser = Depends(require_user)) -> FieldOpsUser:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access is required for this action.",
        )
    return user


# ------------------------------------------------------------------ lockout
def is_locked(user: FieldOpsUser) -> bool:
    if not user.locked_until:
        return False
    locked_until = user.locked_until
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    return locked_until > _now()


def register_failure(user: FieldOpsUser) -> None:
    user.failed_logins = (user.failed_logins or 0) + 1
    if user.failed_logins >= MAX_FAILED:
        user.locked_until = _now() + timedelta(minutes=LOCKOUT_MINUTES)
        user.failed_logins = 0


def register_success(user: FieldOpsUser) -> None:
    user.failed_logins = 0
    user.locked_until = None
    user.last_login = _now()


def audit(db: AsyncSession, actor: Optional[str], action: str,
          target: str = "", detail: str = "", request: Optional[Request] = None) -> None:
    ip = None
    if request is not None:
        ip = (request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
              or (request.client.host if request.client else None))
    db.add(FieldOpsAudit(actor=actor, action=action, target=target, detail=detail, ip=ip))


# ------------------------------------------------- what each role may write
# Server-side authorisation for the shared store. The app enforces these in the
# UI too, but a device can post anything — this is where it actually counts.
WRITE_RULES = {
    "qc":         {"fe", "coord", "approver", "pmo", "admin"},
    "commercial": {"commercial", "approver", "pmo", "admin"},
    "asset":      {"fe", "coord", "approver", "packer", "warehouse", "pmo", "admin"},
    "package":    {"packer", "fe", "coord", "pmo", "admin"},
    "movement":   {"packer", "courier", "coord", "pmo", "admin"},
    "receipt":    {"warehouse", "pmo", "admin"},
    "site":       {"coord", "pmo", "spoc", "admin"},
    "user":       {"admin"},
    "deduction":  {"admin", "commercial"},
    "rate_card":  {"admin", "commercial"},
    "audit":      {"fe", "coord", "approver", "commercial", "packer", "courier",
                   "warehouse", "pmo", "spoc", "admin"},
}

# Only these roles may record a Reliance QC decision (BRD FR-011).
QC_DECISION_ROLES = {"approver", "admin"}

# Evidence is never destroyed — the app archives instead (BRD retention rule).
UNDELETABLE_KINDS = {"qc", "audit"}


def may_write(user: FieldOpsUser, kind: str) -> bool:
    return user.role in WRITE_RULES.get(kind, set())


def may_delete(user: FieldOpsUser, kind: str) -> bool:
    if kind in UNDELETABLE_KINDS:
        return False
    return user.role == "admin"
