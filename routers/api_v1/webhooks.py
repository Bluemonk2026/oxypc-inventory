"""
Admin CRUD for webhooks — session cookie auth.
POST   /api/v1/webhooks                     create
GET    /api/v1/webhooks                     list
DELETE /api/v1/webhooks/{webhook_id}        soft-delete
GET    /api/v1/webhooks/{webhook_id}/events recent event_log entries
"""
from datetime import datetime
from utils.timezone import app_now
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.webhook import Webhook
from models.event_log import EventLog
from models.user import User, UserRole
from auth.dependencies import get_current_user, require_roles
from schemas.webhook import WebhookCreateRequest, WebhookListItem, EventLogItem
from schemas.common import SuccessResponse, PaginatedResponse
from services.audit_engine import audit

router = APIRouter(prefix="/webhooks", tags=["api-v1-webhooks"])
admin_only = require_roles(UserRole.admin)


@router.post("", response_model=WebhookListItem, status_code=201)
async def create_webhook(
    body: WebhookCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    webhook = Webhook(
        name=body.name,
        url=body.url,
        secret_hash=Webhook.hash_secret(body.secret),
        event_types=body.event_types,
        is_active=body.is_active,
        created_by=current_user.username,
    )
    db.add(webhook)
    await db.flush()
    await audit(
        db, action="WEBHOOK_CREATED", user=current_user,
        table_name="webhooks", record_id=str(webhook.id),
        new_value={"name": body.name, "url": body.url, "event_types": body.event_types},
        request=None,
    )
    await db.commit()
    await db.refresh(webhook)
    return WebhookListItem.model_validate(webhook)


@router.get("", response_model=list[WebhookListItem])
async def list_webhooks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    result = await db.execute(
        select(Webhook).where(Webhook.deleted_at.is_(None)).order_by(Webhook.created_at.desc())
    )
    return [WebhookListItem.model_validate(w) for w in result.scalars().all()]


@router.delete("/{webhook_id}", response_model=SuccessResponse)
async def delete_webhook(
    webhook_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    result = await db.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.deleted_at.is_(None))
    )
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found or already deleted")
    webhook.is_active = False
    webhook.deleted_at = app_now()
    await audit(
        db, action="WEBHOOK_DELETED", user=current_user,
        table_name="webhooks", record_id=str(webhook.id),
        new_value={"name": webhook.name, "url": webhook.url},
        request=None,
    )
    await db.commit()
    return SuccessResponse(message=f"Webhook '{webhook.name}' deleted successfully")


@router.get("/{webhook_id}/events", response_model=PaginatedResponse[EventLogItem])
async def list_webhook_events(
    webhook_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    wh_result = await db.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.deleted_at.is_(None))
    )
    webhook = wh_result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    subscribed = webhook.event_types or []
    if not subscribed:
        return PaginatedResponse[EventLogItem](
            items=[], total=0, page=page, page_size=page_size, total_pages=1,
        )
    query = select(EventLog).where(EventLog.event_type.in_(subscribed))
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    logs_result = await db.execute(
        query.order_by(EventLog.published_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    logs = logs_result.scalars().all()
    total_pages = max(1, (total + page_size - 1) // page_size)
    return PaginatedResponse[EventLogItem](
        items=[EventLogItem.model_validate(e) for e in logs],
        total=total, page=page, page_size=page_size, total_pages=total_pages,
    )
