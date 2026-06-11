from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator


class SparePartOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    part_code: str
    name: str
    category: str
    unit_price: float
    qty_in_stock: int
    min_stock_alert: int
    supplier: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v) if v is not None else v

    @field_validator("unit_price", mode="before")
    @classmethod
    def decimal_to_float(cls, v):
        return float(v) if v is not None else v


class SparePartListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    part_code: str
    name: str
    category: str
    unit_price: float
    qty_in_stock: int
    min_stock_alert: int

    @field_validator("id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v) if v is not None else v

    @field_validator("unit_price", mode="before")
    @classmethod
    def decimal_to_float(cls, v):
        return float(v) if v is not None else v
