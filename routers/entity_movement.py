"""Entity Movement — card counts of devices per Entity (Deshwal / OxyPC
Computers / Renew Circuits) plus a bulk "Change Entities" tool: paste/upload
a list of Tag Numbers and reassign them to a different Entity in one go."""
import re
from templates_config import templates
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from models.user import User
from models.device import Device
from utils.master_data import master_values
from auth.dependencies import get_current_user, require_module_perm, verify_csrf
from services.audit_engine import audit

router = APIRouter(prefix="/entity-movement", tags=["entity_movement"], dependencies=[Depends(verify_csrf)])
allowed = require_module_perm("entity_movement")


def _parse_tags(raw: str) -> list[str]:
    tags = [t.strip() for t in re.split(r"[,\n\r]+", raw or "") if t.strip()]
    seen = set()
    out = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


@router.get("", response_class=HTMLResponse)
async def entity_movement_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    entity_values = await master_values(db, "entity") or ["Deshwal", "OxyPC Computers", "Renew Circuits"]
    counts = {}
    for e in entity_values:
        counts[e] = (await db.execute(
            select(func.count()).select_from(Device).where(
                Device.entity == e, Device.is_active == True, Device.is_trashed == False,  # noqa: E712
            )
        )).scalar() or 0
    unassigned = (await db.execute(
        select(func.count()).select_from(Device).where(
            Device.entity.is_(None), Device.is_active == True, Device.is_trashed == False,  # noqa: E712
        )
    )).scalar() or 0
    return templates.TemplateResponse("entity_movement/index.html", {
        "request": request, "current_user": current_user,
        "entity_values": entity_values, "counts": counts, "unassigned": unassigned,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@router.post("/change-entities")
async def change_entities(
    request: Request,
    tags: str = Form(""),
    entity: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allowed),
):
    barcodes = _parse_tags(tags)
    if not barcodes:
        return RedirectResponse(url="/entity-movement?error=No+Tag+Numbers+provided", status_code=302)

    devices = (await db.execute(select(Device).where(Device.barcode.in_(barcodes)))).scalars().all()
    found_barcodes = {d.barcode for d in devices}
    missing = [b for b in barcodes if b not in found_barcodes]

    for d in devices:
        d.entity = entity

    await audit(db, user=current_user, action="ENTITY_MOVEMENT_BULK_CHANGE",
                table_name="devices", record_id=None,
                new_value={"entity": entity, "tags": len(devices), "missing": len(missing)},
                request=request)
    await db.commit()

    msg = f"Entity changed to {entity} for {len(devices)} tag(s)"
    if missing:
        msg += f" — {len(missing)} tag(s) not found: {', '.join(missing[:10])}"
        if len(missing) > 10:
            msg += "…"
    return RedirectResponse(url=f"/entity-movement?success={msg}", status_code=302)
