# tests/test_event_bus.py
"""Unit tests for the in-process event bus."""
import asyncio
import pytest
from fastapi import BackgroundTasks


async def test_subscribe_and_publish_with_background_tasks():
    """Handler is called when published with BackgroundTasks."""
    from services.event_bus import subscribe, publish, clear_all_handlers, EventType
    clear_all_handlers()
    results = []

    async def handler(event_type: str, payload: dict) -> None:
        results.append((event_type, payload))

    subscribe(EventType.DEVICE_REGISTERED, handler)
    bt = BackgroundTasks()
    publish(EventType.DEVICE_REGISTERED, {"barcode": "OXY-001"}, bt)

    # FastAPI BackgroundTasks.__call__ runs all tasks
    await bt()

    assert len(results) == 1
    assert results[0] == (EventType.DEVICE_REGISTERED, {"barcode": "OXY-001"})


async def test_multiple_handlers_all_called():
    """All handlers subscribed to an event type are invoked."""
    from services.event_bus import subscribe, publish, clear_all_handlers, EventType
    clear_all_handlers()
    calls = []

    async def h1(et, p): calls.append("h1")
    async def h2(et, p): calls.append("h2")

    subscribe(EventType.LOT_CREATED, h1)
    subscribe(EventType.LOT_CREATED, h2)
    bt = BackgroundTasks()
    publish(EventType.LOT_CREATED, {}, bt)
    await bt()

    assert "h1" in calls
    assert "h2" in calls


async def test_handler_exception_does_not_crash_bus():
    """A failing handler must not prevent other handlers from running."""
    from services.event_bus import subscribe, publish, clear_all_handlers, EventType
    clear_all_handlers()
    calls = []

    async def bad_handler(et, p): raise RuntimeError("boom")
    async def good_handler(et, p): calls.append("ok")

    subscribe(EventType.SALE_COMPLETED, bad_handler)
    subscribe(EventType.SALE_COMPLETED, good_handler)
    bt = BackgroundTasks()
    publish(EventType.SALE_COMPLETED, {}, bt)
    await bt()  # must not raise

    assert "ok" in calls


async def test_publish_no_subscribers_is_silent():
    """Publishing to an event type with no subscribers does not raise."""
    from services.event_bus import publish, clear_all_handlers, EventType
    clear_all_handlers()
    bt = BackgroundTasks()
    publish(EventType.QC_PASSED, {"device_id": "x"}, bt)
    await bt()  # no error


async def test_clear_all_handlers_resets_state():
    """clear_all_handlers removes all subscriptions."""
    from services.event_bus import subscribe, publish, clear_all_handlers, EventType
    clear_all_handlers()
    calls = []

    async def handler(et, p): calls.append(et)

    subscribe(EventType.STAGE_MOVED, handler)
    clear_all_handlers()
    bt = BackgroundTasks()
    publish(EventType.STAGE_MOVED, {}, bt)
    await bt()

    assert calls == []
