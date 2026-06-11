"""
Admin CRUD for API keys — uses session cookie auth (browser admin panel).
POST   /api/v1/api-keys            create new key (returns raw key ONCE)
GET    /api/v1/api-keys            list all active keys (prefixes only, never hashes)
DELETE /api/v1/api-keys/{key_id}   revoke (soft-delete) a key
"""
from datetime import datetime
from utils.timezone import app_now
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.api_key import APIKey
from models.user import User, UserRole
from auth.dependencies import get_current_user, require_roles
from auth.api_key import VALID_SCOPES
from schemas.common import (
    APIKeyCreateRequest, APIKeyCreatedResponse, APIKeyListItem, SuccessResponse,
)
from services.audit_engine import audit

router = APIRouter(prefix="/api-keys", tags=["api-v1-api-keys"])
admin_only = require_roles(UserRole.admin)


@router.post("", response_model=APIKeyCreatedResponse, status_code=201)
async def create_api_key(
    body: APIKeyCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    # Validate scopes
    invalid = [s for s in body.scopes if s not in VALID_SCOPES]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unknown scopes: {invalid}")

    raw_key, key_hash = APIKey.generate()
    key_prefix = raw_key[:12]

    api_key = APIKey(
        name=body.name,
        key_prefix=key_prefix,
        key_hash=key_hash,
        scopes=body.scopes,
        created_by=current_user.username,
    )
    db.add(api_key)
    await db.flush()

    await audit(
        db,
        action="API_KEY_CREATED",
        user=current_user,
        table_name="api_keys",
        record_id=str(api_key.id),
        new_value={"name": body.name, "scopes": body.scopes, "key_prefix": key_prefix},
        request=None,
    )
    await db.commit()

    return APIKeyCreatedResponse(
        id=str(api_key.id),
        name=api_key.name,
        key=raw_key,           # shown ONCE — never retrievable again
        key_prefix=key_prefix,
        scopes=api_key.scopes,
        created_at=api_key.created_at.isoformat(),
    )


@router.get("", response_model=list[APIKeyListItem])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    result = await db.execute(
        select(APIKey)
        .where(APIKey.deleted_at.is_(None))
        .order_by(APIKey.created_at.desc())
    )
    keys = result.scalars().all()
    return [
        APIKeyListItem(
            id=str(k.id),
            name=k.name,
            key_prefix=k.key_prefix,
            scopes=k.scopes or [],
            created_by=k.created_by,
            last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
            is_active=k.is_active,
            created_at=k.created_at.isoformat(),
        )
        for k in keys
    ]


@router.delete("/{key_id}", response_model=SuccessResponse)
async def revoke_api_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    result = await db.execute(
        select(APIKey).where(APIKey.id == key_id, APIKey.deleted_at.is_(None))
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found or already revoked")

    api_key.is_active = False
    api_key.deleted_at = app_now()

    await audit(
        db,
        action="API_KEY_REVOKED",
        user=current_user,
        table_name="api_keys",
        record_id=str(api_key.id),
        new_value={"name": api_key.name, "key_prefix": api_key.key_prefix},
        request=None,
    )
    await db.commit()
    return SuccessResponse(message=f"API key '{api_key.name}' revoked successfully")
