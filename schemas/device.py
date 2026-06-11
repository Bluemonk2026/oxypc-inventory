from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator

VALID_STAGES = {
    "grn", "iqc", "stock_in", "l1", "l2", "l3",
    "qc_check", "cleaning", "dry_sanding", "masking",
    "painting", "water_sanding", "final_qc",
    "ready_to_sale", "sold", "returned", "scrapped",
}


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    barcode: str
    lot_id: str
    brand: Optional[str] = None
    model: Optional[str] = None
    device_type: Optional[str] = None
    sub_category: Optional[str] = None
    serial_no: Optional[str] = None
    grn_number: Optional[str] = None
    cpu: Optional[str] = None
    generation: Optional[str] = None
    ram_gb: Optional[int] = None
    storage_gb: Optional[int] = None
    storage_type: Optional[str] = None
    hdd_capacity_gb: Optional[int] = None
    screen_size: Optional[str] = None
    battery_health_pct: Optional[int] = None
    bios_password: Optional[bool] = None
    color: Optional[str] = None
    grade: Optional[str] = None
    current_stage: str
    floor: Optional[str] = None
    warehouse: Optional[str] = None
    notes: Optional[str] = None
    device_price: Optional[float] = None
    lot_line_item_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    @field_validator("id", "lot_id", "lot_line_item_id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v) if v is not None else v

    @field_validator("current_stage", mode="before")
    @classmethod
    def stage_to_str(cls, v):
        return v.value if hasattr(v, "value") else str(v)

    @field_validator("grade", mode="before")
    @classmethod
    def grade_to_str(cls, v):
        return v.value if hasattr(v, "value") else (str(v) if v else None)

    @field_validator("device_price", mode="before")
    @classmethod
    def decimal_to_float(cls, v):
        return float(v) if v is not None else v


class DeviceListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    barcode: str
    lot_id: str
    brand: Optional[str] = None
    model: Optional[str] = None
    device_type: Optional[str] = None
    sub_category: Optional[str] = None
    grade: Optional[str] = None
    current_stage: str
    warehouse: Optional[str] = None
    created_at: datetime

    @field_validator("id", "lot_id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v) if v is not None else v

    @field_validator("current_stage", mode="before")
    @classmethod
    def stage_to_str(cls, v):
        return v.value if hasattr(v, "value") else str(v)

    @field_validator("grade", mode="before")
    @classmethod
    def grade_to_str(cls, v):
        return v.value if hasattr(v, "value") else (str(v) if v else None)


class DeviceStageMoveRequest(BaseModel):
    to_stage: str
    notes: Optional[str] = None

    @field_validator("to_stage")
    @classmethod
    def validate_stage(cls, v):
        if v not in VALID_STAGES:
            raise ValueError(f"Invalid stage '{v}'. Valid: {sorted(VALID_STAGES)}")
        return v
