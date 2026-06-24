from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
import bcrypt as _bcrypt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db
from models.user import User, UserRole
from config import SECRET_KEY, ACCESS_TOKEN_EXPIRE_MINUTES

ALGORITHM = "HS256"

ROLE_PERMISSIONS = {
    UserRole.admin: ["*"],
    UserRole.inventory_manager: ["dashboard", "lots", "stock", "iqc", "repair", "reports"],
    UserRole.iqc_inspector: ["dashboard", "iqc", "repair/move"],
    UserRole.l1_engineer: ["dashboard", "repair/l1", "repair/move"],
    UserRole.l2_engineer: ["dashboard", "repair/l2", "repair/move"],
    UserRole.l3_engineer: ["dashboard", "repair/l3", "repair/move"],
    UserRole.qc_inspector: ["dashboard", "qc", "repair/move", "reports"],
    UserRole.sales: [
        "dashboard", "sales", "returns", "reports/sales",
        "tc.call.create", "tc.call.view_own", "tc.queue.view_own",
        "tc.followup.view_own", "tc.quote.create",
    ],
    UserRole.spare_parts_manager: ["dashboard", "spare-parts", "ram-tracking"],
    UserRole.telecaller: [
        "dashboard", "tc.call.create", "tc.call.view_own",
        "tc.queue.view_own", "tc.followup.view_own", "tc.quote.create",
    ],
    UserRole.sales_manager: [
        "dashboard", "sales", "returns", "reports/sales",
        "tc.call.create", "tc.call.view_own", "tc.call.view_team",
        "tc.queue.view_own", "tc.queue.view_team",
        "tc.followup.view_own", "tc.quote.create",
        "tc.assign.create", "tc.kpi.view_team",
    ],
}


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/auth/login"})
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            raise HTTPException(status_code=302, headers={"Location": "/auth/login"})
    except JWTError:
        raise HTTPException(status_code=302, headers={"Location": "/auth/login"})

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user or not user.status:
        raise HTTPException(status_code=302, headers={"Location": "/auth/login"})
    return user


def require_roles(*roles: UserRole):
    async def checker(current_user: User = Depends(get_current_user)):
        role = current_user.role
        if role == UserRole.admin or role in roles:
            return current_user
        # Custom (admin-created) roles are NOT part of the UserRole enum; they are
        # governed by the Module Permission matrix (left-nav visibility + per-action
        # require_module_perm), not these built-in role allow-lists. Let a custom
        # role through any NON-admin-only gate so a module enabled for it in the
        # matrix actually works. Admin-only gates — require_roles(UserRole.admin)
        # alone — still block custom roles.
        role_val = getattr(role, "value", None) or str(role)
        builtin = {r.value for r in UserRole}
        if role_val not in builtin and set(roles) != {UserRole.admin}:
            return current_user
        raise HTTPException(status_code=403, detail="Access denied")
    return checker


def get_nav_permissions(role: UserRole) -> list:
    perms = ROLE_PERMISSIONS.get(role, [])
    if "*" in perms:
        return ["*"]
    return perms


def require_module_perm(module: str, action: str = "enable"):
    """Dependency factory enforcing the admin-configured Module Permission matrix.

    Usage on a route:
        from auth.dependencies import require_module_perm
        @router.post("/lots/add", dependencies=[Depends(require_module_perm("lots", "add"))])

    Behaviour:
      - admin always passes
      - if no matrix row is configured for the role/module → passes (permissive default)
      - otherwise the specific action bit (enable/add/edit/upload) must be granted,
        else 403.
    """
    from models.role_permissions import has_perm

    async def checker(current_user: User = Depends(get_current_user)) -> User:
        role_name = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        if not has_perm(role_name, module, action):
            raise HTTPException(
                status_code=403,
                detail=f"Your role ({role_name}) does not have '{action}' permission for the {module} module.",
            )
        return current_user

    return checker


async def verify_csrf(request: Request) -> None:
    """Dependency: validate CSRF double-submit cookie for mutating requests.

    Usage in POST routes:
        from auth.dependencies import verify_csrf
        from fastapi import Depends

        @router.post("/some-path")
        async def handler(_csrf=Depends(verify_csrf), ...):
            ...

    Validates that the 'csrf_token' form field matches the 'csrf_token' cookie.
    Skips validation for GET/HEAD/OPTIONS requests.
    """
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return
    cookie_token = request.cookies.get("csrf_token", "")
    if not cookie_token:
        from fastapi.responses import HTMLResponse
        from fastapi import HTTPException
        raise HTTPException(
            status_code=403,
            detail="CSRF token missing. Please log in again."
        )
    # Form field must match cookie — read form data (FastAPI caches it per request)
    try:
        form = await request.form()
        form_token = form.get("csrf_token", "")
    except Exception:
        form_token = ""
    if not form_token:
        form_token = request.headers.get("X-CSRF-Token", "")
    if not form_token or form_token != cookie_token:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=403,
            detail="CSRF validation failed. Please refresh and try again."
        )
