import uuid
import secrets
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, Integer, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from database import Base


def _new_bucket_number() -> str:
    return f"BKT{secrets.randbelow(90_000_000) + 10_000_000:08d}"


class Bucket(Base):
    __tablename__ = "buckets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bucket_number = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=True)
    location = Column(String(100), nullable=True)
    category = Column(String(50), nullable=True)
    # status: stock_in | trc_pending | validated
    status = Column(String(20), nullable=False, default="stock_in")
    received_qty = Column(Integer, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=app_now)
    updated_at = Column(DateTime, default=app_now, onupdate=app_now)

    # Movement / production tracking (Batch D)
    location_id = Column(UUID(as_uuid=True), ForeignKey("storage_locations.id"), nullable=True, index=True)
    assigned_to_production = Column(Boolean, nullable=False, default=False)
    assigned_to_production_by = Column(String(50), nullable=True)
    assigned_to_production_at = Column(DateTime, nullable=True)

    # Set by Production Manager's own "Assign Bucket" action (routers/buckets.py
    # assign_bucket), distinct from assigned_to_production above (which only
    # records the Inventory Manager -> Production hand-off). Bucket Allocation
    # tab = assigned_to_production=True and dept_assigned=False; Buckets in
    # Repair Line = both True. Deliberately NOT inferred from device stage —
    # a bucket keeps accepting new devices via "Add to Bucket" long after it's
    # been handed to production, so devices can sit at stock_in indefinitely
    # even on an already-allocated bucket, and a device-stage check silently
    # hid buckets with zero devices still exactly at trc_production.
    dept_assigned = Column(Boolean, nullable=False, default=False, server_default="false")
    dept_assigned_by = Column(String(50), nullable=True)
    dept_assigned_at = Column(DateTime, nullable=True)

    # Final QC Fail Hold's resolved "Devices Failed" reason + engineer
    # (Production Manager -> Repair Line -> Final QC Fail Bucket -> Assign).
    # LOCKED IN by whichever device first fails into this bucket name — every
    # later device joining the SAME bucket name must match BOTH fail_reason
    # and fail_engineer_user_id exactly (routers/cosmetic.py advance_stage),
    # or the Fail submission is rejected and the operator is told to use a
    # different Bucket Name. This keeps a bucket's Assign button (which acts
    # on every tag in it at once) always pointing at one unambiguous
    # reason/engineer pair. fail_engineer_* is resolved from whichever stage
    # the failure reason implies the tag most recently passed through
    # (L1/L2 for Hardware, Stress Test for Software, Cosmetic Completed for
    # Cosmetic) — see routers/cosmetic.py _resolve_fail_engineer.
    fail_reason = Column(String(30), nullable=True)
    fail_engineer_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    fail_engineer_username = Column(String(50), nullable=True)
    fail_engineer_name = Column(String(100), nullable=True)
