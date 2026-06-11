from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator


class DealerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dealer_code: str
    business_name: str
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    gstin: Optional[str] = None
    dealer_type: Optional[str] = None
    credit_limit: Optional[float] = None
    outstanding_amount: Optional[float] = None
    total_purchases: Optional[float] = None
    is_active: Optional[bool] = None
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v) if v is not None else v

    @field_validator("credit_limit", "outstanding_amount", "total_purchases", mode="before")
    @classmethod
    def decimal_to_float(cls, v):
        return float(v) if v is not None else v


class DealerListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dealer_code: str
    business_name: str
    phone: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    dealer_type: Optional[str] = None

    @field_validator("id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v) if v is not None else v
