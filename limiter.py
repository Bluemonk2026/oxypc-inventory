"""SlowAPI rate-limiter singleton.

Imported by main.py (middleware setup) and routers/auth.py (login decorator).
Kept in a separate module to prevent circular imports.
"""
import hashlib
from slowapi import Limiter
from slowapi.util import get_remote_address


def _client_ip(request) -> str:
    """Real client IP, correct both behind Railway's proxy and on bare LAN.

    Behind a proxy, request.client.host is the *proxy's* IP — identical for every
    user of the app, which collapses everyone into one shared rate-limit bucket.
    X-Forwarded-For carries the chain instead.

    We take the RIGHTMOST entry, not the leftmost. Each hop *appends* the peer it
    actually saw, so the rightmost value is the one our own proxy wrote and is the
    only entry a client cannot forge — a caller who sends their own X-Forwarded-For
    only pollutes the left of the list. Reading the leftmost would let anyone
    bypass the 5/minute login limit by rotating a header value.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return get_remote_address(request)


def _key_func(request) -> str:
    """Rate-limit bucket: per logged-in session, falling back to per client IP.

    Staff sit behind one NAT'd office/warehouse IP *and* behind Railway's proxy, so
    an IP-only key means the entire company shares a single bucket — one person
    running a bulk action 429s everyone else. Keying authenticated traffic on the
    session token gives each user their own budget.

    The token is hashed, never used raw: this string ends up in the limiter's
    in-memory store and in logs, and the raw cookie is a live credential.

    Unauthenticated requests (notably POST /login) have no cookie and fall back to
    the client IP, which is what actually wants IP-scoped abuse protection.
    """
    token = request.cookies.get("access_token")
    if token:
        return "sess:" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]
    return "ip:" + _client_ip(request)


def ip_key_func(request) -> str:
    """Always-IP bucket, ignoring cookies. Use for pre-auth abuse limits.

    _key_func must NOT be used to throttle login: the cookie is attacker-controlled
    before authentication, so a brute-forcer could mint a fresh random access_token
    per attempt and land in a fresh bucket every time, nullifying the limit. Anything
    guarding an unauthenticated endpoint keys on the IP, which they cannot rotate.
    """
    return "ip:" + _client_ip(request)

# Default: 100 requests/minute per source IP across all routes.
#
# For an internal ERP with staff on a shared office/warehouse network (NAT'd
# to one public IP), this is a real bottleneck, not just abuse protection —
# 100 concurrent users behind the same IP will collectively exhaust 100
# req/min almost immediately during normal use (page load + a few AJAX calls
# each), and everyone starts getting silently 429'd. Raised the ceiling
# generously; the login endpoint (and a few external-facing customer-care /
# partner endpoints) keep their own much tighter per-route limits below,
# which is where actual abuse protection matters — this default is just a
# backstop against a single client hammering the server, not a capacity
# control for a trusted internal user base.
limiter = Limiter(key_func=_key_func, default_limits=["2000/minute"])
