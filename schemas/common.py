from __future__ import annotations
from typing import Generic, Optional, TypeVar
from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int


class ErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None


class SuccessResponse(BaseModel):
    message: str
    id: Optional[str] = None


class APIKeyCreateRequest(BaseModel):
    name: str
    scopes: list[str]


class APIKeyCreatedResponse(BaseModel):
    """Returned once on creation — raw key is never stored, never shown again."""
    id: str
    name: str
    key: str          # raw key shown only at creation
    key_prefix: str
    scopes: list[str]
    created_at: str


class APIKeyListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    key_prefix: str
    scopes: list[str]
    created_by: str
    last_used_at: Optional[str] = None
    is_active: bool
    created_at: str
