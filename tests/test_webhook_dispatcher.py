"""
Tests for the webhook dispatcher service.
Uses httpx.MockTransport to intercept outbound HTTP calls.
"""
import hashlib
import hmac
import json
from unittest.mock import MagicMock

import httpx
import pytest


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
