"""
Partner bid payments — the money leg of a won bid.

Status shown on Bids Created / My Bids / Partner Payments is DERIVED, never
stored, so the three pages can never disagree:

    no PO document attached        -> PO Pending
    PO attached, no payment row    -> Payment Pending
    payment row, not verified      -> Payment Verifying
    payment row, verified          -> Payment Done
"""
import uuid
from sqlalchemy import (Column, String, Numeric, DateTime, Text, Boolean,
                        ForeignKey)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base
from utils.timezone import app_now

PAYMENT_MODES = ["bank_transfer", "upi"]

# Derived status labels, in flow order.
PS_PO_PENDING = "PO Pending"
PS_PAYMENT_PENDING = "Payment Pending"
PS_PAYMENT_VERIFYING = "Payment Verifying"
PS_PAYMENT_DONE = "Payment Done"


class PartnerBidPayment(Base):
    """Payment details submitted by the partner against a won bid."""
    __tablename__ = "partner_bid_payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bid_id = Column(UUID(as_uuid=True), ForeignKey("partner_bids.id"),
                    nullable=False, index=True)

    payment_date = Column(DateTime, nullable=True)
    payment_mode = Column(String(20), nullable=True)      # bank_transfer | upi
    payment_utr = Column(String(100), nullable=True)
    payment_amount = Column(Numeric(14, 2), nullable=True)
    notes = Column(Text, nullable=True)

    submitted_by = Column(String(100), nullable=True)     # partner/dealer identity
    submitted_at = Column(DateTime, default=app_now)

    verified = Column(Boolean, nullable=False, default=False)
    verified_by = Column(String(50), nullable=True)       # finance user
    verified_at = Column(DateTime, nullable=True)
    verify_notes = Column(Text, nullable=True)

    bid = relationship("PartnerBid", lazy="select")


def payment_status(has_po: bool, payment) -> str:
    """Single source of truth for the four-state payment label."""
    if not has_po:
        return PS_PO_PENDING
    if payment is None:
        return PS_PAYMENT_PENDING
    return PS_PAYMENT_DONE if payment.verified else PS_PAYMENT_VERIFYING


PAYMENT_STATUS_BADGE = {
    PS_PO_PENDING:        "bg-secondary",
    PS_PAYMENT_PENDING:   "bg-warning text-dark",
    PS_PAYMENT_VERIFYING: "bg-info text-dark",
    PS_PAYMENT_DONE:      "bg-success",
}
