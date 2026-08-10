"""Part Estimation — a costed, per-lot bill of the spare parts the lot's IQC
data says are required.

One PartEstimate per generated estimate (a lot can be re-estimated; each run
creates a new immutable row and its own Excel file), with one
PartEstimateLine per part name. Generating an estimate also raises a
PartSourcingRequest carrying source='production' so the Spare Parts Manager
sees it on the Part Master -> Sourcing Requests tab.
"""
import uuid

from sqlalchemy import Column, String, DateTime, Integer, Numeric, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base
from utils.timezone import app_now


class PartEstimate(Base):
    __tablename__ = "part_estimates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    lot_id = Column(UUID(as_uuid=True), ForeignKey("lots.id"), nullable=False, index=True)
    lot_number = Column(String(100), nullable=True)          # snapshot for display

    total_products = Column(Integer, nullable=False, default=0)   # tags in the lot at generation time
    total_qty = Column(Integer, nullable=False, default=0)        # sum of part quantities
    parts_total_cost = Column(Numeric(14, 2), nullable=False, default=0)
    labour_cost = Column(Numeric(14, 2), nullable=False, default=0)
    total_estimation = Column(Numeric(14, 2), nullable=False, default=0)

    # DeviceGrade value ("A".."E", "scrap") this file was generated for. The
    # Select Grade dropdown on Part Estimate accepts more than one grade in a
    # single click — one identical-content workbook is written per grade
    # chosen, so this is what tells two otherwise-identical files apart, and
    # what the Download column shows in place of the generic word "Estimate".
    grade = Column(String(10), nullable=True)
    notes = Column(Text, nullable=True)
    file_path = Column(String(255), nullable=True)           # uploads/part_estimates/<uuid>.xlsx
    file_name = Column(String(255), nullable=True)           # human-facing download name

    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=app_now)

    lines = relationship("PartEstimateLine", back_populates="estimate",
                         lazy="select", cascade="all, delete-orphan")


class PartEstimateLine(Base):
    __tablename__ = "part_estimate_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    estimate_id = Column(UUID(as_uuid=True), ForeignKey("part_estimates.id"),
                         nullable=False, index=True)

    part_name = Column(String(150), nullable=False)
    qty = Column(Integer, nullable=False, default=0)
    unit_cost = Column(Numeric(12, 2), nullable=False, default=0)
    total_cost = Column(Numeric(14, 2), nullable=False, default=0)

    estimate = relationship("PartEstimate", back_populates="lines", lazy="select")
