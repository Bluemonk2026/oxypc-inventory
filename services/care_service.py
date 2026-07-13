"""Customer Care Agent — shared service logic (Phase 1 backend).

Ticket numbering, warranty resolution, diagnostic payload allowlisting, and
the care_audit_logs helper. Route handlers stay thin so the same logic backs
both the public /care/api/v1 surface and the internal staff screens (Phase 2).
"""
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.care import (
    CareSupportTicket, CareWarranty, CareAuditLog, CareDevicePairing,
    CareDispatchException, CareOffer, CareOfferDelivery,
)
from models.sales import Sale
from utils.timezone import app_now
from utils import warranty as warranty_utils

WA_SERVICE_URL = "http://localhost:3001"
WA_TIMEOUT = 8.0

PROVISIONING_TOKEN_TTL_MINUTES = 30
DEVICE_TOKEN_HEADER_MIN_LEN = 20

# ── Diagnostic allowlist (section 13 of the spec) — reject anything else ──
DIAGNOSTIC_ALLOWED_FIELDS = frozenset({
    "bios_serial", "manufacturer", "model", "cpu", "ram_gb", "storage_summary",
    "battery_health_pct", "battery_cycle_count", "smart_status", "os_version",
    "hardware_warning_summary", "system_error_summary",
})
MAX_DIAGNOSTIC_STRING_LEN = 2000
MAX_TICKET_DESCRIPTION_LEN = 2000
TICKET_CATEGORIES = frozenset({
    "hardware", "battery", "storage", "performance", "boot", "screen",
    "keyboard_touchpad", "software", "warranty_query", "accessory", "other",
})


class CareError(Exception):
    """Customer-safe error — message is shown as-is, never leaks internals."""
    def __init__(self, message: str, code: str = "CARE_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


# ── Ticket numbering (gap-safe, same max-suffix pattern as PO/TPL/TPB) ─────

async def next_ticket_number(db: AsyncSession) -> str:
    result = await db.execute(
        select(func.max(CareSupportTicket.ticket_number))
        .where(CareSupportTicket.ticket_number.like("CARE-%"))
    )
    mx = result.scalar()
    n = 1
    if mx:
        try:
            n = int(str(mx).rsplit("-", 1)[-1]) + 1
        except (ValueError, IndexError):
            n = 1
    return f"CARE-{n:04d}"


# ── Warranty resolution — care_warranties row wins; falls back to Sale ────

async def resolve_warranty(db: AsyncSession, device_id, sale_id=None) -> dict:
    """Return a customer-safe warranty summary dict. Prefers an explicit
    CareWarranty record (multi-coverage, replacement-aware); falls back to
    the existing Sale.warranty_type/warranty_expires_at (Phase 1a fields) so
    devices sold before this module existed still show correct status."""
    row = (await db.execute(
        select(CareWarranty).where(CareWarranty.device_id == device_id)
        .order_by(CareWarranty.created_at.desc()).limit(1)
    )).scalar_one_or_none()

    if row:
        now = app_now()
        days_left = None
        if row.expiry_date:
            days_left = max((row.expiry_date.date() - now.date()).days, 0)
        return {
            "status": row.status,
            "start_date": row.start_date,
            "expiry_date": row.expiry_date,
            "battery_expiry_date": row.battery_expiry_date,
            "days_left": days_left,
            "coverage_type": row.coverage_type,
        }

    # Fallback: derive from the sale record directly
    sale = None
    if sale_id:
        sale = await db.get(Sale, sale_id)
    if not sale:
        sale = (await db.execute(
            select(Sale).where(Sale.device_id == device_id).order_by(Sale.sold_at.desc()).limit(1)
        )).scalar_one_or_none()

    if not sale:
        return {"status": "not_started", "start_date": None, "expiry_date": None,
                "battery_expiry_date": None, "days_left": None, "coverage_type": None}

    status = warranty_utils.warranty_status_for_sale(sale)
    now = app_now()
    expiry = sale.warranty_expires_at
    days_left = max((expiry.date() - now.date()).days, 0) if expiry and now <= expiry else 0
    mapped_status = {"in_warranty": "active", "out_of_warranty": "expired",
                     "no_warranty": "not_started"}.get(status, "not_started")
    return {
        "status": mapped_status,
        "start_date": sale.sold_at,
        "expiry_date": expiry,
        "battery_expiry_date": None,
        "days_left": days_left,
        "coverage_type": "main_device",
    }


# ── Diagnostic payload validation ──────────────────────────────────────────

def validate_diagnostic_payload(payload: dict) -> dict:
    """Strip to the allowlist, reject unexpected keys, enforce length caps.
    Raises CareError on any field exceeding limits or containing a disallowed key."""
    if not isinstance(payload, dict):
        raise CareError("Diagnostic payload must be a JSON object", "CARE_INVALID_PAYLOAD")
    unknown = set(payload.keys()) - DIAGNOSTIC_ALLOWED_FIELDS
    if unknown:
        raise CareError(f"Diagnostic payload contains unsupported fields: {sorted(unknown)}",
                        "CARE_UNKNOWN_FIELDS")
    clean = {}
    for k, v in payload.items():
        if isinstance(v, str) and len(v) > MAX_DIAGNOSTIC_STRING_LEN:
            raise CareError(f"Field '{k}' exceeds maximum length", "CARE_PAYLOAD_TOO_LARGE")
        clean[k] = v
    return clean


def validate_ticket_description(description: str) -> str:
    description = (description or "").strip()
    if not description:
        raise CareError("Description is required", "CARE_MISSING_DESCRIPTION")
    if len(description) > MAX_TICKET_DESCRIPTION_LEN:
        raise CareError("Description is too long", "CARE_DESCRIPTION_TOO_LONG")
    return description


def validate_category(category: str) -> str:
    category = (category or "").strip().lower()
    if category not in TICKET_CATEGORIES:
        raise CareError(f"Unknown category '{category}'", "CARE_INVALID_CATEGORY")
    return category


# ── Audit (separate from the internal staff audit_logs table) ────────────

async def care_audit(
    db: AsyncSession, action: str, actor_type: str = "customer",
    actor_id: Optional[str] = None, pairing_id=None, ticket_id=None,
    old_value=None, new_value=None, ip_hash: Optional[str] = None,
):
    db.add(CareAuditLog(
        action=action, actor_type=actor_type, actor_id=actor_id,
        pairing_id=pairing_id, ticket_id=ticket_id,
        old_value=old_value, new_value=new_value, ip_hash=ip_hash,
    ))


async def has_pending_or_active_pairing(db: AsyncSession, device_id) -> bool:
    """A pairing stays is_active=False until the agent redeems it (spec 4.1
    step 7-8) — checking only is_active would let staff create unlimited
    duplicate PENDING pairings for the same device before the first one is
    ever redeemed. Also treats an unexpired, unredeemed provisioning token
    as blocking a second one."""
    row = (await db.execute(
        select(CareDevicePairing).where(
            CareDevicePairing.device_id == device_id,
            CareDevicePairing.revoked_at.is_(None),
        ).where(
            (CareDevicePairing.is_active == True) |  # noqa: E712
            ((CareDevicePairing.provisioning_redeemed_at.is_(None)) &
             (CareDevicePairing.provisioning_token_expires_at > app_now()))
        )
    )).scalar_one_or_none()
    return row is not None


# ── Dispatch readiness (Phase 4, spec section 16) — advisory only ─────────
# NOT wired into routers/sales.py or routers/dispatch.py as a hard block:
# no imaging tooling calls POST /care/internal/pairings automatically yet,
# so every device in production currently has zero pairings. A hard gate
# here today would fail every live sale. This becomes a real gate only once
# imaging integration (still a scoped plan, docs/care-agent/phase4-*.md)
# actually provisions units before they reach this check.

async def resolve_dispatch_readiness(db: AsyncSession, device_id) -> dict:
    """Returns {"ready": bool, "reason": str} — never raises, always safe to
    call from an advisory banner."""
    pairing = (await db.execute(
        select(CareDevicePairing).where(
            CareDevicePairing.device_id == device_id,
            CareDevicePairing.is_active == True,  # noqa: E712
            CareDevicePairing.paired_at.isnot(None),
        )
    )).scalar_one_or_none()
    if pairing:
        return {"ready": True, "reason": "active_pairing"}

    exception = (await db.execute(
        select(CareDispatchException).where(
            CareDispatchException.device_id == device_id,
            CareDispatchException.is_active == True,  # noqa: E712
        ).order_by(CareDispatchException.created_at.desc())
    )).scalar_one_or_none()
    if exception and (not exception.expires_at or exception.expires_at > app_now()):
        return {"ready": True, "reason": f"exception:{exception.reason}"}

    return {"ready": False, "reason": "no_pairing_no_exception"}


# ── Offer targeting + delivery (Phase 5, spec sections 4.5, 19.4) ─────────

async def resolve_offer_targets(db: AsyncSession, offer: CareOffer) -> list:
    """Returns a list of (device_id, sale_id) tuples matching the offer's
    targeting rule. Only ever reads — sending is a separate, explicit step."""
    query = (
        select(CareDevicePairing.device_id, CareDevicePairing.sale_id)
        .where(CareDevicePairing.is_active == True)  # noqa: E712
    )

    if offer.target_type == "all":
        pass
    elif offer.target_type == "model":
        from models.device import Device
        query = query.join(Device, Device.id == CareDevicePairing.device_id).where(
            Device.model == offer.target_value
        )
    elif offer.target_type == "warranty_window":
        # target_value = "<=days" e.g. "30" meaning warranty expiring within 30 days
        try:
            days = int(offer.target_value)
        except (TypeError, ValueError):
            return []
        cutoff = app_now() + timedelta(days=days)
        query = query.join(CareWarranty, CareWarranty.device_id == CareDevicePairing.device_id).where(
            CareWarranty.expiry_date.isnot(None), CareWarranty.expiry_date <= cutoff,
            CareWarranty.expiry_date >= app_now(),
        )
    elif offer.target_type == "sale_range":
        # target_value = "YYYY-MM-DD,YYYY-MM-DD"
        try:
            start_s, end_s = (offer.target_value or "").split(",")
            start_dt = datetime.strptime(start_s.strip(), "%Y-%m-%d")
            end_dt = datetime.strptime(end_s.strip(), "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            return []
        query = query.join(Sale, Sale.id == CareDevicePairing.sale_id).where(
            Sale.sold_at >= start_dt, Sale.sold_at < end_dt,
        )
    else:
        return []

    rows = (await db.execute(query.limit(5000))).all()
    return [(r.device_id, r.sale_id) for r in rows]


async def send_offer_whatsapp(phone: str, message: str, staff_username: str) -> tuple:
    """Reuses the same wa-service bridge pattern as routers/whatsapp.py's
    _wa() helper — deliberately not importing from a router module, so this
    stays callable from care_service without a routers->routers dependency.
    Returns (status_code, response_dict)."""
    try:
        async with httpx.AsyncClient(timeout=WA_TIMEOUT) as c:
            r = await c.post(f"{WA_SERVICE_URL}/send", json={
                "phone": phone, "message": message, "user": staff_username,
            })
            return r.status_code, r.json()
    except Exception as e:
        return 0, {"error": str(e)}


async def record_offer_delivery(db: AsyncSession, offer_id, device_id, channel: str,
                                status: str, error_message: str = None, sent_by: str = None):
    db.add(CareOfferDelivery(
        offer_id=offer_id, device_id=device_id, channel=channel,
        delivery_status=status, error_message=error_message, sent_by=sent_by,
    ))
