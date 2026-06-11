import uuid
from datetime import datetime
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Boolean, Integer
from sqlalchemy.dialects.postgresql import UUID
from database import Base


class WhatsAppSession(Base):
    __tablename__ = "whatsapp_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(50), unique=True, nullable=False)
    phone_number = Column(String(20), nullable=True)
    status = Column(String(20), default="disconnected")  # connected, disconnected, scanning
    session_data = Column(Text, nullable=True)  # JSON session storage
    connected_at = Column(DateTime, nullable=True)
    last_seen = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=app_now)


class WhatsAppMessage(Base):
    __tablename__ = "whatsapp_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sent_by = Column(String(50), nullable=False)  # username
    recipient_phone = Column(String(50), nullable=False)
    recipient_name = Column(String(100), nullable=True)
    message_type = Column(String(20), default="text")  # text, invoice, reminder, catalog
    message_text = Column(Text, nullable=True)
    dealer_id = Column(UUID(as_uuid=True), ForeignKey("dealers.id"), nullable=True)
    reference_type = Column(String(20), nullable=True)  # invoice, payment_reminder, catalog
    reference_id = Column(String(100), nullable=True)
    status = Column(String(20), default="pending")  # pending, sent, failed, delivered
    sent_at = Column(DateTime, nullable=True)
    error_msg = Column(Text, nullable=True)
    direction = Column(String(10), default="outgoing")   # outgoing / incoming
    sender_name = Column(String(200), nullable=True)     # for incoming: who sent in group
    sender_phone = Column(String(30), nullable=True)     # for incoming: sender's phone
    # Mobile telecalling traceability (sprint 2026-05).
    call_id      = Column(UUID(as_uuid=True), ForeignKey("telecalling_records.id"), nullable=True, index=True)
    crm_quote_id = Column(UUID(as_uuid=True), ForeignKey("crm_quotes.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=app_now)


class WhatsAppGroup(Base):
    __tablename__ = "whatsapp_groups"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_wa_id       = Column(String(100), unique=True, nullable=False)   # WA internal ID
    group_name        = Column(String(200), nullable=False)
    participant_count = Column(Integer, default=0)
    tags              = Column(String(200), nullable=True)   # comma-sep: Laptop Dealers, Corporate
    group_category    = Column(String(20), default="other")  # dealer / personal / other
    linked_dealer_id  = Column(UUID(as_uuid=True), ForeignKey("dealers.id", ondelete="SET NULL"), nullable=True)
    synced_by         = Column(String(50), nullable=True)
    last_synced       = Column(DateTime, default=app_now)
    created_at        = Column(DateTime, default=app_now)


class WhatsAppBroadcast(Base):
    __tablename__ = "whatsapp_broadcasts"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    broadcast_name    = Column(String(200), nullable=True)
    message_type      = Column(String(20), default="text")
    message_text      = Column(Text, nullable=False)
    sent_by           = Column(String(50), nullable=False)
    total_recipients  = Column(Integer, default=0)
    sent_count        = Column(Integer, default=0)
    failed_count      = Column(Integer, default=0)
    status            = Column(String(20), default="done")  # done, partial, failed
    created_at        = Column(DateTime, default=app_now)
