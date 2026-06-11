import uuid
from datetime import datetime
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum
from database import Base


class RepairStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    completed = "completed"


class RepairJob(Base):
    __tablename__ = "repair_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    stage = Column(String(5), nullable=False, index=True)
    engineer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    engineer_name = Column(String(100), nullable=True)
    started_at = Column(DateTime, default=app_now)
    completed_at = Column(DateTime, nullable=True)
    issue_description = Column(Text, nullable=True)
    resolution = Column(Text, nullable=True)
    status = Column(SAEnum(RepairStatus), default=RepairStatus.open, index=True)

    # ── L1/L2 Operational Fields (from Excel L1L2 Engineer Screen) ────────────
    team_name = Column(String(100), nullable=True)
    assigned_engineer = Column(String(100), nullable=True)
    faults = Column(Text, nullable=True)
    dust_cleaning = Column(String(20), nullable=True)       # Done / Not Done
    cmos_battery_change = Column(String(20), nullable=True) # Done / Not Done
    thermal_paste = Column(String(20), nullable=True)       # Done / Not Done
    final_status = Column(String(30), nullable=True)
    # Completed / PNA / Escalate to L4 / Scrap / Lot / Repair
    ram_status = Column(String(20), nullable=True)          # No Change / Upgraded / Downgraded
    ram_removed_gb = Column(String(20), nullable=True)
    ram_added_gb = Column(String(20), nullable=True)
    hdd_updated = Column(String(5), nullable=True)          # Yes / No
    hdd_removed = Column(String(30), nullable=True)
    hdd_added = Column(String(30), nullable=True)
    problem_reported = Column(Text, nullable=True)

    # ── L3 Specific Fields (from Excel L3-L4 sheet) ───────────────────────────
    action_taken = Column(String(50), nullable=True)
    problem_observed = Column(Text, nullable=True)
    scrap_reason = Column(String(100), nullable=True)
    received_from = Column(String(50), nullable=True)       # L1/L2 Engineer / L4 Support
    customer_internal = Column(String(30), nullable=True)   # Customer Service / Internal

    device = relationship("Device", back_populates="repair_jobs")
    spare_part_consumptions = relationship("SparePartConsumption", back_populates="repair_job", lazy="select")
