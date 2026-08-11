"""Shared store for the Reliance Asset FieldOps app (/fieldops).

The field app is local-first: every device holds the full project state in the
browser and keeps working with no network. This table is what makes those
devices agree with each other — a QC submitted on an engineer's phone shows up
in the approver's queue, a pickup handover shows up at the warehouse.

One row per app record (a QC record, a package, an asset's mutable state…),
stored as JSON so the field app stays the single owner of its own schema. The
server's job is only to keep the newest version of each record and to answer
"what changed since I last synced?".

Deliberately kept out of the rest of the OxyPC schema: nothing here has foreign
keys into devices, lots or users, so the field project can be archived or
dropped without touching inventory data.
"""

from datetime import datetime

from sqlalchemy import Column, String, DateTime, Boolean, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from database import Base
from utils.timezone import app_now

# JSONB on Postgres, plain JSON elsewhere (keeps SQLite usable for tests).
_JSON = JSON().with_variant(JSONB, "postgresql")


class FieldOpsRecord(Base):
    """One version of one field-app record."""

    __tablename__ = "fieldops_records"

    # "<kind>:<record id>" — natural key, so an upsert is a single lookup.
    id = Column(String(120), primary_key=True)

    # qc | commercial | package | movement | receipt | asset | site | user |
    # deduction | rate_card | audit | meta
    kind = Column(String(32), nullable=False, index=True)

    # The app's own identifier: QC-000012, PKG-00003, A00417, S073 …
    rec_id = Column(String(80), nullable=False)

    data = Column(_JSON, nullable=False)

    # Server clock, not the device's — devices in the field drift, and the pull
    # cursor has to be comparable across all of them.
    updated_at = Column(DateTime(timezone=True), default=app_now, nullable=False, index=True)

    # OxyPC session that pushed it, for traceability of who synced what.
    updated_by = Column(String(120), nullable=True)

    # Devices report the record's own edit time; used to settle races so an old
    # device coming back online cannot overwrite a newer decision.
    device_updated_at = Column(String(40), nullable=True)

    deleted = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint("kind", "rec_id", name="uq_fieldops_kind_rec"),
        Index("ix_fieldops_updated_kind", "updated_at", "kind"),
    )

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"<FieldOpsRecord {self.kind}:{self.rec_id} @ {self.updated_at}>"
