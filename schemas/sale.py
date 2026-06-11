from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator


class SaleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sale_number: str
    device_id: str
    sale_price: float
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_state: Optional[str] = None
    invoice_no: Optional[str] = None
    payment_mode: Optional[str] = None
    sold_by: Optional[str] = None
    sold_at: datetime
    notes: Optional[str] = None

    @field_validator("id", "device_id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v) if v is not None else v

    @field_validator("sale_price", mode="before")
    @classmethod
    def decimal_to_float(cls, v):
        return float(v) if v is not None else v


class SaleListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sale_number: str
    device_id: str
    sale_price: float
    customer_name: Optional[str] = None
    sold_by: Optional[str] = None
    sold_at: datetime

    @field_validator("id", "device_id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v) if v is not None else v

    @field_validator("sale_price", mode="before")
    @classmethod
    def decimal_to_float(cls, v):
        return float(v) if v is not None else v
