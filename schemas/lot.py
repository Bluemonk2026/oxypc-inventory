from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator


class LotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    lot_number: str
    supplier_name: str
    grn_system_number: Optional[str] = None
    grn_date: Optional[datetime] = None
    invoice_date: Optional[datetime] = None
    invoice_no: Optional[str] = None
    invoice_value: Optional[float] = None
    buying_price: float
    qty: int
    purchase_date: datetime
    status: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v) if v is not None else v

    @field_validator("buying_price", "invoice_value", mode="before")
    @classmethod
    def decimal_to_float(cls, v):
        return float(v) if v is not None else v


class LotListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    lot_number: str
    supplier_name: str
    buying_price: float
    qty: int
    purchase_date: datetime
    status: Optional[str] = None

    @field_validator("id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v) if v is not None else v

    @field_validator("buying_price", mode="before")
    @classmethod
    def decimal_to_float(cls, v):
        return float(v) if v is not None else v
