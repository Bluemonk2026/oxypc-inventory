import hashlib
import secrets
import uuid
from datetime import datetime
from utils.timezone import app_now

from sqlalchemy import Boolean, Column, DateTime, JSON, String
from sqlalchemy.dialects.postgresql import UUID

from database import Base


class APIKey(Base):
    """
    Machine-to-machine API key for ecosystem apps.
    Raw key is NEVER stored — only SHA-256 hash.
    Format: ok_live_<64 hex chars>  (72 chars total)
    """
    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    key_prefix = Column(String(12), nullable=False)
    key_hash = Column(String(64), nullable=False, unique=True)
    scopes = Column(JSON, nullable=False, default=list)

    created_by = Column(String(50), nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=app_now, nullable=False)

    @staticmethod
    def generate() -> tuple[str, str]:
        raw = "ok_live_" + secrets.token_hex(32)
        hashed = APIKey.hash_key(raw)
        return raw, hashed

    @staticmethod
    def hash_key(raw_key: str) -> str:
        return hashlib.sha256(raw_key.encode()).hexdigest()
