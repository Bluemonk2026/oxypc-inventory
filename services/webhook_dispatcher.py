"""
Webhook Dispatcher Service
--------------------------
Loads active webhooks matching an event type, sends signed outbound HTTP POSTs,
and records every published event in the event_log table.
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models.webhook import Webhook
from models.event_log import EventLog

logger = logging.getLogger(__name__)

DISPATCH_TIMEOUT = 10.0


def _sign(payload_bytes: bytes, secret_hash: str) -> str:
    """Compute HMAC-SHA256(key=secret_hash, msg=payload_bytes)."""
    return hmac.new(
        secret_hash.encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()


async def load_active_webhooks(db: AsyncSession, event_type: str) -> list[Webhook]:
    """Return all active, non-deleted webhooks subscribed to event_type."""
    result = await db.execute(
        select(Webhook).where(
            Webhook.is_active == True,
            Webhook.deleted_at.is_(None),
        )
    )
    all_hooks = result.scalars().all()
    return [h for h in all_hooks if event_type in (h.event_types or [])]


async def dispatch_webhook(
    hook: Webhook,
    event_type: str,
    payload: dict,
    timestamp: str,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> Optional[int]:
    """
    POST the event payload to hook.url with an HMAC signature header.
    Returns the HTTP status code on success, or None on timeout/error.
    Never raises.
    """
    body: dict = {
        "event_type": event_type,
        "payload": payload,
        "timestamp": timestamp,
        "webhook_id": str(hook.id),
    }
    body_bytes = json.dumps(body, default=str).encode()
    signature = _sign(body_bytes, hook.secret_hash)

    client_kwargs: dict = {"timeout": DISPATCH_TIMEOUT}
    if transport is not None:
        client_kwargs["transport"] = transport

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.post(
                hook.url,
                content=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-OxyPC-Signature": f"sha256={signature}",
                    "X-OxyPC-Event": event_type,
                },
            )
            return resp.status_code
    except httpx.TimeoutException:
        logger.warning("Webhook '%s' timed out delivering '%s'", hook.url, event_type)
        return None
    except Exception as exc:
        logger.warning("Webhook '%s' error delivering '%s': %s", hook.url, event_type, exc)
        return None


async def handle_event(event_type: str, payload: dict) -> None:
    """
    Top-level handler registered with the event bus.
    Creates its own AsyncSession (independent from the request-scoped session).
    """
    now = datetime.now(timezone.utc).isoformat()

    async with AsyncSessionLocal() as db:
        try:
            hooks = await load_active_webhooks(db, event_type)

            log_entry = EventLog(
                event_type=event_type,
                payload=payload,
                source_module=payload.get("_source", "unknown"),
                published_at=datetime.now(timezone.utc),
                webhook_attempts=len(hooks),
            )
            db.add(log_entry)
            await db.flush()

            last_status: Optional[int] = None
            for hook in hooks:
                status = await dispatch_webhook(hook, event_type, payload, now)
                last_status = status if status is not None else last_status
                log_entry.last_attempt_at = datetime.now(timezone.utc)

            if hooks:
                log_entry.last_status_code = last_status

            await db.commit()

        except Exception:
            logger.exception("handle_event failed for event_type='%s'", event_type)
            await db.rollback()
