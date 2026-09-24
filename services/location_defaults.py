"""Auto-location-log helper — closes the dashboard's "Location Gaps"
count (routers/dashboard.py location_gap_count, computed by
routers/inventory_location.py _gap_devices) at the source, instead of only
via a one-off backfill.

_gap_devices flags any active-stage device with zero DeviceLocationLog rows
as "never located". Two stages account for ~96% of that gap in practice —
Stock In and Ready to Sale — because the code paths that move a device into
either one (bucket assignment, GRN, IQC, repair completion, cosmetic
completion, etc.) never write a DeviceLocationLog; only Transfers, IQC's own
external-partner path, and the Location module's own pick-up/place-back/
assign pages do. ensure_stage_location() is called from every real call site
that sets Device.current_stage to one of DEFAULT_STAGE_UNIT_ID's keys, and
stamps a coarse floor-level "assigned" log the first time a device reaches
that stage with no location history at all yet — never overwriting a device
already tracked precisely through the Location module or Transfers.
"""
from sqlalchemy import select

from models.device import DeviceStage
from models.location import DeviceLocationLog, LocationAction, StorageLocation

# Per-stage default location, keyed by StorageLocation.unit_id (a stable
# natural key) rather than a hardcoded UUID. Mapping chosen 2026-09-24 to
# match where this stock actually sits physically: Stock In and the
# workshop-pipeline stages (IQC/L1/QC Check/Final QC) land on the workshop
# floor; Ready to Sale lands on the showroom floor.
DEFAULT_STAGE_UNIT_ID = {
    DeviceStage.stock_in: "TRC-FLOOR",
    DeviceStage.iqc: "TRC-FLOOR",
    DeviceStage.l1: "TRC-FLOOR",
    DeviceStage.qc_check: "TRC-FLOOR",
    DeviceStage.final_qc: "TRC-FLOOR",
    DeviceStage.ready_to_sale: "SHOWROOM-FLOOR",
}

_location_cache: dict[str, "StorageLocation | None"] = {}


async def ensure_stage_location(db, device, stage, current_user, preferred_location_id=None) -> None:
    """Write an initial 'assigned' DeviceLocationLog for `device` if — and
    only if — it has no location history at all yet. Silently no-ops for a
    stage with no default mapping, a device that already has any location
    log (don't clobber real tracking with this coarse default), or a
    missing/inactive target StorageLocation (e.g. local dev DB without the
    production seed rows).

    `preferred_location_id` lets a call site that already captured a real
    StorageLocation for this device (e.g. IQC intake's own Location field)
    use that instead of the coarse per-stage default below — still gated by
    the same "no existing log" check, still logged as 'assigned'."""
    loc_id = preferred_location_id
    if not loc_id:
        unit_id = DEFAULT_STAGE_UNIT_ID.get(stage)
        if not unit_id:
            return
        if unit_id not in _location_cache:
            _location_cache[unit_id] = (await db.execute(
                select(StorageLocation).where(StorageLocation.unit_id == unit_id)
            )).scalar_one_or_none()
        loc = _location_cache[unit_id]
        loc_id = loc.id if loc else None
    if not loc_id:
        return

    existing = (await db.execute(
        select(DeviceLocationLog.id).where(DeviceLocationLog.device_id == device.id).limit(1)
    )).scalar_one_or_none()
    if existing:
        return

    db.add(DeviceLocationLog(
        device_id=device.id, location_id=loc_id, action=LocationAction.assigned,
        actor_id=current_user.id, actor_name=current_user.full_name or current_user.username,
        notes=f"Auto-assigned on entering {stage.value} — no location on file yet.",
    ))
