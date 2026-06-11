"""
Market Intelligence / Availability Models
------------------------------------------
Tracks material available in the market (dealer WhatsApp groups),
enabling buy/sell decisions and price discovery.
"""
import uuid
from datetime import datetime
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Boolean, Numeric, Integer
from sqlalchemy.dialects.postgresql import UUID
from database import Base


class MarketAvailability(Base):
    """
    One entry per model/item posted in a WhatsApp group or recorded manually.
    Represents: "Dealer X has 20x HP 840 G3 at ₹15,000 each, refurb, 3m wty"
    or:          "Dealer Y is looking to buy 10x Dell 5480 laptops"
    """
    __tablename__ = "market_availability"

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Product details
    brand              = Column(String(100), nullable=True)       # HP, Dell, Lenovo, etc.
    model              = Column(String(200), nullable=True)        # 840 G3, 5480, ThinkPad E14
    category           = Column(String(50),  nullable=True)        # Laptop, Desktop, Monitor, etc.
    generation         = Column(String(50),  nullable=True)        # i5 8th Gen, Ryzen 5, etc.
    processor          = Column(String(200), nullable=True)        # Intel Core i5-8250U
    ram                = Column(String(50),  nullable=True)        # 8GB, 16GB
    storage            = Column(String(100), nullable=True)        # 256GB SSD, 1TB HDD
    condition          = Column(String(20),  nullable=True)        # refurb, new, used, as-is
    grade              = Column(String(10),  nullable=True)        # A, B, C

    # Trade details
    trade_type         = Column(String(10),  nullable=False, default="sell")  # buy / sell
    qty                = Column(Integer,     nullable=True)
    price_per_unit     = Column(Numeric(12, 2), nullable=True)
    warranty_months    = Column(Integer,     nullable=True)
    is_negotiable      = Column(Boolean,     default=True)

    # Source: which dealer / group this came from
    dealer_id          = Column(UUID(as_uuid=True), ForeignKey("dealers.id", ondelete="SET NULL"), nullable=True)
    dealer_name        = Column(String(200), nullable=True)        # denormalized for speed
    group_wa_id        = Column(String(100), nullable=True)
    group_name         = Column(String(200), nullable=True)
    source_message_id  = Column(UUID(as_uuid=True), ForeignKey("whatsapp_messages.id", ondelete="SET NULL"), nullable=True)
    source_message_text= Column(Text,        nullable=True)        # original message text

    # Lifecycle
    notes              = Column(Text,        nullable=True)
    is_active          = Column(Boolean,     default=True)         # False = sold / expired
    posted_date        = Column(DateTime,    default=app_now)
    expires_at         = Column(DateTime,    nullable=True)
    created_by         = Column(String(50),  nullable=True)
    created_at         = Column(DateTime,    default=app_now)
    updated_at         = Column(DateTime,    default=app_now, onupdate=app_now)
