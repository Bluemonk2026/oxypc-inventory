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

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from auth.dependencies import get_current_user
from models.user import User

router = APIRouter(tags=["fieldops"])

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

# Never revalidate-free: the shell and the worker must pick up new deploys.
_NO_CACHE = {".html", ".webmanifest"}


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
