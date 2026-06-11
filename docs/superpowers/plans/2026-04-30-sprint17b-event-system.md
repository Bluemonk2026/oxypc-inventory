# Sprint 17b — Event System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an in-process event bus + outbound webhook dispatcher to the OxyPC Inventory API layer so that ecosystem apps receive real-time notifications when key business events occur.

**Architecture:** A lightweight pub/sub registry (`services/event_bus.py`) holds event-type → handler mappings. When a route publishes an event via FastAPI `BackgroundTasks`, the dispatcher service (`services/webhook_dispatcher.py`) creates its own `AsyncSessionLocal()` session, loads subscribed webhooks, sends signed HTTP POSTs, and appends a row to `event_log`. No external broker is required.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, Alembic, Pydantic v2, httpx 0.28.1 (already in requirements.txt), stdlib `hmac`/`hashlib`.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `services/event_bus.py` | **Create** | EventType constants, registry, `subscribe()`, `publish()` |
| `services/webhook_dispatcher.py` | **Create** | HMAC signing, HTTP dispatch, `handle_event()` |
| `models/webhook.py` | **Create** | `Webhook` ORM model |
| `models/event_log.py` | **Create** | `EventLog` ORM model |
| `models/__init__.py` | **Modify** | Add `APIKey`, `Webhook`, `EventLog` imports |
| `alembic/versions/20260430_0900_add_webhooks_event_log.py` | **Create** | Migration for both tables + indexes |
| `schemas/webhook.py` | **Create** | `WebhookCreateRequest`, `WebhookListItem`, `EventLogItem` |
| `routers/api_v1/webhooks.py` | **Create** | Admin CRUD for webhooks + event log view |
| `routers/api_v1/__init__.py` | **Modify** | Register webhooks router |
| `routers/api_v1/iqc.py` | **Modify** | Publish `DEVICE_REGISTERED` after commit |
| `routers/api_v1/devices.py` | **Modify** | Publish `STAGE_MOVED` after stage move commit |
| `routers/stock.py` | **Modify** | Publish `LOT_CREATED` after commit |
| `routers/sales.py` | **Modify** | Publish `SALE_COMPLETED` after commit |
| `main.py` | **Modify** | Subscribe `handle_event` to all event types at startup |
| `tests/test_event_bus.py` | **Create** | Unit tests for pub/sub registry |
| `tests/test_webhook_dispatcher.py` | **Create** | HMAC + dispatch + logging tests |
| `tests/test_webhook_api.py` | **Create** | Integration tests for webhook admin API |

---

## Task 1: Event Bus Service

**Files:**
- Create: `services/event_bus.py`
- Test: `tests/test_event_bus.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run tests — expect ImportError/NameError (module doesn't exist yet)**

```
pytest tests/test_event_bus.py -v
```
Expected: FAILED (ImportError: No module named 'services.event_bus')

- [ ] **Step 3: Create `services/event_bus.py`**

```python
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
```

- [ ] **Step 4: Run tests — expect all 5 to pass**

```
pytest tests/test_event_bus.py -v
```
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add services/event_bus.py tests/test_event_bus.py
git commit -m "feat(event-bus): in-process pub/sub registry with async handler scheduling"
```

---

## Task 2: DB Models — Webhook + EventLog

**Files:**
- Create: `models/webhook.py`
- Create: `models/event_log.py`
- Modify: `models/__init__.py`

- [ ] **Step 1: Create `models/webhook.py`**

```python
"""
Webhook model — outbound HTTP delivery configuration.

Each row represents one subscriber URL that receives signed HTTP POSTs
for its subscribed event types.
"""
import uuid
import hashlib
from datetime import datetime

from sqlalchemy import Column, String, Boolean, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID

from database import Base


class Webhook(Base):
    __tablename__ = "webhooks"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name        = Column(String(100), nullable=False)
    url         = Column(String(500), nullable=False)
    # SHA-256 of the user-supplied signing secret. Used as the HMAC key.
    # The raw secret is NEVER stored.
    secret_hash = Column(String(64), nullable=False)
    # JSON array of EventType strings, e.g. ["DEVICE_REGISTERED", "SALE_COMPLETED"]
    event_types = Column(JSON, nullable=False, default=list)
    is_active   = Column(Boolean, default=True, nullable=False)
    created_by  = Column(String(50), nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False)
    deleted_at  = Column(DateTime, nullable=True)  # soft-delete; NULL = alive

    @staticmethod
    def hash_secret(raw_secret: str) -> str:
        """SHA-256 hash of the signing secret for safe storage."""
        return hashlib.sha256(raw_secret.encode()).hexdigest()
```

- [ ] **Step 2: Create `models/event_log.py`**

```python
"""
EventLog model — append-only record of every published event.

One row per event publication. webhook_attempts tracks how many
webhooks were dispatched; last_status_code records the final HTTP
response from the most recently attempted webhook.
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, JSON, Index
from sqlalchemy.dialects.postgresql import UUID

from database import Base


class EventLog(Base):
    __tablename__ = "event_log"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type       = Column(String(50), nullable=False)
    payload          = Column(JSON, nullable=False)
    source_module    = Column(String(50), nullable=True)
    published_at     = Column(DateTime, default=datetime.utcnow, nullable=False)
    webhook_attempts = Column(Integer, default=0, nullable=False)
    last_attempt_at  = Column(DateTime, nullable=True)
    last_status_code = Column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_event_log_event_type",   "event_type"),
        Index("ix_event_log_published_at", "published_at"),
    )
```

- [ ] **Step 3: Add imports to `models/__init__.py`**

Open `models/__init__.py`. At the very end of the file, append:

```python
from .api_key import APIKey
from .webhook import Webhook
from .event_log import EventLog
```

> **Note:** `APIKey` was created in Sprint 17a but was never added to `__init__.py`. Add it here along with the two new models so all models are registered with SQLAlchemy's metadata.

- [ ] **Step 4: Verify models import cleanly**

```
python -c "from models import APIKey, Webhook, EventLog; print('OK')"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add models/webhook.py models/event_log.py models/__init__.py
git commit -m "feat(models): add Webhook + EventLog models; register APIKey in __init__"
```

---

## Task 3: Alembic Migration

**Files:**
- Create: `alembic/versions/20260430_0900_add_webhooks_event_log.py`

- [ ] **Step 1: Create the migration file**

```python
# alembic/versions/20260430_0900_add_webhooks_event_log.py
"""
Add webhooks and event_log tables — Sprint 17b event system.

Revision ID: 20260430_0900
Revises: 20260429_1200
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260430_0900'
down_revision = '20260429_1200'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── webhooks ──────────────────────────────────────────────────────────────
    op.create_table(
        'webhooks',
        sa.Column('id',          postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name',        sa.String(100), nullable=False),
        sa.Column('url',         sa.String(500), nullable=False),
        sa.Column('secret_hash', sa.String(64),  nullable=False),
        sa.Column('event_types', sa.JSON(),       nullable=False,
                  server_default='[]'),
        sa.Column('is_active',   sa.Boolean(),    nullable=False,
                  server_default='true'),
        sa.Column('created_by',  sa.String(50),   nullable=False),
        sa.Column('created_at',  sa.DateTime(),   nullable=False,
                  server_default=sa.func.now()),
        sa.Column('deleted_at',  sa.DateTime(),   nullable=True),
    )
    op.create_index('ix_webhooks_is_active', 'webhooks', ['is_active'])

    # ── event_log ─────────────────────────────────────────────────────────────
    op.create_table(
        'event_log',
        sa.Column('id',               postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('event_type',       sa.String(50),  nullable=False),
        sa.Column('payload',          sa.JSON(),       nullable=False),
        sa.Column('source_module',    sa.String(50),   nullable=True),
        sa.Column('published_at',     sa.DateTime(),   nullable=False,
                  server_default=sa.func.now()),
        sa.Column('webhook_attempts', sa.Integer(),    nullable=False,
                  server_default='0'),
        sa.Column('last_attempt_at',  sa.DateTime(),   nullable=True),
        sa.Column('last_status_code', sa.Integer(),    nullable=True),
    )
    op.create_index('ix_event_log_event_type',   'event_log', ['event_type'])
    op.create_index('ix_event_log_published_at', 'event_log', ['published_at'])


def downgrade() -> None:
    op.drop_index('ix_event_log_published_at', table_name='event_log')
    op.drop_index('ix_event_log_event_type',   table_name='event_log')
    op.drop_table('event_log')
    op.drop_index('ix_webhooks_is_active', table_name='webhooks')
    op.drop_table('webhooks')
```

- [ ] **Step 2: Run the migration**

```
python -m alembic upgrade head
```
Expected output ends with: `Running upgrade 20260429_1200 -> 20260430_0900`

- [ ] **Step 3: Verify tables exist**

```
python -m alembic current
```
Expected: `20260430_0900 (head)`

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/20260430_0900_add_webhooks_event_log.py
git commit -m "feat(migration): add webhooks + event_log tables — Sprint 17b"
```

---

## Task 4: Webhook Dispatcher Service

**Files:**
- Create: `services/webhook_dispatcher.py`
- Test: `tests/test_webhook_dispatcher.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_webhook_dispatcher.py
"""
Tests for the webhook dispatcher service.
Uses httpx.MockTransport to intercept outbound HTTP calls.
"""
import hashlib
import hmac
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# ── HMAC signature ────────────────────────────────────────────────────────────

async def test_sign_produces_correct_hmac():
    """_sign must produce HMAC-SHA256(secret_hash, payload_bytes)."""
    from services.webhook_dispatcher import _sign

    payload_bytes = b'{"event_type": "DEVICE_REGISTERED"}'
    secret_hash = hashlib.sha256(b"mysecret").hexdigest()

    result = _sign(payload_bytes, secret_hash)

    expected = hmac.new(
        secret_hash.encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    assert result == expected


async def test_sign_changes_with_different_payload():
    """Different payloads must produce different signatures."""
    from services.webhook_dispatcher import _sign

    secret_hash = hashlib.sha256(b"s").hexdigest()
    sig1 = _sign(b"payload-a", secret_hash)
    sig2 = _sign(b"payload-b", secret_hash)
    assert sig1 != sig2


# ── dispatch_webhook ──────────────────────────────────────────────────────────

async def test_dispatch_webhook_sends_correct_headers():
    """dispatch_webhook must set X-OxyPC-Signature and X-OxyPC-Event headers."""
    from services.webhook_dispatcher import dispatch_webhook

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200)

    secret_hash = hashlib.sha256(b"secret").hexdigest()

    hook = MagicMock()
    hook.url = "http://example.com/webhook"
    hook.secret_hash = secret_hash
    hook.id = "test-id"

    status = await dispatch_webhook(
        hook=hook,
        event_type="DEVICE_REGISTERED",
        payload={"barcode": "OXY-001"},
        timestamp="2026-04-30T00:00:00+00:00",
        transport=httpx.MockTransport(handler),
    )

    assert status == 200
    assert "x-oxypc-signature" in captured["headers"]
    assert captured["headers"]["x-oxypc-event"] == "DEVICE_REGISTERED"
    assert captured["body"]["event_type"] == "DEVICE_REGISTERED"
    assert captured["body"]["payload"]["barcode"] == "OXY-001"


async def test_dispatch_webhook_returns_none_on_timeout():
    """dispatch_webhook must return None (not raise) on timeout."""
    from services.webhook_dispatcher import dispatch_webhook

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    hook = MagicMock()
    hook.url = "http://slow.example.com/wh"
    hook.secret_hash = hashlib.sha256(b"s").hexdigest()
    hook.id = "id1"

    status = await dispatch_webhook(
        hook=hook,
        event_type="TEST",
        payload={},
        timestamp="2026-04-30T00:00:00+00:00",
        transport=httpx.MockTransport(handler),
    )
    assert status is None


async def test_dispatch_webhook_returns_none_on_connection_error():
    """dispatch_webhook must return None on any connection-level error."""
    from services.webhook_dispatcher import dispatch_webhook

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    hook = MagicMock()
    hook.url = "http://unreachable.example.com/wh"
    hook.secret_hash = hashlib.sha256(b"s").hexdigest()
    hook.id = "id2"

    status = await dispatch_webhook(
        hook=hook,
        event_type="TEST",
        payload={},
        timestamp="2026-04-30T00:00:00+00:00",
        transport=httpx.MockTransport(handler),
    )
    assert status is None
```

- [ ] **Step 2: Run — expect ImportError**

```
pytest tests/test_webhook_dispatcher.py -v
```
Expected: FAILED (ImportError: No module named 'services.webhook_dispatcher')

- [ ] **Step 3: Create `services/webhook_dispatcher.py`**

```python
"""
Webhook Dispatcher Service
--------------------------
Loads active webhooks matching an event type, sends signed outbound HTTP POSTs,
and records every published event in the event_log table.

Called as a background task handler registered with the event bus.
The top-level entry point is handle_event(), which creates its own DB session
because it runs after the originating HTTP response has already been sent.
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

DISPATCH_TIMEOUT = 10.0   # seconds per webhook call


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sign(payload_bytes: bytes, secret_hash: str) -> str:
    """
    Compute HMAC-SHA256(key=secret_hash, msg=payload_bytes).

    The stored secret_hash is SHA-256(user_secret); it is used as the HMAC key
    so the raw secret never needs to be reconstructed.
    Receivers verify: hmac.new(secret_hash.encode(), body, sha256).hexdigest()
    """
    return hmac.new(
        secret_hash.encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()


# ── Core functions ────────────────────────────────────────────────────────────

async def load_active_webhooks(db: AsyncSession, event_type: str) -> list[Webhook]:
    """
    Return all active, non-deleted webhooks subscribed to event_type.
    JSON array filtering is done in Python (not SQL) for portability across
    PostgreSQL versions.
    """
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
    Never raises — all exceptions are caught and logged.

    The optional `transport` parameter is for unit tests (httpx.MockTransport).
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

    Creates its own AsyncSession (independent from the request-scoped session)
    because this runs as a background task after the HTTP response is sent.
    """
    now = datetime.now(timezone.utc).isoformat()

    async with AsyncSessionLocal() as db:
        try:
            hooks = await load_active_webhooks(db, event_type)

            # Write event_log row first (even when no webhooks are subscribed)
            log_entry = EventLog(
                event_type=event_type,
                payload=payload,
                source_module=payload.get("_source", "unknown"),
                published_at=datetime.now(timezone.utc),
                webhook_attempts=len(hooks),
            )
            db.add(log_entry)
            await db.flush()  # get log_entry.id

            # Dispatch to each subscribed webhook
            last_status: Optional[int] = None
            for hook in hooks:
                status = await dispatch_webhook(hook, event_type, payload, now)
                last_status = status if status is not None else last_status
                log_entry.last_attempt_at = datetime.now(timezone.utc)

            if hooks:
                log_entry.last_status_code = last_status

            await db.commit()

        except Exception:
            logger.exception(
                "handle_event failed for event_type='%s'", event_type
            )
            await db.rollback()
```

- [ ] **Step 4: Run dispatcher tests**

```
pytest tests/test_webhook_dispatcher.py -v
```
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add services/webhook_dispatcher.py tests/test_webhook_dispatcher.py
git commit -m "feat(dispatcher): webhook dispatcher with HMAC signing + event_log recording"
```

---

## Task 5: Wire Events into Existing API Routes

**Files:**
- Modify: `routers/api_v1/iqc.py`
- Modify: `routers/api_v1/devices.py`
- Modify: `main.py`

- [ ] **Step 1: Wire `DEVICE_REGISTERED` into `routers/api_v1/iqc.py`**

Add `BackgroundTasks` to the `register_device` route. The full updated function signature and publish call (add these three lines at the top of the imports, then update the function):

At the top of `routers/api_v1/iqc.py`, add these two imports after the existing imports:

```python
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from services.event_bus import EventType, publish
```

> Note: `BackgroundTasks` is added to the existing `fastapi` import line.

Change the existing import line:
```python
# OLD:
from fastapi import APIRouter, Depends, HTTPException
# NEW:
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
```

And add after it:
```python
from services.event_bus import EventType, publish
```

Update the `register_device` function signature to add `background_tasks: BackgroundTasks` (FastAPI injects this automatically — no `Depends` needed):

```python
@router.post("/register", response_model=SuccessResponse, status_code=201)
async def register_device(
    body: IQCRegisterRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_scope("iqc:write")),
):
```

After `await db.commit()` (the last line before `return`), add:

```python
    publish(EventType.DEVICE_REGISTERED, {
        "barcode": body.barcode,
        "lot_id": str(body.lot_id),
        "brand": body.brand,
        "model": body.model,
        "grade": body.grade,
        "_source": "iqc_api",
    }, background_tasks)
    return SuccessResponse(message="Device registered successfully", id=str(device.id))
```

- [ ] **Step 2: Wire `STAGE_MOVED` into `routers/api_v1/devices.py`**

Add imports at the top of `routers/api_v1/devices.py`:

```python
# Change existing fastapi import to:
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
# Add after existing imports:
from services.event_bus import EventType, publish
```

Update `move_device_stage` signature to add `background_tasks: BackgroundTasks`:

```python
@router.patch("/{barcode}/stage", response_model=DeviceOut)
async def move_device_stage(
    barcode: str,
    body: DeviceStageMoveRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_scope("devices:write")),
):
```

After `await db.commit()` and `await db.refresh(device)`, but before `return`:

```python
    await db.commit()
    await db.refresh(device)
    publish(EventType.STAGE_MOVED, {
        "barcode": barcode,
        "from_stage": current,
        "to_stage": body.to_stage,
        "api_key_name": api_key.name,
        "_source": "devices_api",
    }, background_tasks)
    return DeviceOut.model_validate(device)
```

- [ ] **Step 3: Subscribe `handle_event` to all event types in `main.py`**

In `main.py`, find the `startup_event()` function (line ~220). Add these imports near the top of `main.py` (after the existing imports block):

```python
from services.event_bus import subscribe, EventType
from services.webhook_dispatcher import handle_event
```

Inside `startup_event()`, after the banner print statements at the very end of the function:

```python
    # ── Subscribe webhook dispatcher to all event types ────────────────────
    for _et in [
        EventType.DEVICE_REGISTERED,
        EventType.LOT_CREATED,
        EventType.QC_PASSED,
        EventType.SALE_COMPLETED,
        EventType.STAGE_MOVED,
        EventType.API_KEY_CREATED,
        EventType.API_KEY_REVOKED,
    ]:
        subscribe(_et, handle_event)
    print("  [Events] Webhook dispatcher subscribed to all event types")
```

- [ ] **Step 4: Verify app imports cleanly**

```
python -c "from main import app; print('OK')"
```
Expected: `OK` (no ImportError)

- [ ] **Step 5: Commit**

```bash
git add routers/api_v1/iqc.py routers/api_v1/devices.py main.py
git commit -m "feat(events): publish DEVICE_REGISTERED + STAGE_MOVED from API routes; wire dispatcher at startup"
```

---

## Task 6: Webhook Schemas + Admin API

**Files:**
- Create: `schemas/webhook.py`
- Create: `routers/api_v1/webhooks.py`
- Modify: `routers/api_v1/__init__.py`

- [ ] **Step 1: Create `schemas/webhook.py`**

```python
"""
Pydantic v2 schemas for the Webhook admin API.
"""
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator

from schemas.common import PaginatedResponse   # noqa: F401 — re-exported for callers


class WebhookCreateRequest(BaseModel):
    name: str
    url: str
    secret: str              # raw signing secret — hashed before storage, never returned
    event_types: list[str]
    is_active: bool = True


class WebhookListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    url: str
    event_types: list[str]
    is_active: bool
    created_by: str
    created_at: str

    @field_validator("id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v) if v is not None else v

    @field_validator("created_at", mode="before")
    @classmethod
    def dt_to_str(cls, v):
        return v.isoformat() if hasattr(v, "isoformat") else str(v)


class EventLogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    payload: dict
    source_module: Optional[str] = None
    published_at: str
    webhook_attempts: int
    last_attempt_at: Optional[str] = None
    last_status_code: Optional[int] = None

    @field_validator("id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v) if v is not None else v

    @field_validator("published_at", "last_attempt_at", mode="before")
    @classmethod
    def dt_to_str(cls, v):
        return v.isoformat() if v and hasattr(v, "isoformat") else v
```

- [ ] **Step 2: Create `routers/api_v1/webhooks.py`**

```python
"""
Admin CRUD for webhooks — uses session cookie auth (browser admin panel).
POST   /api/v1/webhooks                         create new webhook
GET    /api/v1/webhooks                         list all non-deleted
DELETE /api/v1/webhooks/{webhook_id}            soft-delete
GET    /api/v1/webhooks/{webhook_id}/events     recent event_log entries
"""
from datetime import datetime
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
        db,
        action="WEBHOOK_CREATED",
        user=current_user,
        table_name="webhooks",
        record_id=str(webhook.id),
        new_value={
            "name": body.name,
            "url": body.url,
            "event_types": body.event_types,
        },
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
        select(Webhook)
        .where(Webhook.deleted_at.is_(None))
        .order_by(Webhook.created_at.desc())
    )
    return [WebhookListItem.model_validate(w) for w in result.scalars().all()]


@router.delete("/{webhook_id}", response_model=SuccessResponse)
async def delete_webhook(
    webhook_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    result = await db.execute(
        select(Webhook).where(
            Webhook.id == webhook_id,
            Webhook.deleted_at.is_(None),
        )
    )
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(
            status_code=404,
            detail="Webhook not found or already deleted",
        )

    webhook.is_active = False
    webhook.deleted_at = datetime.utcnow()

    await audit(
        db,
        action="WEBHOOK_DELETED",
        user=current_user,
        table_name="webhooks",
        record_id=str(webhook.id),
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
    # Verify webhook exists
    wh_result = await db.execute(
        select(Webhook).where(
            Webhook.id == webhook_id,
            Webhook.deleted_at.is_(None),
        )
    )
    webhook = wh_result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    # Return event_log rows whose event_type matches any of this webhook's subscriptions
    subscribed = webhook.event_types or []
    if not subscribed:
        return PaginatedResponse[EventLogItem](
            items=[], total=0, page=page, page_size=page_size, total_pages=1,
        )

    query = select(EventLog).where(EventLog.event_type.in_(subscribed))
    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar() or 0
    logs_result = await db.execute(
        query.order_by(EventLog.published_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    logs = logs_result.scalars().all()
    total_pages = max(1, (total + page_size - 1) // page_size)
    return PaginatedResponse[EventLogItem](
        items=[EventLogItem.model_validate(e) for e in logs],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
```

- [ ] **Step 3: Register the webhooks router in `routers/api_v1/__init__.py`**

The current content of `routers/api_v1/__init__.py` is:

```python
from fastapi import APIRouter
from .health import router as health_router
from .devices import router as devices_router
from .lots import router as lots_router
from .sales import router as sales_router
from .spare_parts import router as spare_parts_router
from .iqc import router as iqc_router
from .api_keys import router as api_keys_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(devices_router)
router.include_router(lots_router)
router.include_router(sales_router)
router.include_router(spare_parts_router)
router.include_router(iqc_router)
router.include_router(api_keys_router)
```

Add the webhooks router:

```python
from fastapi import APIRouter
from .health import router as health_router
from .devices import router as devices_router
from .lots import router as lots_router
from .sales import router as sales_router
from .spare_parts import router as spare_parts_router
from .iqc import router as iqc_router
from .api_keys import router as api_keys_router
from .webhooks import router as webhooks_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(devices_router)
router.include_router(lots_router)
router.include_router(sales_router)
router.include_router(spare_parts_router)
router.include_router(iqc_router)
router.include_router(api_keys_router)
router.include_router(webhooks_router)
```

- [ ] **Step 4: Verify route count**

```
python -c "
from main import app
api_v1 = [r.path for r in app.routes if r.path.startswith('/api/v1')]
print(f'/api/v1 routes: {len(api_v1)}')
for r in sorted(api_v1): print(' ', r)
"
```
Expected: `/api/v1 routes: 19` (15 from Sprint 17a + 4 new webhook routes)

- [ ] **Step 5: Commit**

```bash
git add schemas/webhook.py routers/api_v1/webhooks.py routers/api_v1/__init__.py
git commit -m "feat(api-v1): webhook admin CRUD + event log view — 4 new routes"
```

---

## Task 7: Wire LOT_CREATED and SALE_COMPLETED into HTML Routers

**Files:**
- Modify: `routers/stock.py`
- Modify: `routers/sales.py`

- [ ] **Step 1: Wire `LOT_CREATED` into `routers/stock.py`**

In `routers/stock.py`, modify the import line for `fastapi`:

```python
# OLD:
from fastapi import APIRouter, Depends, Form, Query, Request, HTTPException
# NEW:
from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, Request, HTTPException
```

Add after the existing service imports:
```python
from services.event_bus import EventType, publish
```

Update the `create_lot` function signature to add `background_tasks: BackgroundTasks` as the second parameter (after `request`):

```python
@router.post("/lots/new")
async def create_lot(
    request: Request,
    background_tasks: BackgroundTasks,
    lot_number: str = Form(...),
    # ... rest of Form params unchanged ...
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
```

After `await db.commit()` (line 194) and before the `if crm_deal_id` redirect block, add:

```python
    await db.commit()

    publish(EventType.LOT_CREATED, {
        "lot_id": str(lot.id),
        "lot_number": lot.lot_number,
        "supplier": supplier_name,
        "qty": qty,
        "buying_price": buying_price,
        "_source": "stock_html",
    }, background_tasks)

    if crm_deal_id and crm_deal_id.strip():
```

- [ ] **Step 2: Wire `SALE_COMPLETED` into `routers/sales.py`**

In `routers/sales.py`, modify the fastapi import:

```python
# OLD:
from fastapi import APIRouter, Depends, Form, Request, HTTPException, Query
# NEW:
from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request, HTTPException, Query
```

Add after the existing service imports:
```python
from services.event_bus import EventType, publish
```

Update the `create_sale` function signature:

```python
@router.post("/sales/new")
async def create_sale(
    request: Request,
    background_tasks: BackgroundTasks,
    barcode: str = Form(...),
    # ... rest of Form params unchanged ...
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
```

After `await db.commit()` (line 184) and before the redirect, add:

```python
    await db.commit()

    publish(EventType.SALE_COMPLETED, {
        "sale_number": sale_num,
        "barcode": barcode,
        "price": str(price),
        "customer_name": customer_name or None,
        "sold_by": current_user.username,
        "_source": "sales_html",
    }, background_tasks)

    redirect = f"/sales?success=Sale+{sale_num}+recorded"
```

- [ ] **Step 3: Verify the app still imports cleanly**

```
python -c "from main import app; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add routers/stock.py routers/sales.py
git commit -m "feat(events): publish LOT_CREATED + SALE_COMPLETED from HTML lot/sale routes"
```

---

## Task 8: Tests

**Files:**
- Test: `tests/test_webhook_api.py`

> `tests/test_event_bus.py` and `tests/test_webhook_dispatcher.py` were written in Tasks 1 and 4. This task adds integration tests for the webhook API layer.

- [ ] **Step 1: Create `tests/test_webhook_api.py`**

```python
"""
Integration tests for /api/v1/webhooks/* endpoints.
All routes use session-cookie auth — no session → redirect to /auth/login (307).
"""
import pytest
from httpx import AsyncClient, ASGITransport
from main import app


async def test_webhooks_list_requires_session():
    """GET /api/v1/webhooks without session → redirect (307) or 401/403."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as c:
        resp = await c.get("/api/v1/webhooks")
    assert resp.status_code in (307, 401, 403)


async def test_webhook_create_requires_session():
    """POST /api/v1/webhooks without session → redirect."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as c:
        resp = await c.post(
            "/api/v1/webhooks",
            json={
                "name": "Test Hook",
                "url": "https://example.com/webhook",
                "secret": "s3cr3t",
                "event_types": ["DEVICE_REGISTERED"],
            },
        )
    assert resp.status_code in (307, 401, 403)


async def test_webhook_delete_requires_session():
    """DELETE /api/v1/webhooks/{id} without session → redirect."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as c:
        resp = await c.delete("/api/v1/webhooks/00000000-0000-0000-0000-000000000000")
    assert resp.status_code in (307, 401, 403)


async def test_webhook_events_requires_session():
    """GET /api/v1/webhooks/{id}/events without session → redirect."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as c:
        resp = await c.get("/api/v1/webhooks/00000000-0000-0000-0000-000000000000/events")
    assert resp.status_code in (307, 401, 403)


async def test_webhook_schema_create_request_valid():
    """WebhookCreateRequest schema accepts valid input."""
    from schemas.webhook import WebhookCreateRequest
    req = WebhookCreateRequest(
        name="My Hook",
        url="https://example.com/wh",
        secret="supersecret",
        event_types=["DEVICE_REGISTERED", "SALE_COMPLETED"],
    )
    assert req.name == "My Hook"
    assert req.event_types == ["DEVICE_REGISTERED", "SALE_COMPLETED"]
    assert req.is_active is True


async def test_webhook_schema_list_item_uuid_coercion():
    """WebhookListItem coerces UUID to str and datetime to isoformat."""
    import uuid
    from datetime import datetime
    from schemas.webhook import WebhookListItem

    item = WebhookListItem.model_validate({
        "id": uuid.uuid4(),
        "name": "Hook",
        "url": "https://example.com",
        "event_types": ["LOT_CREATED"],
        "is_active": True,
        "created_by": "admin",
        "created_at": datetime(2026, 4, 30, 12, 0, 0),
    })
    assert isinstance(item.id, str)
    assert "2026" in item.created_at


async def test_event_log_schema_optional_fields():
    """EventLogItem handles None optional fields."""
    import uuid
    from datetime import datetime
    from schemas.webhook import EventLogItem

    item = EventLogItem.model_validate({
        "id": uuid.uuid4(),
        "event_type": "DEVICE_REGISTERED",
        "payload": {"barcode": "OXY-001"},
        "source_module": None,
        "published_at": datetime(2026, 4, 30),
        "webhook_attempts": 0,
        "last_attempt_at": None,
        "last_status_code": None,
    })
    assert item.source_module is None
    assert item.last_attempt_at is None
    assert item.webhook_attempts == 0
```

- [ ] **Step 2: Run all Sprint 17b tests**

```
pytest tests/test_event_bus.py tests/test_webhook_dispatcher.py tests/test_webhook_api.py -v
```
Expected: **17 passed** (5 + 5 + 7)

- [ ] **Step 3: Run the full test suite to ensure nothing is broken**

```
pytest tests/ -v
```
Expected: all tests pass (28 from Sprint 17a + 17 from Sprint 17b = 45+ passing)

- [ ] **Step 4: Commit**

```bash
git add tests/test_webhook_api.py
git commit -m "test(sprint17b): webhook API integration tests + full suite passes"
```

---

## Self-Review

### 1. Spec Coverage

| Requirement | Task |
|---|---|
| EventType constants | Task 1 |
| subscribe / publish / _safe_call | Task 1 |
| `webhooks` table (all columns, soft-delete) | Task 2, 3 |
| `event_log` table (all columns, indexes) | Task 2, 3 |
| Alembic migration with indexes | Task 3 |
| load_active_webhooks | Task 4 |
| dispatch_webhook with HMAC-SHA256 + X-OxyPC-Signature | Task 4 |
| log_event / handle_event with own DB session | Task 4 |
| httpx 10s timeout | Task 4 |
| DEVICE_REGISTERED published from IQC API | Task 5 |
| STAGE_MOVED published from devices API | Task 5 |
| Dispatcher subscribed at startup | Task 5 |
| POST/GET/DELETE /api/v1/webhooks | Task 6 |
| GET /api/v1/webhooks/{id}/events | Task 6 |
| Secret hashed before storage, never returned | Task 6 |
| LOT_CREATED from stock.py create_lot | Task 7 |
| SALE_COMPLETED from sales.py create_sale | Task 7 |
| Tests: bus, dispatcher, webhook API | Tasks 1, 4, 8 |

All spec requirements covered.

### 2. Placeholder Scan

No placeholders found. All code blocks contain complete, runnable code.

### 3. Type Consistency

- `EventType.DEVICE_REGISTERED` (string `"DEVICE_REGISTERED"`) used consistently across event_bus, dispatcher, schemas, and publish calls.
- `_sign(payload_bytes: bytes, secret_hash: str) -> str` — called in `dispatch_webhook` with `body_bytes` (bytes) and `hook.secret_hash` (str). ✅
- `handle_event(event_type: str, payload: dict)` — registered via `subscribe(et, handle_event)` and called by the event bus with `(event_type: str, payload: dict)`. ✅
- `dispatch_webhook(hook, event_type, payload, timestamp, transport=None)` — called in `handle_event` with matching args. ✅
- `WebhookListItem.model_validate(webhook)` — `Webhook` ORM has all fields (`id`, `name`, `url`, `event_types`, `is_active`, `created_by`, `created_at`). ✅

---

## Tier 3 Preview (Sprint 17c)

After Sprint 17b is merged:
- `/api/v1/intelligence/*` — read-only device inventory snapshots, stage distributions, lot P&L summaries for AI layer
- Module capability registry — `app_settings` extension listing active modules, discoverable by ecosystem apps
- Finance outbound webhook — `SALE_COMPLETED` payload formatted as invoice for Tally/QuickBooks
- WhatsApp inbound — parse WA group messages → `market_availability` table (could be a webhook subscriber)
