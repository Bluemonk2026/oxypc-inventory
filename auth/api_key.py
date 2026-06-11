"""
API key authentication for machine-to-machine (M2M) endpoints.

Usage:
    @router.get("/", dependencies=[Depends(require_scope("devices:read"))])
    async def list_devices(...):
        ...

Or capture the API key object:
    @router.post("/register")
    async def register(api_key: APIKey = Depends(require_scope("iqc:write"))):
        ...
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.api_key import APIKey

VALID_SCOPES: frozenset[str] = frozenset({
    "devices:read",
    "devices:write",
    "lots:read",
    "lots:write",
    "sales:read",
    "sales:write",
    "iqc:read",
    "iqc:write",
    "dealers:read",
    "spare_parts:read",
    "intelligence:read",
    "api_keys:manage",
})


def _extract_bearer_token(auth_header: Optional[str]) -> Optional[str]:
    """Extract raw token from 'Authorization: Bearer <token>' header."""
    if not auth_header:
        return None
    if not auth_header.startswith("Bearer "):
        return None
    parts = auth_header.split(" ", 1)
    if len(parts) != 2:
        return None
    return parts[1].strip() or None


def require_scope(*scopes: str):
    """
    FastAPI dependency factory.
    Validates Bearer token against api_keys table and checks required scopes.
    Returns the APIKey ORM object so the endpoint can log the caller's name/id.

    Example:
        api_key: APIKey = Depends(require_scope("iqc:write"))
    """
    # Validate requested scopes at definition time — catches typos in route files
    for s in scopes:
        if s not in VALID_SCOPES:
            raise RuntimeError(
                f"Unknown scope '{s}' in require_scope() call. "
                f"Valid scopes: {sorted(VALID_SCOPES)}"
            )

    async def _verify(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> APIKey:
        raw_key = _extract_bearer_token(request.headers.get("Authorization", ""))
        if not raw_key:
            raise HTTPException(
                status_code=401,
                detail="Missing or malformed Authorization: Bearer <token> header",
            )

        key_hash = APIKey.hash_key(raw_key)
        result = await db.execute(
            select(APIKey).where(
                APIKey.key_hash == key_hash,
                APIKey.is_active == True,
                APIKey.deleted_at.is_(None),
            )
        )
        api_key = result.scalar_one_or_none()

        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid or revoked API key")

        # Scope check
        granted: list = api_key.scopes or []
        missing = [s for s in scopes if s not in granted]
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"API key missing required scopes: {missing}",
            )

        # Update last_used_at (non-critical — don't fail on error)
        try:
            await db.execute(
                update(APIKey)
                .where(APIKey.id == api_key.id)
                .values(last_used_at=datetime.utcnow())
            )
        except Exception:
            pass

        return api_key

    return _verify
