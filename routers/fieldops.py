"""Reliance Asset FieldOps — a standalone app hosted inside the OxyPC process.

Shares the domain and the deployment; shares nothing else. Its own login, its
own users, its own database (FIELDOPS_DATABASE_URL), its own audit. An OxyPC
session grants no access here, and this app appears nowhere in the OxyPC menu.

Anyone may reach /fieldops/login. Everything past it — the app shell, the
inventory master, the sync API — requires a FieldOps session, because the data
behind it is Reliance's confidential site, price and cost information.

Authorisation is enforced here rather than in the browser: a device can post
anything, so role rules on what may be written live on this side of the wire.
"""

import json
import os
from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import hash_password_async, verify_password_async
from fieldops_auth import (
    COOKIE_NAME, QC_DECISION_ROLES, audit, clear_session_cookie, create_session_token,
    current_user_optional, is_locked, may_delete, may_write, register_failure,
    register_success, require_admin, require_user, set_session_cookie,
)
from fieldops_db import (
    FieldOpsAudit, FieldOpsRecord, FieldOpsUser, configured, get_fieldops_db,
)
from limiter import ip_key_func, limiter
from utils.timezone import app_now

router = APIRouter(tags=["fieldops"])

BASE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fieldops_app"
)

SYNC_KINDS = {
    "qc", "commercial", "package", "movement", "receipt",
    "asset", "site", "user", "deduction", "rate_card", "audit",
}
PULL_OVERLAP = timedelta(seconds=5)
MAX_CHANGES_PER_PUSH = 500
MAX_PULL_RECORDS = 2000

_MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".webmanifest": "application/manifest+json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".md": "text/markdown; charset=utf-8",
}
_NO_CACHE = {".html", ".webmanifest", ".js", ".css", ".md"}


# ============================================================ file serving
def _resolve(rel_path: str) -> str:
    full = os.path.normpath(os.path.join(BASE_DIR, rel_path))
    base = os.path.normpath(BASE_DIR)
    if not (full == base or full.startswith(base + os.sep)):
        raise HTTPException(status_code=404, detail="Not found")
    if not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="Not found")
    return full


def _serve(full_path: str) -> FileResponse:
    ext = os.path.splitext(full_path)[1].lower()
    name = os.path.basename(full_path)
    headers = {"Cache-Control": "no-cache" if (ext in _NO_CACHE or name == "sw.js")
               else "public, max-age=3600"}
    if name == "sw.js":
        headers["Service-Worker-Allowed"] = "/fieldops/"
    return FileResponse(full_path, media_type=_MEDIA_TYPES.get(ext, "application/octet-stream"),
                        headers=headers)


# ============================================================ login page
LOGIN_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Sign in · Reliance Asset FieldOps</title>
<link rel="icon" href="/fieldops/icons/icon.svg" type="image/svg+xml">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{min-height:100vh;display:flex;align-items:flex-start;justify-content:center;
 background:linear-gradient(160deg,#17365D 52%,#1B6CA8);padding:44px 18px;
 font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;color:#1F2937}
.wrap{width:100%;max-width:420px;display:flex;flex-direction:column;align-items:center}
.logo{width:70px;height:70px;border-radius:20px;background:#fff;display:flex;align-items:center;
 justify-content:center;font-size:33px;margin-bottom:14px;box-shadow:0 6px 24px rgba(0,0,0,.3)}
h1{color:#fff;font-size:23px;font-weight:800}
.sub{color:#B8C9E2;font-size:12px;margin:4px 0 30px;text-align:center}
.card{background:#fff;border-radius:16px;padding:22px 18px;width:100%;box-shadow:0 10px 34px rgba(0,0,0,.28)}
label{font-size:12px;color:#6B7280;font-weight:700;display:block;margin-bottom:4px}
input{width:100%;padding:12px 13px;border-radius:10px;border:1.5px solid #D8DEE9;font-size:16px;
 outline:none;margin-bottom:14px;min-height:46px}
input:focus{border-color:#2E5FAC}
button{width:100%;padding:13px;border:none;border-radius:10px;background:#17365D;color:#fff;
 font-size:15px;font-weight:700;cursor:pointer;min-height:48px}
button:disabled{opacity:.6;cursor:not-allowed}
.err{background:#FDECEC;border:1px solid #F0B9B9;color:#C62828;padding:10px 12px;border-radius:10px;
 font-size:12px;font-weight:600;margin-bottom:12px;display:none}
.foot{color:#8FA6C4;font-size:11px;text-align:center;margin-top:22px;line-height:1.6}
</style></head><body>
<div class="wrap">
  <div class="logo">📦</div>
  <h1>FieldOps</h1>
  <div class="sub">Reliance Asset QC &amp; Logistics Portal</div>
  <form class="card" id="f" autocomplete="on">
    <div class="err" id="e"></div>
    <label for="u">Username</label>
    <input id="u" name="username" autocapitalize="none" autocorrect="off" required autofocus>
    <label for="p">Password</label>
    <input id="p" name="password" type="password" required>
    <button id="b" type="submit">Sign in</button>
  </form>
  <div class="foot">Access is issued by your administrator.<br>
    Reliance Asset Recovery · 3,957 units · 622 locations</div>
</div>
<script>
var f=document.getElementById('f'),e=document.getElementById('e'),b=document.getElementById('b');
f.addEventListener('submit',function(ev){
  ev.preventDefault(); e.style.display='none'; b.disabled=true; b.textContent='Signing in…';
  fetch('/fieldops/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
    credentials:'same-origin',
    body:JSON.stringify({username:document.getElementById('u').value,
                         password:document.getElementById('p').value})})
  .then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})
  .then(function(o){
    if(o.ok){ location.href = o.j.must_change_password ? '/fieldops/#/profile' : '/fieldops/'; return; }
    e.textContent = o.j.detail || 'Sign in failed.'; e.style.display='block';
    b.disabled=false; b.textContent='Sign in';
  })
  .catch(function(){ e.textContent='Cannot reach the server.'; e.style.display='block';
    b.disabled=false; b.textContent='Sign in'; });
});
</script></body></html>"""


@router.get("/fieldops/login", response_class=HTMLResponse)
async def fieldops_login_page(user=Depends(current_user_optional)):
    if not configured():
        return HTMLResponse(
            "<h2 style='font-family:sans-serif;padding:40px'>FieldOps is not configured "
            "on this server.</h2><p style='font-family:sans-serif;padding:0 40px'>"
            "Set <code>FIELDOPS_DATABASE_URL</code> and restart.</p>", status_code=503)
    if user is not None:
        return RedirectResponse(url="/fieldops/", status_code=302)
    return HTMLResponse(LOGIN_PAGE, headers={"Cache-Control": "no-cache"})


# ============================================================ first-run setup
# Bootstrapping without server access: the very first FieldOps administrator is
# created from the browser, by someone who is already an OxyPC administrator.
# The password is generated here, shown exactly once, and must be replaced at
# first sign-in. Once an administrator exists this route is closed for good —
# it is the only place FieldOps ever looks at an OxyPC session.
import secrets
import string

_PW_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*-_=+?"


def _one_time_password(length: int = 20) -> str:
    return "".join(secrets.choice(_PW_ALPHABET) for _ in range(length))


async def _oxypc_admin(request: Request) -> Optional[str]:
    """Username of the signed-in OxyPC administrator, or None."""
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        from jose import jwt as _jwt

        from config import SECRET_KEY as _SK
        payload = _jwt.decode(token, _SK, algorithms=["HS256"])
    except Exception:      # noqa: BLE001 — any decode failure is simply "not signed in"
        return None
    username = payload.get("sub")
    if not username:
        return None
    try:
        from database import AsyncSessionLocal
        from models.user import User as OxyUser

        async with AsyncSessionLocal() as oxydb:
            row = (await oxydb.execute(
                select(OxyUser).where(OxyUser.username == username)
            )).scalar_one_or_none()
    except Exception:      # noqa: BLE001
        return None
    if row is None or not getattr(row, "status", True):
        return None
    role = getattr(getattr(row, "role", None), "value", None) or str(getattr(row, "role", ""))
    return username if role == "admin" else None


async def _admin_exists(db: AsyncSession) -> bool:
    count = (await db.execute(
        select(func.count(FieldOpsUser.id)).where(FieldOpsUser.role == "admin")
    )).scalar() or 0
    return count > 0


_SETUP_SHELL = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Set up FieldOps</title><style>
*{box-sizing:border-box;margin:0;padding:0}
body{min-height:100vh;display:flex;align-items:flex-start;justify-content:center;
 background:linear-gradient(160deg,#17365D 52%%,#1B6CA8);padding:44px 18px;
 font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;color:#1F2937}
.wrap{width:100%%;max-width:520px}
.card{background:#fff;border-radius:16px;padding:24px 20px;box-shadow:0 10px 34px rgba(0,0,0,.28)}
h1{font-size:20px;color:#17365D;margin-bottom:6px}
p{font-size:13px;color:#4B5563;line-height:1.55;margin-bottom:12px}
button{width:100%%;padding:13px;border:none;border-radius:10px;background:#17365D;color:#fff;
 font-size:15px;font-weight:700;cursor:pointer;min-height:48px}
.cred{background:#F0F4FA;border:1.5px solid #C3D6F0;border-radius:10px;padding:14px;margin:14px 0}
.cred .k{font-size:11px;color:#6B7280;text-transform:uppercase;letter-spacing:.5px;font-weight:700}
.cred .v{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:18px;font-weight:700;
 color:#17365D;word-break:break-all;margin-top:2px}
.warn{background:#FFF8E7;border:1px solid #F5D48A;border-radius:10px;padding:12px;font-size:12px;
 color:#7A5B00;margin-bottom:12px}
.err{background:#FDECEC;border:1px solid #F0B9B9;color:#C62828;padding:12px;border-radius:10px;font-size:13px}
a.go{display:block;text-align:center;margin-top:14px;color:#2E5FAC;font-weight:700;font-size:14px;
 text-decoration:none}
</style></head><body><div class="wrap"><div class="card">%s</div></div></body></html>"""


@router.get("/fieldops/setup", response_class=HTMLResponse)
async def fieldops_setup_page(request: Request, db: AsyncSession = Depends(get_fieldops_db)):
    if not configured():
        raise HTTPException(status_code=503, detail="FieldOps has no database configured.")
    if await _admin_exists(db):
        raise HTTPException(status_code=404, detail="Not found")

    who = await _oxypc_admin(request)
    if not who:
        return HTMLResponse(_SETUP_SHELL % (
            "<h1>Set up FieldOps</h1>"
            "<p>No FieldOps administrator exists yet. To create the first one, open this page "
            "while signed in to OxyPC as an administrator — that is the only proof of ownership "
            "available before any FieldOps account exists.</p>"
            "<div class='err'>Not signed in to OxyPC as an administrator.</div>"
            "<a class='go' href='/auth/login'>Sign in to OxyPC first →</a>"), status_code=403)

    return HTMLResponse(_SETUP_SHELL % (
        "<h1>Set up FieldOps</h1>"
        f"<p>Signed in to OxyPC as <b>{who}</b>. This creates the first FieldOps administrator "
        "and issues a one-time password.</p>"
        "<div class='warn'>The password is shown once and never again. It must be changed at "
        "first sign-in, and this page closes permanently afterwards.</div>"
        "<form method='post' action='/fieldops/api/setup'>"
        "<button type='submit'>Create the administrator</button></form>"))


@router.post("/fieldops/api/setup", response_class=HTMLResponse)
@limiter.limit("5/minute", key_func=ip_key_func)
async def fieldops_setup_create(request: Request, db: AsyncSession = Depends(get_fieldops_db)):
    if not configured():
        raise HTTPException(status_code=503, detail="FieldOps has no database configured.")
    if await _admin_exists(db):
        raise HTTPException(status_code=404, detail="Not found")

    who = await _oxypc_admin(request)
    if not who:
        raise HTTPException(status_code=403, detail="Sign in to OxyPC as an administrator first.")

    password = _one_time_password()
    admin = FieldOpsUser(
        id="U00",
        username="admin",
        name="System Administrator",
        password_hash=await hash_password_async(password),
        must_change_password=True,      # single use — replaced at first sign-in
        role="admin",
        region="All",
        sites=[],
        perms={"allow": [], "deny": []},
        status="active",
        created_by=f"setup by OxyPC:{who}",
    )
    db.add(admin)
    audit(db, who, "admin_created", target="admin",
          detail="first-run setup; one-time password issued", request=request)
    await db.commit()

    return HTMLResponse(_SETUP_SHELL % (
        "<h1>Administrator created</h1>"
        "<div class='warn'>Copy this now — it is not shown again and it works only once.</div>"
        "<div class='cred'><div class='k'>Username</div><div class='v'>admin</div></div>"
        f"<div class='cred'><div class='k'>One-time password</div><div class='v'>{password}</div></div>"
        "<p>Sign in with it and you will be asked immediately to choose your own password. "
        "After that this setup page is closed for good.</p>"
        "<a class='go' href='/fieldops/login'>Go to the FieldOps sign-in →</a>"))


# ============================================================ auth API
class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/fieldops/api/auth/login")
@limiter.limit("20/minute", key_func=ip_key_func)
async def fieldops_login(
    request: Request,
    body: LoginBody = Body(...),
    db: AsyncSession = Depends(get_fieldops_db),
):
    if not configured():
        raise HTTPException(status_code=503, detail="FieldOps is not configured on this server.")

    username = (body.username or "").strip()
    user = (
        await db.execute(select(FieldOpsUser).where(func.lower(FieldOpsUser.username) == username.lower()))
    ).scalar_one_or_none()

    # One message for every failure — never reveal whether an account exists.
    invalid = HTTPException(status_code=401, detail="Incorrect username or password.")

    async def refuse(exc: HTTPException, action: str, detail: str):
        """Record the attempt and commit before raising.

        The session dependency rolls back on an exception, so anything written
        on a failure path is lost unless it is committed first — which would
        silently discard both the audit trail of failed sign-ins and the
        failed-attempt counter the lockout depends on.
        """
        audit(db, username, action, detail=detail, request=request)
        await db.commit()
        raise exc

    if user is None:
        await verify_password_async(body.password or "", "$2b$12$" + "x" * 53)  # constant-ish work
        await refuse(invalid, "login_failed", "no such account")
    if is_locked(user):
        await refuse(
            HTTPException(status_code=429,
                          detail="Too many failed attempts. Try again in a few minutes."),
            "login_blocked", "account locked")
    if user.status != "active":
        await refuse(HTTPException(status_code=403, detail="This account is inactive."),
                     "login_failed", "account inactive")
    if not user.password_hash:
        await refuse(
            HTTPException(status_code=403,
                          detail="No password has been set for this account. Ask your administrator."),
            "login_failed", "no password set")
    if not await verify_password_async(body.password or "", user.password_hash):
        register_failure(user)
        await refuse(invalid, "login_failed",
                     f"wrong password (failures={user.failed_logins})")

    register_success(user)
    audit(db, username, "login", detail=f"role={user.role}", request=request)
    token = create_session_token(user)
    payload = {"ok": True, "user": user.to_dict(),
               "must_change_password": bool(user.must_change_password)}
    response = JSONResponse(payload)
    set_session_cookie(response, token)
    return response


@router.post("/fieldops/api/auth/logout")
async def fieldops_logout(request: Request, db: AsyncSession = Depends(get_fieldops_db),
                          user=Depends(current_user_optional)):
    if user:
        audit(db, user.username, "logout", request=request)
    response = JSONResponse({"ok": True})
    clear_session_cookie(response)
    return response


@router.get("/fieldops/api/me")
async def fieldops_me(user: FieldOpsUser = Depends(require_user)):
    return {"user": user.to_dict()}


class PasswordBody(BaseModel):
    current_password: Optional[str] = None
    new_password: str


@router.post("/fieldops/api/auth/password")
async def fieldops_change_password(
    request: Request,
    body: PasswordBody = Body(...),
    db: AsyncSession = Depends(get_fieldops_db),
    user: FieldOpsUser = Depends(require_user),
):
    """Change your own password. Requires the current one unless an admin has
    just reset it and flagged the account for a forced change."""
    if len(body.new_password or "") < 8:
        raise HTTPException(status_code=400, detail="Choose a password of at least 8 characters.")
    if not user.must_change_password:
        if not body.current_password or not await verify_password_async(
            body.current_password, user.password_hash or ""
        ):
            raise HTTPException(status_code=400, detail="Current password is incorrect.")
    user.password_hash = await hash_password_async(body.new_password)
    user.must_change_password = False
    audit(db, user.username, "password_changed", target=user.username, request=request)
    return {"ok": True}


# ============================================================ admin: users
class UserBody(BaseModel):
    id: Optional[str] = None
    username: str
    name: str
    role: str
    region: str = "All"
    sites: List[str] = Field(default_factory=list)
    allow: List[str] = Field(default_factory=list)
    deny: List[str] = Field(default_factory=list)
    status: str = "active"
    password: Optional[str] = None


VALID_ROLES = {"fe", "coord", "pmo", "spoc", "approver", "commercial",
               "packer", "courier", "warehouse", "admin"}


@router.get("/fieldops/api/admin/users")
async def list_users(db: AsyncSession = Depends(get_fieldops_db),
                     admin: FieldOpsUser = Depends(require_admin)):
    rows = (await db.execute(select(FieldOpsUser).order_by(FieldOpsUser.id))).scalars().all()
    return {"users": [u.to_dict() for u in rows]}


@router.post("/fieldops/api/admin/users")
async def save_user(
    request: Request,
    body: UserBody = Body(...),
    db: AsyncSession = Depends(get_fieldops_db),
    admin: FieldOpsUser = Depends(require_admin),
):
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Unknown role '{body.role}'.")
    username = (body.username or "").strip()
    if not username or not (body.name or "").strip():
        raise HTTPException(status_code=400, detail="Name and username are both required.")

    clash = (
        await db.execute(select(FieldOpsUser).where(func.lower(FieldOpsUser.username) == username.lower()))
    ).scalar_one_or_none()

    user = None
    if body.id:
        user = await db.get(FieldOpsUser, body.id)
    if clash and (user is None or clash.id != user.id):
        raise HTTPException(status_code=400, detail=f"Username '{username}' is already in use.")

    created = False
    if user is None:
        existing_ids = {u.id for u in (await db.execute(select(FieldOpsUser))).scalars().all()}
        n = 1
        while f"U{n:02d}" in existing_ids:
            n += 1
        user = FieldOpsUser(id=f"U{n:02d}", created_by=admin.username)
        db.add(user)
        created = True

    if user.role == "admin" and body.role != "admin":
        remaining = (await db.execute(
            select(func.count(FieldOpsUser.id)).where(
                FieldOpsUser.role == "admin", FieldOpsUser.status == "active",
                FieldOpsUser.id != user.id)
        )).scalar() or 0
        if remaining == 0:
            raise HTTPException(status_code=400, detail="At least one active administrator must remain.")

    user.username = username
    user.name = body.name.strip()
    user.role = body.role
    user.region = body.region or "All"
    user.sites = list(body.sites or [])
    user.perms = {"allow": list(body.allow or []), "deny": list(body.deny or [])}
    user.status = body.status if body.status in ("active", "inactive") else "active"

    if body.password:
        if len(body.password) < 8:
            raise HTTPException(status_code=400, detail="Choose a password of at least 8 characters.")
        user.password_hash = await hash_password_async(body.password)
        user.must_change_password = True

    audit(db, admin.username, "user_created" if created else "user_updated",
          target=user.username, detail=f"role={user.role} sites={len(user.sites)}", request=request)
    await db.flush()
    return {"ok": True, "user": user.to_dict()}


class ResetBody(BaseModel):
    user_id: str
    new_password: str


@router.post("/fieldops/api/admin/users/reset-password")
async def reset_password(
    request: Request,
    body: ResetBody = Body(...),
    db: AsyncSession = Depends(get_fieldops_db),
    admin: FieldOpsUser = Depends(require_admin),
):
    user = await db.get(FieldOpsUser, body.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if len(body.new_password or "") < 8:
        raise HTTPException(status_code=400, detail="Choose a password of at least 8 characters.")
    user.password_hash = await hash_password_async(body.new_password)
    user.must_change_password = True
    user.failed_logins = 0
    user.locked_until = None
    audit(db, admin.username, "password_reset", target=user.username, request=request)
    return {"ok": True, "user": user.to_dict()}


@router.delete("/fieldops/api/admin/users/{user_id}")
async def delete_user(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_fieldops_db),
    admin: FieldOpsUser = Depends(require_admin),
):
    user = await db.get(FieldOpsUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot delete the account you are signed in with.")
    if user.role == "admin":
        remaining = (await db.execute(
            select(func.count(FieldOpsUser.id)).where(
                FieldOpsUser.role == "admin", FieldOpsUser.status == "active",
                FieldOpsUser.id != user.id)
        )).scalar() or 0
        if remaining == 0:
            raise HTTPException(status_code=400, detail="At least one active administrator must remain.")
    await db.delete(user)
    audit(db, admin.username, "user_deleted", target=user.username, request=request)
    return {"ok": True}


# ============================================================ admin: data
@router.get("/fieldops/api/admin/export")
async def export_all(db: AsyncSession = Depends(get_fieldops_db),
                     admin: FieldOpsUser = Depends(require_admin)):
    """Everything in the shared store, as one JSON document."""
    records = (await db.execute(select(FieldOpsRecord))).scalars().all()
    users = (await db.execute(select(FieldOpsUser).order_by(FieldOpsUser.id))).scalars().all()
    return {
        "exported_at": app_now().isoformat(),
        "exported_by": admin.username,
        "users": [u.to_dict() for u in users],          # never includes hashes
        "records": [
            {"kind": r.kind, "id": r.rec_id, "data": r.data, "deleted": r.deleted,
             "updated_at": r.updated_at.isoformat() if r.updated_at else None,
             "updated_by": r.updated_by}
            for r in records
        ],
    }


class ImportBody(BaseModel):
    records: List[Dict[str, Any]] = Field(default_factory=list)
    replace: bool = False


@router.post("/fieldops/api/admin/import")
async def import_all(
    request: Request,
    body: ImportBody = Body(...),
    db: AsyncSession = Depends(get_fieldops_db),
    admin: FieldOpsUser = Depends(require_admin),
):
    """Load records into the shared store. Additive by default; `replace` clears
    the store first (users and their passwords are never touched)."""
    if body.replace:
        existing = (await db.execute(select(FieldOpsRecord))).scalars().all()
        for row in existing:
            await db.delete(row)
        await db.flush()

    now = app_now()
    loaded, skipped = 0, 0
    for rec in body.records:
        kind, rec_id = rec.get("kind"), str(rec.get("id") or "")
        if kind not in SYNC_KINDS or not rec_id:
            skipped += 1
            continue
        key = f"{kind}:{rec_id}"
        row = await db.get(FieldOpsRecord, key)
        if row is None:
            row = FieldOpsRecord(id=key, kind=kind, rec_id=rec_id)
            db.add(row)
        row.data = rec.get("data") or {}
        row.deleted = bool(rec.get("deleted"))
        row.updated_at = now
        row.updated_by = f"{admin.username} (import)"
        row.device_updated_at = rec.get("updated_at")
        loaded += 1

    audit(db, admin.username, "data_import",
          detail=f"loaded={loaded} skipped={skipped} replace={body.replace}", request=request)
    return {"ok": True, "loaded": loaded, "skipped": skipped}


@router.get("/fieldops/api/admin/audit")
async def admin_audit(limit: int = 200, db: AsyncSession = Depends(get_fieldops_db),
                      admin: FieldOpsUser = Depends(require_admin)):
    rows = (await db.execute(
        select(FieldOpsAudit).order_by(FieldOpsAudit.at.desc()).limit(min(limit, 1000))
    )).scalars().all()
    return {"events": [
        {"at": r.at.isoformat() if r.at else None, "actor": r.actor, "action": r.action,
         "target": r.target, "detail": r.detail, "ip": r.ip}
        for r in rows
    ]}


# ============================================================ sync
class Change(BaseModel):
    kind: str
    id: str
    data: Dict[str, Any]
    updated_at: Optional[str] = None
    deleted: bool = False


class SyncRequest(BaseModel):
    since: Optional[str] = None
    changes: List[Change] = Field(default_factory=list)


def _iso(dt) -> str:
    return dt.isoformat() if dt else ""


def _authorise(user: FieldOpsUser, change: Change, existing: Optional[FieldOpsRecord]) -> Optional[str]:
    """Return a refusal reason, or None if the change is allowed.

    The browser enforces these too, but a device can post whatever it likes —
    this is the copy that counts.
    """
    if change.kind not in SYNC_KINDS:
        return "unknown kind"
    if change.deleted:
        if not may_delete(user, change.kind):
            return "deletion not permitted for this role"
        return None
    if not may_write(user, change.kind):
        return "role may not write this record type"

    if change.kind == "qc":
        status_value = (change.data or {}).get("status")
        prior = (existing.data or {}).get("status") if existing else None
        # Recording a Reliance decision is the approver's alone (FR-011).
        if status_value in {"accepted", "disputed", "re_qc"} and prior != status_value:
            if user.role not in QC_DECISION_ROLES:
                return "only a Reliance QC approver may accept, dispute or re-QC"
        # Submitted evidence is immutable; corrections are new re-QC records (BR-05).
        if existing is not None and prior == "pending" and status_value == "pending":
            before, after = existing.data or {}, change.data or {}
            for field in ("responses", "codes", "photos", "seconds", "engineer_id"):
                if json.dumps(before.get(field), sort_keys=True, default=str) != \
                   json.dumps(after.get(field), sort_keys=True, default=str):
                    return "a submitted QC record cannot be edited (BR-05)"

    if change.kind == "commercial":
        status_value = (change.data or {}).get("commercial_status")
        prior = (existing.data or {}).get("commercial_status") if existing else None
        if status_value != prior and status_value in {"accepted", "hold", "disputed"}:
            if user.role not in {"commercial", "admin"}:
                return "only the commercial approver may set a commercial status"

    return None


@router.post("/fieldops/api/sync")
async def fieldops_sync(
    request: Request,
    payload: SyncRequest = Body(...),
    db: AsyncSession = Depends(get_fieldops_db),
    user: FieldOpsUser = Depends(require_user),
):
    now = app_now()
    if len(payload.changes) > MAX_CHANGES_PER_PUSH:
        raise HTTPException(status_code=413,
                            detail=f"Too many changes in one push (max {MAX_CHANGES_PER_PUSH}).")

    accepted, rejected, refusals = 0, 0, []
    for change in payload.changes:
        key = f"{change.kind}:{change.id}"
        existing = await db.get(FieldOpsRecord, key)

        reason = _authorise(user, change, existing)
        if reason:
            rejected += 1
            if len(refusals) < 20:
                refusals.append({"kind": change.kind, "id": change.id, "reason": reason})
            audit(db, user.username, "sync_refused", target=key, detail=reason, request=request)
            continue

        if existing is None:
            db.add(FieldOpsRecord(
                id=key, kind=change.kind, rec_id=change.id, data=change.data,
                updated_at=now, updated_by=user.username,
                device_updated_at=change.updated_at, deleted=bool(change.deleted),
            ))
            accepted += 1
        else:
            if (change.updated_at and existing.device_updated_at
                    and change.updated_at < existing.device_updated_at):
                rejected += 1
                continue
            existing.data = change.data
            existing.updated_at = now
            existing.updated_by = user.username
            existing.device_updated_at = change.updated_at
            existing.deleted = bool(change.deleted)
            accepted += 1

    if payload.changes:
        await db.flush()

    stmt = select(FieldOpsRecord)
    if payload.since:
        try:
            from datetime import datetime as _dt
            cursor = _dt.fromisoformat(payload.since)
            stmt = stmt.where(FieldOpsRecord.updated_at >= cursor - PULL_OVERLAP)
        except ValueError:
            pass
    stmt = stmt.order_by(FieldOpsRecord.updated_at).limit(MAX_PULL_RECORDS + 1)

    rows = (await db.execute(stmt)).scalars().all()
    truncated = len(rows) > MAX_PULL_RECORDS
    rows = rows[:MAX_PULL_RECORDS]

    return {
        "server_time": _iso(now),
        "cursor": _iso(rows[-1].updated_at) if (truncated and rows) else _iso(now),
        "accepted": accepted,
        "rejected": rejected,
        "refusals": refusals,
        "records": [
            {"kind": r.kind, "id": r.rec_id, "data": r.data, "deleted": r.deleted,
             "updated_at": _iso(r.updated_at), "updated_by": r.updated_by}
            for r in rows
        ],
        "truncated": truncated,
        "user": user.to_dict(),
    }


@router.get("/fieldops/api/status")
async def fieldops_status(db: AsyncSession = Depends(get_fieldops_db),
                          user: FieldOpsUser = Depends(require_user)):
    total = (await db.execute(select(func.count(FieldOpsRecord.id)))).scalar() or 0
    by_kind = (await db.execute(
        select(FieldOpsRecord.kind, func.count(FieldOpsRecord.id)).group_by(FieldOpsRecord.kind)
    )).all()
    latest = (await db.execute(select(func.max(FieldOpsRecord.updated_at)))).scalar()
    users = (await db.execute(select(func.count(FieldOpsUser.id)))).scalar() or 0
    return {
        "records": total,
        "by_kind": {k: c for k, c in by_kind},
        "users": users,
        "last_change": _iso(latest),
        "server_time": _iso(app_now()),
    }


# ============================================================ app shell
@router.get("/fieldops")
async def fieldops_root(user=Depends(current_user_optional)):
    if user is None:
        return RedirectResponse(url="/fieldops/login", status_code=302)
    return RedirectResponse(url="/fieldops/", status_code=307)


@router.get("/fieldops/")
async def fieldops_index(user=Depends(current_user_optional)):
    if user is None:
        return RedirectResponse(url="/fieldops/login", status_code=302)
    return _serve(_resolve("index.html"))


@router.get("/fieldops/{asset_path:path}")
async def fieldops_asset(asset_path: str, user=Depends(current_user_optional)):
    if user is None:
        # The worker and manifest must fail quietly rather than redirect into HTML.
        if asset_path.endswith((".js", ".css", ".webmanifest", ".json")):
            raise HTTPException(status_code=401, detail="Not signed in")
        return RedirectResponse(url="/fieldops/login", status_code=302)
    if not asset_path or asset_path.endswith("/"):
        return _serve(_resolve("index.html"))
    return _serve(_resolve(asset_path))
