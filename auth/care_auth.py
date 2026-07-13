"""Customer Care Agent authentication — device-bound bearer token.

No customer account/password exists. The desktop agent authenticates every
call with `Authorization: Bearer <device-token>`, resolved against
`care_device_pairings.device_token_hash`. This is deliberately NOT a JWT —
there is no session to expire; the token is long-lived and revoked (not
expired) when the device is re-imaged, returned, or bought back.

Every route using get_current_pairing() must scope all queries to the
returned pairing's device_id/sale_id — never accept an arbitrary id from
the client (object-level authorisation, not just authentication).
"""
import hashlib
from datetime import datetime
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.care import CareDevicePairing
from utils.timezone import app_now


def _extract_bearer(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    return token or None


def _hash_ip(request: Request) -> Optional[str]:
    ip = request.client.host if request.client else None
    if not ip:
        return None
    return hashlib.sha256(ip.encode()).hexdigest()


async def get_current_pairing(
    request: Request,
    authorization: str = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> CareDevicePairing:
    """Resolve the authenticated device pairing. Raises 401 on any failure —
    never distinguishes "unknown token" from "revoked token" in the response
    (avoids leaking pairing state to an attacker probing tokens)."""
    raw = _extract_bearer(authorization)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing Authorization: Bearer <device-token> header")

    token_hash = CareDevicePairing.hash_token(raw)
    result = await db.execute(
        select(CareDevicePairing).where(
            CareDevicePairing.device_token_hash == token_hash,
            CareDevicePairing.is_active == True,  # noqa: E712
            CareDevicePairing.revoked_at.is_(None),
        )
    )
    pairing = result.scalar_one_or_none()
    if not pairing:
        raise HTTPException(status_code=401, detail="Invalid or revoked device token")

    # Non-critical bookkeeping — never fail the request over it
    try:
        await db.execute(
            update(CareDevicePairing)
            .where(CareDevicePairing.id == pairing.id)
            .values(last_seen_at=app_now(), last_ip_hash=_hash_ip(request))
        )
        await db.commit()
    except Exception:
        await db.rollback()

    return pairing
