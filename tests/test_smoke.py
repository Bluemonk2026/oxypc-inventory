"""
Smoke tests — verify the server is reachable and key pages return expected codes.
These are read-only tests; they do NOT modify any data.

Run: pytest tests/test_smoke.py -v
"""
import pytest


@pytest.mark.parametrize("path,expected", [
    ("/health", 200),
    ("/auth/login", 200),
    ("/", "3xx"),          # root redirects (login required) — FastAPI returns 307
    ("/admin/users", "3xx"),  # requires login
    ("/lots", "3xx"),         # requires login
])
def test_public_routes(app_client, path: str, expected):
    """Key routes should return the expected HTTP status without crashing."""
    response = app_client.get(path, follow_redirects=False)
    if expected == "3xx":
        assert 300 <= response.status_code < 400, (
            f"GET {path} returned {response.status_code}, expected a 3xx redirect"
        )
    else:
        assert response.status_code == expected, (
            f"GET {path} returned {response.status_code}, expected {expected}"
        )


def test_health_db_ok(app_client):
    """Health endpoint must report DB as ok."""
    response = app_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body.get("status") == "ok"
    assert body.get("db") == "ok"
