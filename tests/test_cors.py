import pytest
from httpx import AsyncClient, ASGITransport
from main import app


async def test_cors_preflight_from_allowed_origin():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert resp.status_code in (200, 204)
    assert "access-control-allow-origin" in resp.headers


async def test_cors_preflight_disallowed_origin():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.options(
            "/api/v1/health",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert "access-control-allow-origin" not in resp.headers
