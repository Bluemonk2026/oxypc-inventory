"""
R-OS Engine Models
------------------
RepairAttempt  — per-attempt cost + outcome for Cost Engine scrap decision
DeviceCosting  — live device-level P&L (base + parts + labour)
SparePartsLedger — double-entry IN/OUT ledger; stock_qty derived, never stored directly
DeviceAging    — days_in_stage and total_days, refreshed nightly
AuditLog       — immutable write log for every core table change
"""
import uuid
from datetime import datetime
from utils.timezone import app_now
from sqlalchemy import (Column, String, Integer, DateTime, ForeignKey,
                        Text, Numeric, Boolean)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


# ── Repair Attempts ───────────────────────────────────────────────────────
class RepairAttempt(Base):
    """One row per attempt per device per repair level.
    The Cost Engine reads SUM(cost) from here to decide scrap."""
    __tablename__ = "repair_attempts"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id     = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    repair_job_id = Column(UUID(as_uuid=True), ForeignKey("repair_jobs.id"), nullable=True)
    level         = Column(Integer, nullable=False)          # 1, 2, or 3
    attempt_no    = Column(Integer, nullable=False, default=1)
    cost          = Column(Numeric(10, 2), nullable=False, default=0)
    time_spent    = Column(Integer, nullable=True)           # minutes
    outcome       = Column(String(30), nullable=True)        # resolved / escalated / scrapped
    notes         = Column(Text, nullable=True)
    created_by    = Column(String(50), nullable=True)
    created_at    = Column(DateTime, default=app_now)

    device     = relationship("Device",     foreign_keys=[device_id],     lazy="select")
    repair_job = relationship("RepairJob",  foreign_keys=[repair_job_id], lazy="select")


# ── Device Costing (Cost Engine) ─────────────────────────────────────────
class DeviceCosting(Base):
    """Live cost tracker per device. Updated on every parts consumption and repair attempt.
    Scrap decision: total_cost > expected_sale_value."""
    __tablename__ = "device_costing"

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id           = Column(UUID(as_uuid=True), ForeignKey("devices.id"),
                                  unique=True, nullable=False, index=True)
    base_cost           = Column(Numeric(12, 2), nullable=False, default=0)  # lot_price / received_qty
    parts_cost          = Column(Numeric(12, 2), nullable=False, default=0)  # SUM spare parts consumed
    labour_cost         = Column(Numeric(12, 2), nullable=False, default=0)  # estimated
    total_cost          = Column(Numeric(12, 2), nullable=False, default=0)  # base + parts + labour
    expected_sale_value = Column(Numeric(12, 2), nullable=True)
    updated_at          = Column(DateTime, default=app_now, onupdate=app_now)

    device = relationship("Device", foreign_keys=[device_id], lazy="select")


# ── Spare Parts Ledger (double-entry) ─────────────────────────────────────
class SparePartsLedger(Base):
    """Every stock movement is an immutable ledger entry.
    stock_qty = SUM(qty WHERE type='IN') - SUM(qty WHERE type='OUT')
    — never stored directly on spare_parts.qty_in_stock
    (qty_in_stock kept in sync for read performance)."""
    __tablename__ = "spare_parts_ledger"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    part_id        = Column(UUID(as_uuid=True), ForeignKey("spare_parts.id"),
                             nullable=False, index=True)
    entry_type     = Column(String(10), nullable=False)      # IN / OUT
    qty            = Column(Integer, nullable=False)         # always positive
    cost_per_unit  = Column(Numeric(10, 2), nullable=False, default=0)
    total_cost     = Column(Numeric(12, 2), nullable=False, default=0)
    reference_type = Column(String(30), nullable=True)       # purchase / device_repair / adjustment
    reference_id   = Column(String(50), nullable=True)       # UUID of purchase / consumption record
    device_id      = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True)
    notes          = Column(Text, nullable=True)
    created_by     = Column(String(50), nullable=True)
    created_at     = Column(DateTime, default=app_now)

    part   = relationship("SparePart", foreign_keys=[part_id], lazy="select")
    device = relationship("Device",    foreign_keys=[device_id], lazy="select")


# ── Device Aging ──────────────────────────────────────────────────────────
class DeviceAging(Base):
    """Refreshed nightly by the Aging Tracker service.
    days_in_stage > 30 → STUCK flag
    total_days    > 90 → DEAD STOCK flag"""
    __tablename__ = "device_aging"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id       = Column(UUID(as_uuid=True), ForeignKey("devices.id"),
                              unique=True, nullable=False, index=True)
    days_in_stage   = Column(Integer, nullable=False, default=0)
    total_days      = Column(Integer, nullable=False, default=0)
    stage_entered_at= Column(DateTime, nullable=True)
    is_stuck        = Column(Boolean, nullable=False, default=False)   # days_in_stage > 30
    is_dead_stock   = Column(Boolean, nullable=False, default=False)   # total_days > 90
    refreshed_at    = Column(DateTime, default=app_now, onupdate=app_now)

    device = relationship("Device", foreign_keys=[device_id], lazy="select")


# ── Audit Log (append-only) ───────────────────────────────────────────────
class AuditLog(Base):
    """Immutable write log. No UPDATE or DELETE permitted on this table.
    Populated by services/audit_engine.py on every core table write."""
    __tablename__ = "audit_logs"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    username   = Column(String(50), nullable=True)
    action     = Column(String(50), nullable=False)   # e.g. STAGE_MOVED, SALE_CREATED, QC_FAIL
    table_name = Column(String(50), nullable=True)
    record_id  = Column(String(50), nullable=True)
    old_value  = Column(Text, nullable=True)          # JSON snapshot before change
    new_value  = Column(Text, nullable=True)          # JSON snapshot after change
    ip_address = Column(String(45), nullable=True)
    notes      = Column(Text, nullable=True)
    timestamp  = Column(DateTime, default=app_now, nullable=False, index=True)

    user = relationship("User", foreign_keys=[user_id], lazy="select")
