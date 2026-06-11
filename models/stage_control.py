import uuid
from datetime import datetime
from utils.timezone import app_now
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class StageMaster(Base):
    """Canonical list of all stages with display order."""
    __tablename__ = "stage_master"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), unique=True, nullable=False)   # matches DeviceStage enum value
    label = Column(String(100), nullable=False)              # display name
    sequence = Column(Integer, nullable=False, default=0)    # sort order
    created_at = Column(DateTime, default=app_now)

    from_transitions = relationship(
        "AllowedTransition",
        foreign_keys="AllowedTransition.from_stage",
        back_populates="from_stage_obj",
        lazy="select",
    )
    to_transitions = relationship(
        "AllowedTransition",
        foreign_keys="AllowedTransition.to_stage",
        back_populates="to_stage_obj",
        lazy="select",
    )


class AllowedTransition(Base):
    """Defines which stage moves are legal.
    Control Engine queries this before every stage change."""
    __tablename__ = "allowed_transitions"
    __table_args__ = (
        UniqueConstraint("from_stage", "to_stage", name="uq_transition"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_stage = Column(String(50), ForeignKey("stage_master.name", ondelete="CASCADE"), nullable=False)
    to_stage   = Column(String(50), ForeignKey("stage_master.name", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=app_now)

    from_stage_obj = relationship("StageMaster", foreign_keys=[from_stage], back_populates="from_transitions")
    to_stage_obj   = relationship("StageMaster", foreign_keys=[to_stage],   back_populates="to_transitions")


# ── Default stage sequence and allowed transitions ────────────────────────
STAGE_SEQUENCE = [
    ("iqc",           "IQC Inspection",       1),
    ("stock_in",      "Stock In",             2),
    ("l1",            "L1 Repair",            3),
    ("l2",            "L2 Repair",            4),
    ("l3",            "L3 Repair",            5),
    ("qc_check",      "QC Check",             6),
    ("cleaning",      "Cleaning",             7),
    ("dry_sanding",   "Dry Sanding",          8),
    ("masking",       "Masking",              9),
    ("painting",      "Painting",             10),
    ("water_sanding", "Water Sanding",        11),
    ("final_qc",      "Final QC",             12),
    ("ready_to_sale", "Ready to Sale",        13),
    ("sold",          "Sold",                 14),
    ("returned",      "Returned",             15),
    ("scrapped",      "Scrapped",             99),
]

DEFAULT_TRANSITIONS = [
    # IQC can go to stock_in, l1 (direct repair), or scrapped
    ("iqc",           "stock_in"),
    ("iqc",           "l1"),
    ("iqc",           "scrapped"),
    # Stock In → L1 or directly to QC if no repair needed
    ("stock_in",      "l1"),
    ("stock_in",      "qc_check"),
    # Repair escalation
    ("l1",            "l2"),
    ("l1",            "qc_check"),
    ("l1",            "scrapped"),
    ("l2",            "l3"),
    ("l2",            "qc_check"),
    ("l2",            "scrapped"),
    ("l3",            "qc_check"),
    ("l3",            "scrapped"),
    # QC to cosmetic refurb
    ("qc_check",      "cleaning"),
    ("qc_check",      "ready_to_sale"),   # for mint-condition devices
    ("qc_check",      "l1"),              # QC fail → back to repair
    ("qc_check",      "l2"),
    ("qc_check",      "l3"),
    ("qc_check",      "scrapped"),
    # Cosmetic pipeline
    ("cleaning",      "dry_sanding"),
    ("cleaning",      "final_qc"),        # skip sanding if not needed
    ("dry_sanding",   "masking"),
    ("masking",       "painting"),
    ("painting",      "water_sanding"),
    ("water_sanding", "final_qc"),
    ("final_qc",      "ready_to_sale"),
    ("final_qc",      "cleaning"),        # back to cosmetic if failed
    ("final_qc",      "scrapped"),
    # Sales end-states
    ("ready_to_sale", "sold"),
    ("sold",          "returned"),
    # Return re-enters IQC
    ("returned",      "iqc"),
    ("returned",      "scrapped"),
    # Admin can move anything to scrapped
    ("stock_in",      "scrapped"),
]
