"""Reliance Asset FieldOps — mounted at /fieldops.

A self-contained offline-first PWA (plain HTML/CSS/JS, no build step) for
demo-unit asset QC, commercial deduction, packing, pickup/courier movement,
warehouse receipt and 45-day project control.

The files live in fieldops_app/ at the project root, deliberately NOT under
static/ — that directory is mounted publicly by main.py, which would serve the
Reliance inventory (site names, RRP/MRP, commercial charges) to anyone without
a login. Everything is served through this router instead, so every request,
including js/inventory.js, requires an authenticated OxyPC session.

The app keeps its own state in the browser (localStorage) and talks to no
backend, so nothing here touches the OxyPC database.
"""

import os
from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_user
from database import get_db
from models.fieldops import FieldOpsRecord
from models.user import User
from utils.timezone import app_now

router = APIRouter(tags=["fieldops"])

# Collections the devices agree on. The 3,957-unit inventory master is NOT one
# of them: every device seeds it identically from js/inventory.js, so only what
# changes in the field has to travel.
SYNC_KINDS = {
    "qc", "commercial", "package", "movement", "receipt",
    "asset", "site", "user", "deduction", "rate_card", "audit",
}

# A device sends the cursor it got last time. Rewinding it a little on the way
# out means a record written in the same second as the previous response is
# never skipped; re-applying a record the device already has is a no-op.
PULL_OVERLAP = timedelta(seconds=5)

# Guard rails so one device cannot post an unbounded payload.
MAX_CHANGES_PER_PUSH = 500
MAX_PULL_RECORDS = 2000

BASE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fieldops_app"
)

# Explicit types: .webmanifest and .svg are not always in the system table.
_MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".webmanifest": "application/manifest+json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".md": "text/markdown; charset=utf-8",
}

# App code must revalidate, or a browser holding an hour-old copy keeps running
# the previous build after a deploy. The service worker is the caching layer
# here; only static media is allowed a long TTL.
_NO_CACHE = {".html", ".webmanifest", ".js", ".css", ".md"}


def _resolve(rel_path: str) -> str:
    """Map a request path to a file inside static/fieldops, refusing escapes."""
    full = os.path.normpath(os.path.join(BASE_DIR, rel_path))
    base = os.path.normpath(BASE_DIR)
    if not (full == base or full.startswith(base + os.sep)):
        raise HTTPException(status_code=404, detail="Not found")
    if not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="Not found")
    return full


def _serve(full_path: str) -> FileResponse:
    ext = os.path.splitext(full_path)[1].lower()
    headers = {}
    name = os.path.basename(full_path)
    if ext in _NO_CACHE or name == "sw.js":
        headers["Cache-Control"] = "no-cache"
    else:
        headers["Cache-Control"] = "public, max-age=3600"
    if name == "sw.js":
        # allow the worker to control the whole /fieldops/ path
        headers["Service-Worker-Allowed"] = "/fieldops/"
    return FileResponse(
        full_path,
        media_type=_MEDIA_TYPES.get(ext, "application/octet-stream"),
        headers=headers,
    )


class Change(BaseModel):
    kind: str
    id: str
    data: Dict[str, Any]
    updated_at: Optional[str] = None      # the device's own edit time
    deleted: bool = False


class SyncRequest(BaseModel):
    since: Optional[str] = None           # cursor from the previous response
    changes: List[Change] = Field(default_factory=list)


def _iso(dt) -> str:
    return dt.isoformat() if dt else ""


@router.post("/fieldops/api/sync")
async def fieldops_sync(
    payload: SyncRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Push this device's changes, pull everyone else's — one round trip.

    Records are last-write-wins on the device's own edit time, so a phone that
    was offline for an hour cannot overwrite a decision made since. QC records
    are append-only in the app itself (a correction is a new re-QC version), so
    the cases that actually matter never contend.
    """
    now = app_now()
    actor = getattr(current_user, "username", None) or str(getattr(current_user, "id", ""))

    if len(payload.changes) > MAX_CHANGES_PER_PUSH:
        raise HTTPException(
            status_code=413,
            detail=f"Too many changes in one push (max {MAX_CHANGES_PER_PUSH}).",
        )

    # ---------- push ----------
    accepted, rejected = 0, 0
    for change in payload.changes:
        if change.kind not in SYNC_KINDS:
            rejected += 1
            continue
        key = f"{change.kind}:{change.id}"
        existing = await db.get(FieldOpsRecord, key)
        if existing is None:
            db.add(
                FieldOpsRecord(
                    id=key,
                    kind=change.kind,
                    rec_id=change.id,
                    data=change.data,
                    updated_at=now,
                    updated_by=actor,
                    device_updated_at=change.updated_at,
                    deleted=bool(change.deleted),
                )
            )
            accepted += 1
        else:
            # Older edit than what the server already holds → drop it.
            if (
                change.updated_at
                and existing.device_updated_at
                and change.updated_at < existing.device_updated_at
            ):
                rejected += 1
                continue
            existing.data = change.data
            existing.updated_at = now
            existing.updated_by = actor
            existing.device_updated_at = change.updated_at
            existing.deleted = bool(change.deleted)
            accepted += 1

    if payload.changes:
        await db.flush()

    # ---------- pull ----------
    stmt = select(FieldOpsRecord)
    if payload.since:
        try:
            from datetime import datetime as _dt

            cursor = _dt.fromisoformat(payload.since)
            stmt = stmt.where(FieldOpsRecord.updated_at >= cursor - PULL_OVERLAP)
        except ValueError:
            pass  # unparseable cursor → treat as a full pull
    stmt = stmt.order_by(FieldOpsRecord.updated_at).limit(MAX_PULL_RECORDS + 1)

    rows = (await db.execute(stmt)).scalars().all()
    truncated = len(rows) > MAX_PULL_RECORDS
    rows = rows[:MAX_PULL_RECORDS]

    records = [
        {
            "kind": r.kind,
            "id": r.rec_id,
            "data": r.data,
            "deleted": r.deleted,
            "updated_at": _iso(r.updated_at),
            "updated_by": r.updated_by,
        }
        for r in rows
    ]

    # When the page was truncated, hand back the last row's time so the next
    # call continues from there rather than declaring itself up to date.
    cursor_out = _iso(rows[-1].updated_at) if (truncated and rows) else _iso(now)

    return {
        "server_time": _iso(now),
        "cursor": cursor_out,
        "accepted": accepted,
        "rejected": rejected,
        "records": records,
        "truncated": truncated,
        "user": {
            "username": getattr(current_user, "username", ""),
            "name": getattr(current_user, "full_name", "")
            or getattr(current_user, "username", ""),
            "role": str(getattr(getattr(current_user, "role", None), "value", "")
                        or getattr(current_user, "role", "")),
        },
    }


@router.get("/fieldops/api/status")
async def fieldops_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Small health/summary probe the app uses to show shared-store state."""
    from sqlalchemy import func

    total = (await db.execute(select(func.count(FieldOpsRecord.id)))).scalar() or 0
    by_kind = (
        await db.execute(
            select(FieldOpsRecord.kind, func.count(FieldOpsRecord.id)).group_by(
                FieldOpsRecord.kind
            )
        )
    ).all()
    latest = (
        await db.execute(select(func.max(FieldOpsRecord.updated_at)))
    ).scalar()
    return {
        "records": total,
        "by_kind": {k: c for k, c in by_kind},
        "last_change": _iso(latest),
        "server_time": _iso(app_now()),
    }


@router.get("/fieldops")
async def fieldops_root(current_user: User = Depends(get_current_user)):
    """The app uses relative asset paths, so it must run under a trailing slash."""
    return RedirectResponse(url="/fieldops/", status_code=307)


@router.get("/fieldops/")
async def fieldops_index(current_user: User = Depends(get_current_user)):
    return _serve(_resolve("index.html"))


@router.get("/fieldops/{asset_path:path}")
async def fieldops_asset(
    asset_path: str, current_user: User = Depends(get_current_user)
):
    if not asset_path or asset_path.endswith("/"):
        return _serve(_resolve("index.html"))
    return _serve(_resolve(asset_path))
