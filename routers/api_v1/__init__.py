from fastapi import APIRouter
from .health import router as health_router
from .devices import router as devices_router
from .lots import router as lots_router
from .sales import router as sales_router
from .spare_parts import router as spare_parts_router
from .iqc import router as iqc_router
from .api_keys import router as api_keys_router
from .webhooks import router as webhooks_router
from .telecalling import router as telecalling_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(devices_router)
router.include_router(lots_router)
router.include_router(sales_router)
router.include_router(spare_parts_router)
router.include_router(iqc_router)
router.include_router(api_keys_router)
router.include_router(webhooks_router)
router.include_router(telecalling_router)
