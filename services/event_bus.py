"""
In-process event bus — synchronous pub/sub with async handlers.

Usage (in a route):
    from fastapi import BackgroundTasks
    from services.event_bus import EventType, publish

    async def my_route(background_tasks: BackgroundTasks, ...):
        ...
        await db.commit()
        publish(EventType.DEVICE_REGISTERED, {"barcode": "OXY-001"}, background_tasks)

Usage (at startup — subscribe dispatcher):
    from services.event_bus import subscribe, EventType
    subscribe(EventType.DEVICE_REGISTERED, handle_event)

Handler signature:
    async def handle_event(event_type: str, payload: dict) -> None: ...
    Handlers must create their own DB sessions; they run after the HTTP response.
"""
import asyncio
import logging
from typing import Callable, Awaitable, Any

logger = logging.getLogger(__name__)

Handler = Callable[[str, dict[str, Any]], Awaitable[None]]

_registry: dict[str, list[Handler]] = {}


class EventType:
    DEVICE_REGISTERED = "DEVICE_REGISTERED"
    LOT_CREATED       = "LOT_CREATED"
    QC_PASSED         = "QC_PASSED"
    SALE_COMPLETED    = "SALE_COMPLETED"
    STAGE_MOVED       = "STAGE_MOVED"
    API_KEY_CREATED   = "API_KEY_CREATED"
    API_KEY_REVOKED   = "API_KEY_REVOKED"
    # Telecalling mobile (sprint 2026-05)
    CALL_LOGGED            = "CALL_LOGGED"
    CALL_ORDER_PLACED      = "CALL_ORDER_PLACED"
    CALL_QUOTE_SENT        = "CALL_QUOTE_SENT"
    CALL_DNC_SET           = "CALL_DNC_SET"
    ASSIGNMENT_CREATED     = "ASSIGNMENT_CREATED"


def subscribe(event_type: str, handler: Handler) -> None:
    """Register an async handler for an event type. Safe to call multiple times."""
    _registry.setdefault(event_type, []).append(handler)


def publish(
    event_type: str,
    payload: dict[str, Any],
    background_tasks=None,
) -> None:
    """
    Schedule all registered handlers for event_type.

    If background_tasks (FastAPI BackgroundTasks) is provided, handlers
    are added there (run after the HTTP response is sent, within the
    request lifecycle). Otherwise, handlers are scheduled as asyncio tasks
    on the currently running event loop (fire-and-forget).

    publish() is intentionally synchronous — it never blocks the caller.
    """
    handlers = _registry.get(event_type, [])
    for handler in handlers:
        if background_tasks is not None:
            background_tasks.add_task(_safe_call, handler, event_type, payload)
        else:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(_safe_call(handler, event_type, payload))
            except RuntimeError:
                pass  # No event loop — skip silently (e.g. CLI context)


async def _safe_call(handler: Handler, event_type: str, payload: dict) -> None:
    """Invoke handler, swallowing all exceptions so one bad handler can't crash the bus."""
    try:
        await handler(event_type, payload)
    except Exception:
        logger.exception(
            "Event handler '%s' raised an exception for event '%s'",
            getattr(handler, "__name__", repr(handler)),
            event_type,
        )


def clear_all_handlers() -> None:
    """Reset the registry. For use in tests only."""
    _registry.clear()
