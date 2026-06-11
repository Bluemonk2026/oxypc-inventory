"""
GET /api/v1/health  — public endpoint, no auth required.
Returns platform status + module-level sub-checks + stage counts.
Used by: uptime monitors, OxyQC EXE startup check, ecosystem app discovery.
"""
import time
from fastapi import APIRouter, Depends
from sqlalchemy import text, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.device import Device, DeviceStage

router = APIRouter(prefix="/health", tags=["api-v1-health"])

_start_time = time.time()

REGISTERED_MODULES = [
    "devices", "lots", "iqc", "sales", "spare_parts",
    "dealers", "crm_sourcing", "crm_sales", "repair",
    "qc", "whatsapp", "telecalling", "market",
]


@router.get("")
async def api_health(db: AsyncSession = Depends(get_db)):
    modules: dict = {}

    # 1 — Database connectivity
    try:
        await db.execute(text("SELECT 1"))
        modules["database"] = {"status": "ok"}
    except Exception as e:
        modules["database"] = {"status": "error", "detail": str(e)[:120]}

    # 2 — Device stage distribution (quick aggregate)
    try:
        stage_r = await db.execute(
            select(Device.current_stage, func.count(Device.id).label("cnt"))
            .group_by(Device.current_stage)
        )
        stage_counts = {
            (row.current_stage.value if hasattr(row.current_stage, "value") else str(row.current_stage)): row.cnt
            for row in stage_r
        }
        modules["devices"] = {
            "status": "ok",
            "stage_counts": stage_counts,
            "total": sum(stage_counts.values()),
        }
    except Exception as e:
        modules["devices"] = {"status": "error", "detail": str(e)[:120]}

    overall = "ok" if all(m.get("status") == "ok" for m in modules.values()) else "degraded"

    return {
        "status": overall,
        "version": "v1",
        "uptime_seconds": int(time.time() - _start_time),
        "registered_modules": REGISTERED_MODULES,
        "modules": modules,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
