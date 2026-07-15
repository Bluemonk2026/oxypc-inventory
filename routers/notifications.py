"""
Global Notification System — bell icon + alerts page.
Features 9, 10, 11 — Sprint 31
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, or_

from templates_config import templates
from database import get_db
from models.user import User
from models.notification import Notification
from auth.dependencies import get_current_user, verify_csrf

router = APIRouter(tags=["notifications"], dependencies=[Depends(verify_csrf)])


@router.get("/notifications/alerts", response_class=HTMLResponse)
async def alerts_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    q: str = "",
    brand: str = "",
    stage: str = "",
    date_from: str = "",
    date_to: str = "",
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    query = (
        select(Notification)
        .where(
            Notification.created_at >= cutoff,
            or_(
                Notification.user_id == current_user.id,
                Notification.user_id == None,  # noqa: E711
            ),
        )
        .order_by(Notification.created_at.desc())
    )

    result = await db.execute(query)
    all_notifs = list(result.scalars().all())

    # Apply filters in Python (small dataset — max 30 days)
    if q:
        all_notifs = [n for n in all_notifs if q.lower() in (n.barcode or "").lower()]
    if brand:
        all_notifs = [
            n for n in all_notifs
            if brand.lower() in (n.brand or "").lower()
            or brand.lower() in (n.model or "").lower()
        ]
    if stage:
        all_notifs = [n for n in all_notifs if stage.lower() in (n.stage or "").lower()]
    if date_from:
        try:
            df = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            all_notifs = [n for n in all_notifs if n.created_at >= df]
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
            all_notifs = [n for n in all_notifs if n.created_at <= dt]
        except ValueError:
            pass

    # Mark all visible (unread) notifications as read for this user
    await db.execute(
        update(Notification)
        .where(
            or_(
                Notification.user_id == current_user.id,
                Notification.user_id == None,  # noqa: E711
            ),
            Notification.is_read == False,  # noqa: E712
        )
        .values(is_read=True)
    )
    await db.commit()

    return templates.TemplateResponse(
        "notifications/alerts.html",
        {
            "request": request,
            "current_user": current_user,
            "notifications": all_notifs,
            "q": q,
            "brand": brand,
            "stage": stage,
            "date_from": date_from,
            "date_to": date_to,
        },
    )


@router.get("/notifications/recent")
async def recent_notifications(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """JSON feed for the topbar bell's slide-in panel — last 30 days, newest first."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    result = await db.execute(
        select(Notification)
        .where(
            Notification.created_at >= cutoff,
            or_(
                Notification.user_id == current_user.id,
                Notification.user_id == None,  # noqa: E711
            ),
        )
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    notifs = result.scalars().all()

    await db.execute(
        update(Notification)
        .where(
            or_(
                Notification.user_id == current_user.id,
                Notification.user_id == None,  # noqa: E711
            ),
            Notification.is_read == False,  # noqa: E712
        )
        .values(is_read=True)
    )
    await db.commit()

    return JSONResponse({
        "notifications": [
            {
                "id": n.id,
                "barcode": n.barcode or "",
                "title": n.title,
                "message": n.message,
                "notification_type": n.notification_type,
                "created_at": n.created_at.strftime("%d-%m-%Y %H:%M") if n.created_at else "",
            }
            for n in notifs
        ]
    })


@router.get("/notifications/since")
async def notifications_since(
    after_id: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Feed for the top-right live toast popup — unread notifications newer
    than `after_id`, WITHOUT marking them read (unlike /notifications/recent,
    which is only meant for the bell panel's explicit open action). A toast
    firing and auto-dismissing isn't the same as the user having read it."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    query = (
        select(Notification)
        .where(
            Notification.created_at >= cutoff,
            Notification.is_read == False,  # noqa: E712
            or_(
                Notification.user_id == current_user.id,
                Notification.user_id == None,  # noqa: E711
            ),
        )
        .order_by(Notification.id.asc())
    )
    if after_id:
        query = query.where(Notification.id > after_id)
    result = await db.execute(query.limit(20))
    notifs = result.scalars().all()

    return JSONResponse({
        "notifications": [
            {
                "id": n.id,
                "barcode": n.barcode or "",
                "title": n.title,
                "message": n.message,
                "notification_type": n.notification_type,
                "created_at": n.created_at.strftime("%d-%m-%Y %H:%M") if n.created_at else "",
            }
            for n in notifs
        ]
    })


@router.get("/notifications/unread-count")
async def unread_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(func.count(Notification.id)).where(
            or_(
                Notification.user_id == current_user.id,
                Notification.user_id == None,  # noqa: E711
            ),
            Notification.is_read == False,  # noqa: E712
        )
    )
    count = result.scalar() or 0
    return JSONResponse({"count": count})


@router.post("/notifications/{notif_id}/read")
async def mark_read(
    notif_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await db.execute(
        update(Notification)
        .where(Notification.id == notif_id)
        .values(is_read=True)
    )
    await db.commit()
    return JSONResponse({"ok": True})
