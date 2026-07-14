"""SlowAPI rate-limiter singleton.

Imported by main.py (middleware setup) and routers/auth.py (login decorator).
Kept in a separate module to prevent circular imports.

Reverse proxy support:
  Set OXYPC_TRUSTED_PROXY=1 in the environment when running behind nginx/Cloudflare.
  This reads the client IP from X-Forwarded-For instead of the TCP connection.
"""
import os
from slowapi import Limiter
from slowapi.util import get_remote_address, get_ipaddr

# When behind a reverse proxy (nginx, Cloudflare, AWS ALB), X-Forwarded-For carries
# the real client IP. Set OXYPC_TRUSTED_PROXY=1 to use it.
_behind_proxy = os.environ.get("OXYPC_TRUSTED_PROXY", "0") == "1"
_key_func = get_ipaddr if _behind_proxy else get_remote_address

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
