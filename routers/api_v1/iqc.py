"""
JSON API — IQC Registration (OxyQC EXE protocol)
POST /api/v1/iqc/register   → creates Device + IQCInspection + StageMovement + audit log
GET  /api/v1/iqc/lookup?barcode=OXY-001  → quick device lookup by barcode

The HTML route at POST /iqc/new is UNCHANGED — this is a parallel JSON endpoint.
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.device import Device, DeviceStage, StageMovement
from models.lot import Lot, LotLineItem
from models.iqc_inspection import IQCInspection
from models.api_key import APIKey
from auth.api_key import require_scope
from schemas.iqc import IQCRegisterRequest
from schemas.common import SuccessResponse
from schemas.device import DeviceOut
from services.audit_engine import audit
from services.event_bus import EventType, publish

router = APIRouter(prefix="/iqc", tags=["api-v1-iqc"])


@router.post("/register", response_model=SuccessResponse, status_code=201)
async def register_device(
    body: IQCRegisterRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_scope("iqc:write")),
):
    """
    OxyQC EXE submits IQC data as JSON.
    Equivalent to the browser form at POST /iqc/new.
    """
    # Duplicate barcode check
    existing = await db.execute(select(Device).where(Device.barcode == body.barcode))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Barcode '{body.barcode}' already registered")

    device = Device(
        barcode=body.barcode,
        lot_id=body.lot_id,
        sub_category=body.sub_category,
        brand=body.brand,
        model=body.model,
        device_type=body.device_type,
        serial_no=body.serial_no,
        grn_number=body.grn_number,
        cpu=body.cpu,
        generation=body.generation,
        ram_gb=body.ram_gb,
        storage_gb=body.storage_gb,
        storage_type=body.storage_type,
        hdd_capacity_gb=body.hdd_capacity_gb,
        screen_size=body.screen_size,
        battery_health_pct=body.battery_health_pct,
        bios_password=body.bios_password or False,
        color=body.color,
        grade=body.grade,
        floor=body.floor,
        warehouse=body.warehouse,
        notes=body.notes,
        lot_line_item_id=body.lot_line_item_id or None,
        current_stage=DeviceStage.iqc,
    )

    # Auto-price from LotLineItem or lot average (same logic as HTML route in routers/iqc.py)
    if body.lot_line_item_id:
        li_r = await db.execute(select(LotLineItem).where(LotLineItem.id == body.lot_line_item_id))
        li = li_r.scalar_one_or_none()
        if li and li.unit_price:
            device.device_price = float(li.unit_price)
    if not device.device_price:
        lot_r = await db.execute(select(Lot).where(Lot.id == body.lot_id))
        lot_obj = lot_r.scalar_one_or_none()
        if lot_obj and lot_obj.buying_price and lot_obj.qty:
            device.device_price = float(lot_obj.buying_price / lot_obj.qty)

    db.add(device)
    await db.flush()  # get device.id before adding inspection

    # Physical inspection (mirror routers/iqc.py IQCInspection creation)
    inspector = body.inspector_name or f"api_key:{api_key.name}"
    insp_kwargs: dict = {}
    if body.inspection:
        insp_kwargs = {
            k: v for k, v in body.inspection.model_dump().items()
            if v is not None
        }

    inspection = IQCInspection(
        device_id=device.id,
        inspector_name=inspector,
        **insp_kwargs,
    )
    db.add(inspection)

    movement = StageMovement(
        device_id=device.id,
        from_stage=None,
        to_stage=DeviceStage.iqc,
        moved_by=f"api_key:{api_key.name}",
        notes="IQC Entry via OxyQC API",
    )
    db.add(movement)

    # Fake request object for audit_engine (uses client.host)
    class _FakeClient:
        host = "api_key"

    class _FakeRequest:
        client = _FakeClient()

    await audit(
        db,
        action="DEVICE_IQC_REGISTERED_API",
        user=None,
        table_name="devices",
        record_id=str(device.id),
        new_value={
            "barcode": body.barcode,
            "lot_id": str(body.lot_id),
            "brand": body.brand,
            "model": body.model,
            "grade": body.grade,
            "api_key": api_key.name,
        },
        request=_FakeRequest(),
    )
    await db.commit()
    publish(EventType.DEVICE_REGISTERED, {
        "barcode": body.barcode,
        "lot_id": str(body.lot_id),
        "brand": body.brand,
        "model": body.model,
        "grade": body.grade,
        "_source": "iqc_api",
    }, background_tasks)
    return SuccessResponse(message="Device registered successfully", id=str(device.id))


@router.get("/lookup", response_model=DeviceOut)
async def lookup_device(
    barcode: str,
    db: AsyncSession = Depends(get_db),
    _key: APIKey = Depends(require_scope("iqc:read")),
):
    """Fast barcode lookup — returns full device detail or 404."""
    result = await db.execute(select(Device).where(Device.barcode == barcode))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail=f"Device '{barcode}' not found")
    return DeviceOut.model_validate(device)
