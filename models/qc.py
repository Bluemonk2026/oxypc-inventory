import uuid
from datetime import datetime
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class QCResult(str):
    pass_ = "pass"
    fail  = "fail"


class QCCheck(Base):
    __tablename__ = "qc_checks"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id      = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    inspector_id   = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    inspector_name = Column(String(100), nullable=True)

    # ── Component Scoring (0–10 each; total_score normalised to 0–100) ────
    battery_score  = Column(Integer, nullable=True)   # 0-10
    screen_score   = Column(Integer, nullable=True)   # 0-10
    keyboard_score = Column(Integer, nullable=True)   # 0-10
    body_score     = Column(Integer, nullable=True)   # 0-10
    total_score    = Column(Integer, nullable=True)   # sum*2.5 → 0-100

    # ── Grade + Result ─────────────────────────────────────────────────────
    result         = Column(String(10), nullable=False)   # pass / fail
    grade          = Column(String(5), nullable=True)     # A/B/C/D/S (auto-assigned)
    attempt_number = Column(Integer, nullable=False, default=1)  # QC fail counter

    # ── Legacy / extra detail ──────────────────────────────────────────────
    checked_at     = Column(DateTime, default=app_now)
    notes          = Column(Text, nullable=True)
    issues_found   = Column(Text, nullable=True)
    send_to_stage  = Column(String(20), nullable=True)   # on fail: which repair stage

    device = relationship("Device", back_populates="qc_checks")

    @property
    def computed_grade(self) -> str:
        """Derive A/B/C/D/S from total_score."""
        s = self.total_score or 0
        if s >= 85: return "A"
        if s >= 70: return "B"
        if s >= 50: return "C"
        if s >  0:  return "D"
        return "S"
