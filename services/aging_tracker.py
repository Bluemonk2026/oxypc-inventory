"""
Aging Tracker
-------------
Called on application startup and can be triggered manually.
Updates device_aging rows for all active (non-sold, non-scrapped) devices.

Rules:
  days_in_stage > 30  → is_stuck = True
  total_days    > 90  → is_dead_stock = True
"""
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.device import Device, DeviceStage, StageMovement
from models.engines import DeviceAging

# Stages that count as "active" (not terminal)
ACTIVE_STAGES = {
    DeviceStage.iqc, DeviceStage.stock_in,
    DeviceStage.l1,  DeviceStage.l2, DeviceStage.l3,
    DeviceStage.qc_check,
    DeviceStage.cleaning, DeviceStage.dry_sanding,
    DeviceStage.masking,  DeviceStage.painting,
    DeviceStage.water_sanding, DeviceStage.final_qc,
    DeviceStage.ready_to_sale,
}

STUCK_DAYS     = 30
DEAD_STOCK_DAYS= 90


async def refresh_aging(db: AsyncSession) -> dict:
    """
    Recalculate aging for all active devices.
    Returns summary: { "updated": int, "stuck": int, "dead_stock": int }
    """
    now = datetime.utcnow()
    summary = {"updated": 0, "stuck": 0, "dead_stock": 0}

    result = await db.execute(
        select(Device).where(Device.current_stage.in_(ACTIVE_STAGES))
    )
    devices = result.scalars().all()

    for device in devices:
        # ── total days since IQC (created_at) ──────────────────────────
        total_days = (now - device.created_at).days if device.created_at else 0

        # ── days in current stage: find last stage_movement to this stage ──
        mv_result = await db.execute(
            select(StageMovement)
            .where(
                StageMovement.device_id == device.id,
                StageMovement.to_stage  == device.current_stage,
            )
            .order_by(StageMovement.moved_at.desc())
        )
        last_move = mv_result.scalars().first()
        stage_entered = last_move.moved_at if last_move else device.created_at
        days_in_stage = (now - stage_entered).days if stage_entered else total_days

        is_stuck      = days_in_stage > STUCK_DAYS
        is_dead_stock = total_days > DEAD_STOCK_DAYS

        # ── upsert DeviceAging ──────────────────────────────────────────
        aging_result = await db.execute(
            select(DeviceAging).where(DeviceAging.device_id == device.id)
        )
        aging = aging_result.scalar_one_or_none()
        if aging is None:
            aging = DeviceAging(device_id=device.id)
            db.add(aging)

        aging.days_in_stage   = days_in_stage
        aging.total_days      = total_days
        aging.stage_entered_at= stage_entered
        aging.is_stuck        = is_stuck
        aging.is_dead_stock   = is_dead_stock
        aging.refreshed_at    = now

        summary["updated"] += 1
        if is_stuck:      summary["stuck"] += 1
        if is_dead_stock: summary["dead_stock"] += 1

    await db.commit()
    return summary
