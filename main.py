import asyncio
import sys
import os
import webbrowser
import threading
import time
import logging
import traceback as _tb

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import ProgrammingError, DataError, DBAPIError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from limiter import limiter

from config import APP_HOST, APP_PORT, APP_NAME, write_default_config, ALLOWED_ORIGINS

# Debug mode — set OXYPC_DEBUG=1 to show full exception detail in error pages (LAN dev only)
DEBUG = os.environ.get("OXYPC_DEBUG", "0") == "1"

# Write default config on first run
if not os.path.exists(os.path.join(os.path.dirname(__file__), "config.ini")):
    write_default_config()

app = FastAPI(title=APP_NAME, version="1.0.0")

# Rate limiting — global default: 100/min per IP; login is overridden to 5/min
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ── CORS — ecosystem apps (Customer Portal, AI Layer, ESG, Finance) ───────────
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
    expose_headers=["X-Total-Count"],
    max_age=600,
)

# ── HTTPS redirect — Railway terminates SSL at the edge and sets
# X-Forwarded-Proto: http for plain-HTTP requests.  Redirect them to HTTPS.
# Does not fire on local dev because the header is absent. ───────────────────
@app.middleware("http")
async def _force_https(request: Request, call_next):
    if request.headers.get("x-forwarded-proto") == "http":
        url = str(request.url).replace("http://", "https://", 1)
        return RedirectResponse(url=url, status_code=301)
    return await call_next(request)

# ── Error logger (writes to errors.log next to main.py) ───────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_err_logger = logging.getLogger("oxypc.errors")
_err_logger.setLevel(logging.ERROR)
_err_handler = logging.FileHandler(os.path.join(BASE_DIR, "errors.log"), encoding="utf-8")
_err_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_err_logger.addHandler(_err_handler)
if not logging.getLogger().handlers:          # also echo to console if no root handler
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s")

# Static files
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# Uploads directory — CRM file attachments (product records, etc.)
_uploads_dir = os.path.join(BASE_DIR, "uploads")
os.makedirs(os.path.join(_uploads_dir, "crm"), exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_uploads_dir), name="uploads")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Import and include all routers
from routers.health import router as health_router
from routers.auth import router as auth_router
from routers.dashboard import router as dashboard_router
from routers.admin import router as admin_router
from routers.iqc import router as iqc_router
from routers.stock import router as stock_router
from routers.repair import router as repair_router
from routers.qc import router as qc_router
from routers.sales import router as sales_router
from routers.spare_parts import router as spare_parts_router
from routers.reports import router as reports_router
from routers.master import router as master_router
import models.role_permissions  # ensures tables are in Base.metadata for db_validator
import models.ticket  # ensures tickets table is created on startup
from routers.bulk_upload import router as bulk_upload_router
from routers.cosmetic import router as cosmetic_router
from routers.workid_status import router as workid_status_router
from routers.scrap import router as scrap_router
from routers.devices import router as devices_router
from routers.transfers import router as transfers_router
from routers.part_requests import router as part_requests_router
from routers.dispatch import router as dispatch_router
from routers.model_requests import router as model_requests_router
import models.model_requests  # ensure model_requests table is in Base.metadata
from routers.attendance import router as attendance_router
from routers.telesales_dashboard import router as telesales_dashboard_router
from routers.dealers import router as dealers_router
from routers.telecalling import router as telecalling_router
from routers.m_telecalling import router as m_telecalling_router
from routers.whatsapp import router as whatsapp_router
from routers.grn import router as grn_router
from routers.parts_grn import router as parts_grn_router
import models.parts_grn  # ensure parts_grn tables are in Base.metadata
from routers.stage_control import router as stage_control_router
from routers.market import router as market_router
from routers.inventory_location import router as inventory_location_router
from routers.stress_api import router as stress_api_router
from routers.iqc_api import router as iqc_api_router
from routers.qa_uat import router as qa_uat_router
from routers.crm_dashboard import router as crm_dashboard_router
from routers.crm_contacts import router as crm_contacts_router
from routers.crm_sourcing import router as crm_sourcing_router
from routers.crm_sales import router as crm_sales_router
from routers.crm_quotes import router as crm_quotes_router
from routers.crm_activities import router as crm_activities_router
from routers.crm_price_matrix import router as crm_price_matrix_router
from routers.invoices import router as invoices_router
from routers.crm_purchase_orders import router as crm_purchase_orders_router
from routers.accounts import router as accounts_router
from routers.crm_reports import router as crm_reports_router
from routers.crm_assign_leads import router as crm_assign_leads_router
from routers.assign_dealer_leads import router as assign_dealer_leads_router
from routers.tickets import router as tickets_router
from routers.settings import router as settings_router
from routers.trash import router as trash_router
from routers.notifications import router as notifications_router
from routers.manuals import router as manuals_router
from routers.landing_pages import router as landing_pages_router
from routers.buckets import router as buckets_router
from routers.api import router as api_router
from routers.api_v1 import router as api_v1_router
from services.event_bus import subscribe, EventType
from services.webhook_dispatcher import handle_event

app.include_router(api_v1_router)
app.include_router(api_router)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(admin_router)
app.include_router(iqc_router)
app.include_router(stock_router)
app.include_router(repair_router)
app.include_router(qc_router)
app.include_router(sales_router)
app.include_router(spare_parts_router)
app.include_router(reports_router)
app.include_router(master_router)
app.include_router(bulk_upload_router)
app.include_router(cosmetic_router)
app.include_router(workid_status_router)
app.include_router(scrap_router)
app.include_router(devices_router)
app.include_router(transfers_router)
app.include_router(part_requests_router)
app.include_router(dispatch_router)
app.include_router(model_requests_router)
app.include_router(attendance_router)
app.include_router(telesales_dashboard_router)
app.include_router(dealers_router)
app.include_router(telecalling_router)
app.include_router(m_telecalling_router)
app.include_router(whatsapp_router)
app.include_router(grn_router)
app.include_router(parts_grn_router)
app.include_router(stage_control_router)
app.include_router(market_router)
app.include_router(inventory_location_router)
app.include_router(iqc_api_router)
app.include_router(qa_uat_router)
app.include_router(crm_dashboard_router)
app.include_router(crm_contacts_router)
app.include_router(crm_sourcing_router)
app.include_router(crm_sales_router)
app.include_router(crm_quotes_router)
app.include_router(crm_activities_router)
app.include_router(crm_price_matrix_router)
app.include_router(invoices_router)
app.include_router(crm_purchase_orders_router)
app.include_router(accounts_router)
app.include_router(crm_reports_router)
app.include_router(crm_assign_leads_router)
app.include_router(assign_dealer_leads_router)
app.include_router(tickets_router)
app.include_router(settings_router)
app.include_router(trash_router)
app.include_router(notifications_router)
app.include_router(manuals_router)
app.include_router(landing_pages_router)
app.include_router(stress_api_router)
app.include_router(buckets_router)


# ── Error UI: per-code message + solution, JSON for API/AJAX else HTML modal ──
_ERROR_INFO = {
    400: ("Bad Request", "The request was invalid or some fields were missing/incorrect.",
          "Go back, check the values you entered, and try again."),
    401: ("Not Signed In", "Your session expired or you are not logged in.",
          "Log in again to continue."),
    403: ("Access Denied", "You don't have permission to open this page or action.",
          "Ask an admin to enable it for your role in Master Data → Module Permissions, or go back."),
    404: ("Not Found", "The page or record you requested doesn't exist or was moved.",
          "Check the link, or go back and pick a valid item."),
    405: ("Action Not Allowed", "This action isn't allowed on this page.",
          "Go back and use the buttons/links provided on the page."),
    422: ("Invalid Input", "Some values weren't in the expected format.",
          "Correct the highlighted fields and submit again."),
    429: ("Too Many Requests", "You've sent too many requests in a short time.",
          "Wait a minute, then try again."),
    500: ("Something Went Wrong", "An unexpected error occurred on the server.",
          "Try again. If it keeps happening, note what you were doing and inform the admin."),
}


def _wants_json(request: Request) -> bool:
    """API / AJAX callers get JSON, not the HTML error modal."""
    p = request.url.path or ""
    if "/api/" in p:
        return True
    if any(p.endswith(s) for s in ("/usb-import", "/exists", "/brief")) \
       or any(s in p for s in ("/qr-poll", "/status-poll", "/sync-status",
                               "/groups/messages", "/groups/analytics", "/lookup")):
        return True
    accept = request.headers.get("accept", "")
    if "application/json" in accept and "text/html" not in accept:
        return True
    return request.headers.get("x-requested-with", "").lower() == "xmlhttprequest"


def _render_error(request: Request, code: int, message: str = None, detail: str = None):
    title, default_msg, solution = _ERROR_INFO.get(
        code, ("Error", "An error occurred.", "Go back and try again."))
    msg = message or default_msg
    if _wants_json(request):
        return JSONResponse({"error": msg, "code": code, "solution": solution}, status_code=code)
    return templates.TemplateResponse("error.html", {
        "request": request, "code": code, "title": title,
        "message": msg, "solution": solution, "detail": detail,
    }, status_code=code)


# Exception handlers
@app.exception_handler(302)
async def redirect_handler(request: Request, exc):
    resp = RedirectResponse(url=exc.headers.get("Location", "/auth/login"))
    resp.headers["Cache-Control"] = "no-store"  # never let a browser cache an auth redirect
    return resp


@app.exception_handler(403)
async def forbidden_handler(request: Request, exc):
    return _render_error(request, 403)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return _render_error(request, 404)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Catch-all for any HTTPException status not handled above (400/401/405/409/…)."""
    code = exc.status_code or 500
    if code in (301, 302, 307, 308):
        resp = RedirectResponse(url=(exc.headers or {}).get("Location", "/auth/login"))
        resp.headers["Cache-Control"] = "no-store"
        return resp
    detail_msg = exc.detail if isinstance(exc.detail, str) and exc.detail.strip() else None
    try:
        import http as _http
        generic_phrase = _http.HTTPStatus(code).phrase
    except Exception:
        generic_phrase = None
    # Show the developer-supplied detail as the message only if it's not the bare HTTP phrase
    message = detail_msg if (detail_msg and detail_msg != generic_phrase) else None
    return _render_error(request, code, message=message)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return _render_error(request, 400,
                         message="Some fields are missing or in the wrong format.",
                         detail=(str(exc.errors()) if DEBUG else None))


@app.exception_handler(DBAPIError)
async def db_api_error_handler(request: Request, exc: DBAPIError):
    msg = str(exc).lower()
    if ("invalid input" in msg and "uuid" in msg) or "invalid uuid" in msg:
        return _render_error(request, 404, message="The record you requested doesn't exist.")
    return _render_error(request, 500, message="A database error occurred.")


@app.exception_handler(ProgrammingError)
async def db_programming_error_handler(request: Request, exc: ProgrammingError):
    msg = str(exc).lower()
    if ("invalid input" in msg and "uuid" in msg) or "invalid uuid" in msg:
        return _render_error(request, 404, message="The record you requested doesn't exist.")
    return _render_error(request, 500, message="A database error occurred.")


@app.exception_handler(DataError)
async def db_data_error_handler(request: Request, exc: DataError):
    msg = str(exc).lower()
    if ("invalid input" in msg and "uuid" in msg) or "invalid uuid" in msg:
        return _render_error(request, 422, message="That identifier isn't in a valid format.")
    return _render_error(request, 500, message="A database error occurred.")


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    tb_str = _tb.format_exc()
    msg = f"\n{'='*60}\n500 {request.method} {request.url}\n{type(exc).__name__}: {exc}\n{tb_str}{'='*60}"
    # always print to console (visible in server terminal)
    print(msg, flush=True)
    # also write to log file
    try:
        _err_logger.error(msg)
    except Exception:
        pass
    return _render_error(request, 500, message="An unexpected error occurred.",
                         detail=(f"{type(exc).__name__}: {exc}" if DEBUG else None))


@app.on_event("startup")
async def startup_event():
    print(f"\n{'='*50}")
    print(f"  {APP_NAME} starting...")
    print(f"{'='*50}")

    # ── Schema validation + auto-fix (MUST run before serving requests) ────────
    # Checks every ORM table/column exists in the DB, fixes what it can,
    # and raises RuntimeError (aborting startup) if anything is unfixable.
    try:
        from database import engine as _engine
        from db_validator import validate_and_fix

        _auto_fix = os.environ.get("OXYPC_AUTO_FIX", "1") == "1"
        summary = await validate_and_fix(_engine, auto_fix=_auto_fix)

        if summary["issues_fixed"]:
            print(f"  [Schema] Auto-fixed {summary['issues_fixed']} issue(s):")
            for msg in summary["fixed"]:
                print(f"    + {msg}")
        else:
            print(f"  [Schema] OK  DB schema matches ORM models - no issues")

    except RuntimeError as exc:
        # Unrecoverable schema problem - log loudly and let uvicorn abort startup
        print(str(exc))
        raise
    except Exception as exc:
        # DB not reachable yet -warn but don't abort (connection errors surface on first request)
        print(f"  [Schema] WARNING: Could not validate schema: {exc}")

    # ── Load saved application timezone ──────────────────────────────────────
    try:
        from sqlalchemy import text as _text
        from utils.timezone import set_app_timezone as _set_tz
        async with _engine.connect() as _conn:
            _row = await _conn.execute(
                _text("SELECT value FROM app_settings WHERE key='app_timezone' LIMIT 1")
            )
            _tz_row = _row.fetchone()
            if _tz_row and _tz_row[0]:
                _set_tz(_tz_row[0])
                print(f"  [Timezone] Loaded from DB: {_tz_row[0]}")
            else:
                print("  [Timezone] Using default: Asia/Kolkata (IST)")
    except Exception as _tz_exc:
        print(f"  [Timezone] Could not load from DB: {_tz_exc} — using default")

    # ── Subscribe webhook dispatcher to all event types ───────────────────────
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

    # ── Warm permission cache from DB ─────────────────────────────────────────
    try:
        from routers.master import load_all_permissions_to_cache
        from database import AsyncSessionLocal as _ASL
        async with _ASL() as _sess:
            await load_all_permissions_to_cache(_sess)
        print("  [Perms] Role permission cache loaded")
    except Exception as _pe:
        print(f"  [Perms] Could not load permission cache: {_pe}")

    # ── Print startup banner ───────────────────────────────────────────────────
    print(f"\n  {APP_NAME} started successfully")
    print(f"  URL: http://localhost:{APP_PORT}")
    print(f"  LAN: http://<your-server-ip>:{APP_PORT}")
    print(f"  Default login: see config.ini or ask your administrator")
    print(f"{'='*50}\n")


def open_browser():
    time.sleep(1.5)
    webbrowser.open(f"http://localhost:{APP_PORT}")


if __name__ == "__main__":
    # Open browser only when explicitly requested (set OXYPC_OPEN_BROWSER=0 to disable)
    if os.environ.get("OXYPC_OPEN_BROWSER", "1") == "1":
        t = threading.Thread(target=open_browser, daemon=True)
        t.start()

    uvicorn.run(
        "main:app",
        host=APP_HOST,
        port=APP_PORT,
        reload=False,
        log_level="info",
        workers=1,          # single async worker — avoids stale in-memory caches (_PERM_CACHE, _transitions_cache) across forked processes
    )
