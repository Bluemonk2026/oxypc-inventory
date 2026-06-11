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
limiter = Limiter(key_func=_key_func, default_limits=["100/minute"])
