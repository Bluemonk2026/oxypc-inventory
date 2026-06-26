from __future__ import annotations

from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, String, DateTime, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class StressTestResult(Base):
    __tablename__ = "stress_test_results"

    id:             Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    barcode:        Mapped[str]      = mapped_column(String(100), nullable=False, index=True)
    brand:          Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model_name:     Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    run_at:         Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration:       Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    overall_status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    results_json:   Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    pdf_path:       Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    run_by:         Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
