"""
Health Check Endpoint
---------------------
GET /health → JSON
  {
    "status": "ok" | "degraded",
    "db": "ok" | "error: <message>",
    "version": "1.0.0",
    "uptime_seconds": <int>
  }

Returns HTTP 200 when healthy, HTTP 503 when DB unreachable.
Used by uptime monitors (Uptime Robot, Grafana, load balancers).
"""
import time
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from database import AsyncSessionLocal

router = APIRouter(tags=["health"])

_start_time = time.time()


@router.get("/health")
async def health_check():
    """
    Lightweight liveness + readiness check.
    Executes SELECT 1 against the DB to confirm connectivity.
    """
    db_status = "ok"
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = f"error: {str(exc)[:120]}"

    healthy = db_status == "ok"
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "db": db_status,
            "version": "1.0.0",
            "uptime_seconds": int(time.time() - _start_time),
        },
    )
