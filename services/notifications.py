"""
Notification service — create notifications from anywhere without circular imports.
"""
import uuid as _uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from models.notification import Notification


async def create_notification(
    db: AsyncSession,
    *,
    user_id: Optional[_uuid.UUID] = None,
    title: str,
    message: str,
    notification_type: str = "info",
    barcode: Optional[str] = None,
    brand: Optional[str] = None,
    model: Optional[str] = None,
    stage: Optional[str] = None,
) -> None:
    """
    Insert a notification row.

    - user_id=None  → broadcast (visible to ALL users).
    - user_id=<int> → personal notification for that specific user only.
    - notification_type: info | success | warning | alert
    """
    notif = Notification(
        user_id=user_id,
        title=title,
        message=message,
        notification_type=notification_type,
        barcode=barcode,
        brand=brand,
        model=model,
        stage=stage,
    )
    db.add(notif)
    await db.commit()
