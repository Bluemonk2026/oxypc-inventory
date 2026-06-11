"""Pydantic v2 schemas for the Webhook admin API."""
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator

from schemas.common import PaginatedResponse   # noqa: F401


class WebhookCreateRequest(BaseModel):
    name: str
    url: str
    secret: str
    event_types: list[str]
    is_active: bool = True


class WebhookListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    url: str
    event_types: list[str]
    is_active: bool
    created_by: str
    created_at: str

    @field_validator("id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v) if v is not None else v

    @field_validator("created_at", mode="before")
    @classmethod
    def dt_to_str(cls, v):
        return v.isoformat() if hasattr(v, "isoformat") else str(v)


class EventLogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    payload: dict
    source_module: Optional[str] = None
    published_at: str
    webhook_attempts: int
    last_attempt_at: Optional[str] = None
    last_status_code: Optional[int] = None

    @field_validator("id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v) if v is not None else v

    @field_validator("published_at", "last_attempt_at", mode="before")
    @classmethod
    def dt_to_str(cls, v):
        return v.isoformat() if v and hasattr(v, "isoformat") else v
