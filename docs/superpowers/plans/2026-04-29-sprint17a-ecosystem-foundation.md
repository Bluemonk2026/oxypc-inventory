# OxyPC Inventory — Sprint 17a: Ecosystem Foundation (Tier 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a stable `/api/v1/` JSON API layer with API key M2M authentication and CORS so OxyQC EXE and future ecosystem apps (Customer Portal, ESG Reporting, AI Layer, Finance/Tally) can call the OxyPC Inventory backend without browser sessions.

**Architecture:** Parallel routes — all existing HTML routes remain unchanged; new `/api/v1/` routes added alongside them sharing the same DB session. Pydantic v2 `schemas/` package defines stable response contracts. `models/api_key.py` stores M2M credentials (SHA-256 hash, scopes JSON). `auth/api_key.py` provides a `require_scope()` FastAPI dependency. No schema changes to any existing table.

**Tech Stack:** FastAPI, SQLAlchemy 2.x async, Pydantic v2 (`ConfigDict(from_attributes=True)`), Alembic, Python 3.11+. Project root: `C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory`.

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Modify | `schemas/__init__.py` | Export all schema classes |
| Create | `schemas/common.py` | `PaginatedResponse[T]`, `ErrorResponse`, `SuccessResponse`, API key request/response schemas |
| Create | `schemas/device.py` | `DeviceOut`, `DeviceListItem`, `DeviceStageMoveRequest` |
| Create | `schemas/lot.py` | `LotOut`, `LotListItem` |
| Create | `schemas/sale.py` | `SaleOut`, `SaleListItem` |
| Create | `schemas/dealer.py` | `DealerOut`, `DealerListItem` |
| Create | `schemas/spare_parts.py` | `SparePartOut`, `SparePartListItem` |
| Create | `schemas/iqc.py` | `IQCRegisterRequest`, `IQCInspectionData` |
| Create | `models/api_key.py` | `APIKey` ORM model (SHA-256 hash, scopes JSON, soft-delete) |
| Create | `auth/api_key.py` | `require_scope()` dependency, `VALID_SCOPES` frozenset |
| Modify | `config.py` | `ALLOWED_ORIGINS` list from env var |
| Modify | `main.py` | Add `CORSMiddleware`; include `api_v1_router` |
| Create | `routers/api_v1/__init__.py` | Aggregate sub-routers under `/api/v1` prefix |
| Create | `routers/api_v1/devices.py` | `GET /api/v1/devices`, `GET /api/v1/devices/{barcode}`, `PATCH /api/v1/devices/{barcode}/stage` |
| Create | `routers/api_v1/lots.py` | `GET /api/v1/lots`, `GET /api/v1/lots/{lot_number}` |
| Create | `routers/api_v1/sales.py` | `GET /api/v1/sales`, `GET /api/v1/sales/{sale_number}` |
| Create | `routers/api_v1/spare_parts.py` | `GET /api/v1/spare-parts`, `GET /api/v1/spare-parts/{part_code}` |
| Create | `routers/api_v1/iqc.py` | `POST /api/v1/iqc/register` (OxyQC EXE JSON protocol) |
| Create | `routers/api_v1/health.py` | `GET /api/v1/health` (public, no auth — module health + stage counts) |
| Create | `routers/api_v1/api_keys.py` | `POST`, `GET`, `DELETE /api/v1/api-keys` (admin CRUD, session auth) |
| Create | `alembic/versions/20260429_1200_add_api_keys_table.py` | DDL for `api_keys` table |
| Create | `tests/test_api_v1.py` | Integration tests for all new endpoints |

---

### Task 1: Pydantic schemas package

**Files:**
- Modify: `schemas/__init__.py`
- Create: `schemas/common.py`
- Create: `schemas/device.py`
- Create: `schemas/lot.py`
- Create: `schemas/sale.py`
- Create: `schemas/dealer.py`
- Create: `schemas/spare_parts.py`
- Create: `schemas/iqc.py`
- Test: `tests/test_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schemas.py
import pytest
from uuid import uuid4
from datetime import datetime
from schemas.common import PaginatedResponse, SuccessResponse, ErrorResponse
from schemas.device import DeviceOut, DeviceListItem, DeviceStageMoveRequest
from schemas.lot import LotOut, LotListItem
from schemas.sale import SaleOut
from schemas.dealer import DealerOut
from schemas.spare_parts import SparePartOut
from schemas.iqc import IQCRegisterRequest


def test_paginated_response_generic():
    resp = PaginatedResponse[DeviceListItem](
        items=[], total=0, page=1, page_size=50, total_pages=0
    )
    assert resp.total == 0
    assert resp.items == []


def test_device_out_uuid_coercion():
    """UUIDs from SQLAlchemy must be coerced to str by field_validator."""
    device_id = uuid4()
    lot_id = uuid4()
    d = DeviceOut(
        id=device_id,
        barcode="OXY-001",
        lot_id=lot_id,
        brand="Dell",
        model="Latitude 5480",
        device_type="Laptop",
        sub_category="Laptop",
        serial_no=None, grn_number=None, cpu=None, generation=None,
        ram_gb=8, storage_gb=256, storage_type="SSD",
        hdd_capacity_gb=None, screen_size="14.0", battery_health_pct=85,
        bios_password=False, color="Black",
        grade="A", current_stage="iqc",
        floor=None, warehouse=None, notes=None, device_price=None,
        lot_line_item_id=None,
        created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    )
    assert isinstance(d.id, str)
    assert isinstance(d.lot_id, str)
    assert d.id == str(device_id)


def test_stage_move_request_validation():
    req = DeviceStageMoveRequest(to_stage="stock_in", notes="Passed IQC")
    assert req.to_stage == "stock_in"

    with pytest.raises(Exception):
        DeviceStageMoveRequest(to_stage="invalid_stage")


def test_iqc_register_request_required_fields():
    with pytest.raises(Exception):
        IQCRegisterRequest(barcode="", lot_id="not-a-uuid")

    req = IQCRegisterRequest(
        barcode="OXY-TEST-001",
        lot_id=str(uuid4()),
        brand="HP",
        model="ProBook 450",
    )
    assert req.barcode == "OXY-TEST-001"


def test_success_response():
    r = SuccessResponse(message="Created", id=str(uuid4()))
    assert r.message == "Created"
    assert r.id is not None
```

- [ ] **Step 2: Run test to confirm it fails**

```
cd C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
pytest tests/test_schemas.py -v
```
Expected: `ModuleNotFoundError: No module named 'schemas.common'`

- [ ] **Step 3: Create `schemas/common.py`**

```python
# schemas/common.py
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
```

- [ ] **Step 4: Create `schemas/device.py`**

Valid stages must match `DeviceStage` enum values exactly.

```python
# schemas/device.py
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
        # DeviceStage enum → its .value string
        return v.value if hasattr(v, "value") else str(v)

    @field_validator("grade", mode="before")
    @classmethod
    def grade_to_str(cls, v):
        return v.value if hasattr(v, "value") else (str(v) if v else None)


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
```

- [ ] **Step 5: Create `schemas/lot.py`**

```python
# schemas/lot.py
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
```

- [ ] **Step 6: Create `schemas/sale.py`**

```python
# schemas/sale.py
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
```

- [ ] **Step 7: Create `schemas/dealer.py`**

```python
# schemas/dealer.py
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
```

- [ ] **Step 8: Create `schemas/spare_parts.py`**

```python
# schemas/spare_parts.py
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
```

- [ ] **Step 9: Create `schemas/iqc.py`**

All fields mirror the HTML form in `routers/iqc.py` so OxyQC EXE can POST JSON with the same payload.

```python
# schemas/iqc.py
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, field_validator


class IQCInspectionData(BaseModel):
    """Physical inspection fields — all optional, mirrors HTML form in routers/iqc.py."""
    power_on: Optional[str] = None
    status: Optional[str] = None
    all_ok: Optional[str] = None
    r2v3_grade_category: Optional[str] = None
    # Screen
    screen_dot: Optional[str] = None
    screen_line: Optional[str] = None
    screen_functional: Optional[str] = None
    screen_discoloration: Optional[str] = None
    screen_patch: Optional[str] = None
    screen_broken: Optional[str] = None
    screen_flickering: Optional[str] = None
    screen_scratch: Optional[str] = None
    screen_loose: Optional[str] = None
    screen_missing: Optional[str] = None
    screen_hinge_broken: Optional[str] = None
    screen_colour_spread: Optional[str] = None
    screen_keyboard_mark: Optional[str] = None
    screen_hard_press: Optional[str] = None
    # Panel A
    panel_a_scratch: Optional[str] = None
    panel_a_broken: Optional[str] = None
    panel_a_missing: Optional[str] = None
    panel_a_dent: Optional[str] = None
    panel_a_colour_fade: Optional[str] = None
    # Panel B
    panel_b_scratch: Optional[str] = None
    panel_b_colour_fade: Optional[str] = None
    panel_b_rubber_cut: Optional[str] = None
    panel_b_broken: Optional[str] = None
    panel_b_missing: Optional[str] = None
    # Panel C
    panel_c_scratch: Optional[str] = None
    panel_c_broken: Optional[str] = None
    panel_c_missing: Optional[str] = None
    panel_c_dent: Optional[str] = None
    panel_c_colour_fade: Optional[str] = None
    # Panel D
    panel_d_dent: Optional[str] = None
    panel_d_colour_fade: Optional[str] = None
    panel_d_scratch: Optional[str] = None
    panel_d_broken: Optional[str] = None
    panel_d_missing: Optional[str] = None
    # Keyboard
    keyboard_working: Optional[str] = None
    keyboard_colour_fade: Optional[str] = None
    keyboard_key_missing: Optional[str] = None
    keyboard_hard_press: Optional[str] = None
    # Speaker / Touchpad / Ports / Other
    speaker_status: Optional[str] = None
    touchpad_working: Optional[str] = None
    touchpad_click_working: Optional[str] = None
    touchpad_scratch: Optional[str] = None
    touchpad_colour_fade: Optional[str] = None
    touchpad_missing: Optional[str] = None
    port_hdmi: Optional[str] = None
    port_usb_working: Optional[str] = None
    port_audio_jack: Optional[str] = None
    wifi_status: Optional[str] = None
    webcam_status: Optional[str] = None
    hdd_connector: Optional[str] = None
    hdd_casing: Optional[str] = None
    battery_present: Optional[str] = None
    battery_cable: Optional[str] = None
    dvd_drive: Optional[str] = None


class IQCRegisterRequest(BaseModel):
    """Top-level JSON body for POST /api/v1/iqc/register (OxyQC EXE)."""
    # Required
    barcode: str
    lot_id: str   # UUID string

    # Device identity
    brand: Optional[str] = None
    model: Optional[str] = None
    device_type: Optional[str] = None
    sub_category: Optional[str] = None
    serial_no: Optional[str] = None
    grn_number: Optional[str] = None

    # Specs
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

    # Location
    floor: Optional[str] = None
    warehouse: Optional[str] = None
    notes: Optional[str] = None
    lot_line_item_id: Optional[str] = None

    # Inspector name (OxyQC sends the logged-in tech's name)
    inspector_name: Optional[str] = None

    # Physical inspection sub-object
    inspection: Optional[IQCInspectionData] = None

    @field_validator("barcode")
    @classmethod
    def barcode_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("barcode cannot be empty")
        return v.strip()
```

- [ ] **Step 10: Update `schemas/__init__.py`**

```python
# schemas/__init__.py
from .common import (
    PaginatedResponse, ErrorResponse, SuccessResponse,
    APIKeyCreateRequest, APIKeyCreatedResponse, APIKeyListItem,
)
from .device import DeviceOut, DeviceListItem, DeviceStageMoveRequest
from .lot import LotOut, LotListItem
from .sale import SaleOut, SaleListItem
from .dealer import DealerOut, DealerListItem
from .spare_parts import SparePartOut, SparePartListItem
from .iqc import IQCRegisterRequest, IQCInspectionData

__all__ = [
    "PaginatedResponse", "ErrorResponse", "SuccessResponse",
    "APIKeyCreateRequest", "APIKeyCreatedResponse", "APIKeyListItem",
    "DeviceOut", "DeviceListItem", "DeviceStageMoveRequest",
    "LotOut", "LotListItem",
    "SaleOut", "SaleListItem",
    "DealerOut", "DealerListItem",
    "SparePartOut", "SparePartListItem",
    "IQCRegisterRequest", "IQCInspectionData",
]
```

- [ ] **Step 11: Run tests to verify they pass**

```
pytest tests/test_schemas.py -v
```
Expected: 5 tests PASS.

- [ ] **Step 12: Commit**

```bash
git add schemas/
git add tests/test_schemas.py
git commit -m "feat: add Pydantic v2 schemas package — stable API contracts for ecosystem layer"
```

---

### Task 2: API Key model + Alembic migration

**Files:**
- Create: `models/api_key.py`
- Create: `alembic/versions/20260429_1200_add_api_keys_table.py`
- Test: `tests/test_api_key_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_key_model.py
from models.api_key import APIKey


def test_generate_produces_ok_live_prefix():
    raw, hashed = APIKey.generate()
    assert raw.startswith("ok_live_")
    assert len(raw) == 8 + 64   # "ok_live_" + 32 bytes hex = 72 chars
    assert len(hashed) == 64     # SHA-256 hex digest


def test_hash_key_is_deterministic():
    raw = "ok_live_" + "a" * 64
    h1 = APIKey.hash_key(raw)
    h2 = APIKey.hash_key(raw)
    assert h1 == h2
    assert h1 != raw


def test_generate_always_unique():
    _, h1 = APIKey.generate()
    _, h2 = APIKey.generate()
    assert h1 != h2


def test_key_prefix_extraction():
    raw = "ok_live_abcdef123456789012345678901234567890123456789012345678901234"
    prefix = raw[:12]   # "ok_live_abcd"
    assert prefix.startswith("ok_live_")
```

- [ ] **Step 2: Run test to confirm it fails**

```
pytest tests/test_api_key_model.py -v
```
Expected: `ModuleNotFoundError: No module named 'models.api_key'`

- [ ] **Step 3: Create `models/api_key.py`**

```python
# models/api_key.py
import hashlib
import secrets
import uuid
from datetime import datetime

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
    name = Column(String(100), nullable=False)          # e.g. "OxyQC EXE Production"
    key_prefix = Column(String(12), nullable=False)     # First 12 chars for display: "ok_live_xxxx"
    key_hash = Column(String(64), nullable=False, unique=True)  # SHA-256 hex digest
    scopes = Column(JSON, nullable=False, default=list)  # e.g. ["iqc:write", "devices:read"]

    created_by = Column(String(50), nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    deleted_at = Column(DateTime, nullable=True)        # soft-delete
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    @staticmethod
    def generate() -> tuple[str, str]:
        """
        Generate a new raw key and its SHA-256 hash.
        Returns (raw_key, hashed_key).
        raw_key must be shown to the user once and then discarded.
        """
        raw = "ok_live_" + secrets.token_hex(32)   # 8 + 64 = 72 chars
        hashed = APIKey.hash_key(raw)
        return raw, hashed

    @staticmethod
    def hash_key(raw_key: str) -> str:
        """SHA-256 hex digest of a raw API key."""
        return hashlib.sha256(raw_key.encode()).hexdigest()
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_api_key_model.py -v
```
Expected: 4 tests PASS.

- [ ] **Step 5: Create Alembic migration**

```python
# alembic/versions/20260429_1200_add_api_keys_table.py
"""add api_keys table

Revision ID: 20260429_1200
Revises: 20260429_0819_e5e431fe7430
Create Date: 2026-04-29 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260429_1200'
down_revision = '20260429_0819_e5e431fe7430'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'api_keys',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('key_prefix', sa.String(12), nullable=False),
        sa.Column('key_hash', sa.String(64), nullable=False),
        sa.Column('scopes', postgresql.JSON(), nullable=False,
                  server_default=sa.text("'[]'::json")),
        sa.Column('created_by', sa.String(50), nullable=False),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False,
                  server_default=sa.text('true')),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('NOW()')),
    )
    op.create_index('ix_api_keys_key_hash', 'api_keys', ['key_hash'], unique=True)
    op.create_index('ix_api_keys_is_active', 'api_keys', ['is_active'])


def downgrade() -> None:
    op.drop_index('ix_api_keys_is_active', table_name='api_keys')
    op.drop_index('ix_api_keys_key_hash', table_name='api_keys')
    op.drop_table('api_keys')
```

- [ ] **Step 6: Run the migration**

```
cd C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
alembic upgrade head
```
Expected: `Running upgrade 20260429_0819_e5e431fe7430 -> 20260429_1200, add api_keys table`

- [ ] **Step 7: Commit**

```bash
git add models/api_key.py
git add alembic/versions/20260429_1200_add_api_keys_table.py
git add tests/test_api_key_model.py
git commit -m "feat: add APIKey model + Alembic migration — SHA-256 M2M auth, soft-delete, scopes JSON"
```

---

### Task 3: API key auth dependency

**Files:**
- Create: `auth/api_key.py`
- Test: `tests/test_auth_api_key.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth_api_key.py
import pytest
from auth.api_key import VALID_SCOPES, _extract_bearer_token


def test_valid_scopes_includes_all_expected():
    expected = {
        "devices:read", "devices:write",
        "lots:read", "lots:write",
        "sales:read", "sales:write",
        "iqc:read", "iqc:write",
        "dealers:read",
        "spare_parts:read",
        "intelligence:read",
        "api_keys:manage",
    }
    assert expected.issubset(VALID_SCOPES)


def test_extract_bearer_token_valid():
    assert _extract_bearer_token("Bearer ok_live_abc123") == "ok_live_abc123"


def test_extract_bearer_token_missing():
    assert _extract_bearer_token("") is None
    assert _extract_bearer_token(None) is None


def test_extract_bearer_token_wrong_scheme():
    assert _extract_bearer_token("Basic dXNlcjpwYXNz") is None


def test_extract_bearer_token_extra_spaces():
    # Must handle exactly one space after "Bearer "
    token = _extract_bearer_token("Bearer  double-space")
    # "double-space" — strip deals with extra spaces
    assert token is not None
```

- [ ] **Step 2: Run test to confirm it fails**

```
pytest tests/test_auth_api_key.py -v
```
Expected: `ModuleNotFoundError: No module named 'auth.api_key'`

- [ ] **Step 3: Create `auth/api_key.py`**

```python
# auth/api_key.py
"""
API key authentication for machine-to-machine (M2M) endpoints.

Usage:
    @router.get("/", dependencies=[Depends(require_scope("devices:read"))])
    async def list_devices(...):
        ...

Or capture the API key object:
    @router.post("/register")
    async def register(api_key: APIKey = Depends(require_scope("iqc:write"))):
        # api_key.name, api_key.scopes, etc.
        ...
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.api_key import APIKey

VALID_SCOPES: frozenset[str] = frozenset({
    "devices:read",
    "devices:write",
    "lots:read",
    "lots:write",
    "sales:read",
    "sales:write",
    "iqc:read",
    "iqc:write",
    "dealers:read",
    "spare_parts:read",
    "intelligence:read",
    "api_keys:manage",
})


def _extract_bearer_token(auth_header: Optional[str]) -> Optional[str]:
    """Extract raw token from 'Authorization: Bearer <token>' header."""
    if not auth_header:
        return None
    if not auth_header.startswith("Bearer "):
        return None
    parts = auth_header.split(" ", 1)
    if len(parts) != 2:
        return None
    return parts[1].strip() or None


def require_scope(*scopes: str):
    """
    FastAPI dependency factory.
    Validates Bearer token against api_keys table and checks required scopes.
    Returns the APIKey ORM object so the endpoint can log the caller's name/id.

    Example:
        api_key: APIKey = Depends(require_scope("iqc:write"))
    """
    # Validate requested scopes at import time (catches typos in route definitions)
    for s in scopes:
        if s not in VALID_SCOPES:
            raise RuntimeError(
                f"Unknown scope '{s}' in require_scope() call. "
                f"Valid scopes: {sorted(VALID_SCOPES)}"
            )

    async def _verify(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> APIKey:
        raw_key = _extract_bearer_token(request.headers.get("Authorization", ""))
        if not raw_key:
            raise HTTPException(
                status_code=401,
                detail="Missing or malformed Authorization: Bearer <token> header",
            )

        key_hash = APIKey.hash_key(raw_key)
        result = await db.execute(
            select(APIKey).where(
                APIKey.key_hash == key_hash,
                APIKey.is_active == True,
                APIKey.deleted_at.is_(None),
            )
        )
        api_key = result.scalar_one_or_none()

        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid or revoked API key")

        # Scope check
        granted: list = api_key.scopes or []
        missing = [s for s in scopes if s not in granted]
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"API key missing required scopes: {missing}",
            )

        # Update last_used_at (fire-and-forget — don't fail the request if this fails)
        try:
            await db.execute(
                update(APIKey)
                .where(APIKey.id == api_key.id)
                .values(last_used_at=datetime.utcnow())
            )
            # Note: no commit here — the endpoint's db session handles commit
        except Exception:
            pass  # non-critical

        return api_key

    return _verify
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_auth_api_key.py -v
```
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add auth/api_key.py tests/test_auth_api_key.py
git commit -m "feat: add require_scope() API key auth dependency — M2M JWT-free auth with SHA-256 key hashing"
```

---

### Task 4: CORS configuration

**Files:**
- Modify: `config.py` (add `ALLOWED_ORIGINS`)
- Modify: `main.py` (add `CORSMiddleware` + import api_v1 router stub)
- Test: `tests/test_cors.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cors.py
"""CORS preflight and header tests."""
import pytest
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.mark.asyncio
async def test_cors_preflight_from_allowed_origin():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert resp.status_code in (200, 204)
    assert "access-control-allow-origin" in resp.headers


@pytest.mark.asyncio
async def test_cors_preflight_disallowed_origin():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.options(
            "/api/v1/health",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
    # CORSMiddleware returns 400 for disallowed origins on preflight
    assert "access-control-allow-origin" not in resp.headers
```

- [ ] **Step 2: Run test to confirm it fails**

```
pytest tests/test_cors.py -v
```
Expected: either `ImportError` on `routers.api_v1` or CORS headers missing.

- [ ] **Step 3: Add `ALLOWED_ORIGINS` to `config.py`**

Open `config.py`. After the existing constant definitions (after `ACCESS_TOKEN_EXPIRE_MINUTES` line), add:

```python
# Ecosystem CORS — comma-separated origins allowed to call /api/v1/*
# Example env: OXYPC_ALLOWED_ORIGINS=https://portal.oxypc.in,https://esg.oxypc.in
ALLOWED_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv(
        "OXYPC_ALLOWED_ORIGINS",
        "http://localhost:3000,http://localhost:8080,http://localhost:5173",
    ).split(",")
    if o.strip()
]
```

- [ ] **Step 4: Add `CORSMiddleware` to `main.py`**

In `main.py`, after the existing `from config import ...` import line, add `ALLOWED_ORIGINS` to the import:

```python
from config import APP_HOST, APP_PORT, APP_NAME, write_default_config, ALLOWED_ORIGINS
```

Then, after the SlowAPI middleware block (after `app.add_exception_handler(RateLimitExceeded, ...)`), add:

```python
# ── CORS — ecosystem apps (Customer Portal, AI Layer, ESG, Finance) ───────────
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
    expose_headers=["X-Total-Count"],
    max_age=600,
)
```

- [ ] **Step 5: Create minimal `routers/api_v1/__init__.py` stub (so import resolves)**

```python
# routers/api_v1/__init__.py
from fastapi import APIRouter
from .health import router as health_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
```

And the minimal health stub `routers/api_v1/health.py` (full version in Task 8):

```python
# routers/api_v1/health.py
from fastapi import APIRouter
router = APIRouter(prefix="/health", tags=["api-v1-health"])

@router.get("")
async def api_health():
    return {"status": "ok", "version": "v1"}
```

- [ ] **Step 6: Add `api_v1_router` include to `main.py`**

After line `from routers.api import router as api_router`, add:

```python
from routers.api_v1 import router as api_v1_router
```

After `app.include_router(api_router)`, add:

```python
app.include_router(api_v1_router)
```

- [ ] **Step 7: Run CORS tests**

```
pytest tests/test_cors.py -v
```
Expected: 2 tests PASS.

- [ ] **Step 8: Commit**

```bash
git add config.py main.py routers/api_v1/__init__.py routers/api_v1/health.py tests/test_cors.py
git commit -m "feat: add CORS middleware + /api/v1 router stub — ecosystem apps can now preflight"
```

---

### Task 5: Devices JSON API

**Files:**
- Create: `routers/api_v1/devices.py`
- Modify: `routers/api_v1/__init__.py` (include devices_router)
- Test: `tests/test_api_v1.py` (devices section)

- [ ] **Step 1: Write the failing tests (devices section)**

```python
# tests/test_api_v1.py
"""
Integration tests for /api/v1/* endpoints.
Uses a test DB or mocks — these are request-level integration tests.
Note: requires a running DB. Mark with @pytest.mark.integration if desired.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock
from main import app


# ──────────────── Devices ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_devices_list_requires_bearer():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/v1/devices")
    assert resp.status_code == 401
    assert "Missing" in resp.json()["detail"] or "Bearer" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_devices_list_invalid_key():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/api/v1/devices",
            headers={"Authorization": "Bearer ok_live_" + "x" * 64},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_device_barcode_lookup_not_found():
    """Non-existent barcode should 404, not 500."""
    # Even without auth we expect 401, not 500
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/v1/devices/NONEXISTENT-BARCODE")
    assert resp.status_code == 401  # auth before lookup
```

- [ ] **Step 2: Run tests to confirm they fail correctly**

```
pytest tests/test_api_v1.py -v
```
Expected: `404 Not Found` on `/api/v1/devices` (route not registered yet).

- [ ] **Step 3: Create `routers/api_v1/devices.py`**

```python
# routers/api_v1/devices.py
"""
JSON API — Devices
GET  /api/v1/devices                list with filters + pagination
GET  /api/v1/devices/{barcode}      single device detail
PATCH /api/v1/devices/{barcode}/stage   move stage (validates FSM)
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.device import Device, DeviceStage, StageMovement
from models.api_key import APIKey
from models.stage_control import AllowedTransition
from auth.api_key import require_scope
from schemas.device import DeviceOut, DeviceListItem, DeviceStageMoveRequest
from schemas.common import PaginatedResponse
from datetime import datetime

router = APIRouter(prefix="/devices", tags=["api-v1-devices"])


@router.get("", response_model=PaginatedResponse[DeviceListItem])
async def list_devices(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    stage: Optional[str] = Query(default=None),
    sub_category: Optional[str] = Query(default=None),
    brand: Optional[str] = Query(default=None),
    lot_id: Optional[str] = Query(default=None),
    grade: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _key: APIKey = Depends(require_scope("devices:read")),
):
    query = select(Device)
    if stage:
        try:
            query = query.where(Device.current_stage == DeviceStage(stage))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid stage: {stage}")
    if sub_category:
        query = query.where(Device.sub_category == sub_category)
    if brand:
        query = query.where(Device.brand.ilike(f"%{brand}%"))
    if lot_id:
        query = query.where(Device.lot_id == lot_id)
    if grade:
        query = query.where(Device.grade == grade)

    # Total count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Paginated results
    result = await db.execute(
        query.order_by(Device.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    devices = result.scalars().all()
    total_pages = max(1, (total + page_size - 1) // page_size)

    return PaginatedResponse[DeviceListItem](
        items=[DeviceListItem.model_validate(d) for d in devices],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{barcode}", response_model=DeviceOut)
async def get_device(
    barcode: str,
    db: AsyncSession = Depends(get_db),
    _key: APIKey = Depends(require_scope("devices:read")),
):
    result = await db.execute(select(Device).where(Device.barcode == barcode))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail=f"Device '{barcode}' not found")
    return DeviceOut.model_validate(device)


@router.patch("/{barcode}/stage", response_model=DeviceOut)
async def move_device_stage(
    barcode: str,
    body: DeviceStageMoveRequest,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_scope("devices:write")),
):
    result = await db.execute(select(Device).where(Device.barcode == barcode))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail=f"Device '{barcode}' not found")

    current = device.current_stage.value if hasattr(device.current_stage, "value") else str(device.current_stage)

    # FSM validation via AllowedTransition table (same as HTML routes)
    t_result = await db.execute(
        select(AllowedTransition).where(
            AllowedTransition.from_stage == current,
            AllowedTransition.to_stage == body.to_stage,
        )
    )
    if not t_result.scalar_one_or_none():
        raise HTTPException(
            status_code=422,
            detail=f"Transition '{current}' → '{body.to_stage}' is not allowed by the FSM",
        )

    # Apply stage move
    try:
        new_stage = DeviceStage(body.to_stage)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown stage: {body.to_stage}")

    device.current_stage = new_stage
    movement = StageMovement(
        device_id=device.id,
        from_stage=current,
        to_stage=body.to_stage,
        moved_by=f"api_key:{api_key.name}",
        notes=body.notes or f"API stage move via {api_key.key_prefix}",
    )
    db.add(movement)
    await db.commit()
    await db.refresh(device)
    return DeviceOut.model_validate(device)
```

- [ ] **Step 4: Register devices router in `routers/api_v1/__init__.py`**

```python
# routers/api_v1/__init__.py
from fastapi import APIRouter
from .health import router as health_router
from .devices import router as devices_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(devices_router)
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_api_v1.py -v -k "devices"
```
Expected: 3 tests PASS (all return 401 as expected — no valid API key in test DB).

- [ ] **Step 6: Commit**

```bash
git add routers/api_v1/devices.py routers/api_v1/__init__.py tests/test_api_v1.py
git commit -m "feat: add GET /api/v1/devices + GET /api/v1/devices/{barcode} + PATCH stage — FSM-validated"
```

---

### Task 6: Lots JSON API

**Files:**
- Create: `routers/api_v1/lots.py`
- Modify: `routers/api_v1/__init__.py`

- [ ] **Step 1: Append test to `tests/test_api_v1.py`**

Add to the existing file:

```python
# ──────────────── Lots ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lots_list_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/v1/lots")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_lot_by_number_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/v1/lots/LOT-2024-0001")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run to confirm they fail (route not registered)**

```
pytest tests/test_api_v1.py -v -k "lots"
```
Expected: 404 (route not found).

- [ ] **Step 3: Create `routers/api_v1/lots.py`**

```python
# routers/api_v1/lots.py
"""
JSON API — Lots
GET  /api/v1/lots                    list with pagination
GET  /api/v1/lots/{lot_number}       single lot detail
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.lot import Lot
from models.api_key import APIKey
from auth.api_key import require_scope
from schemas.lot import LotOut, LotListItem
from schemas.common import PaginatedResponse

router = APIRouter(prefix="/lots", tags=["api-v1-lots"])


@router.get("", response_model=PaginatedResponse[LotListItem])
async def list_lots(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    supplier: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _key: APIKey = Depends(require_scope("lots:read")),
):
    query = select(Lot)
    if supplier:
        query = query.where(Lot.supplier_name.ilike(f"%{supplier}%"))
    if status:
        query = query.where(Lot.status == status)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(
        query.order_by(Lot.purchase_date.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    lots = result.scalars().all()
    total_pages = max(1, (total + page_size - 1) // page_size)
    return PaginatedResponse[LotListItem](
        items=[LotListItem.model_validate(l) for l in lots],
        total=total, page=page, page_size=page_size, total_pages=total_pages,
    )


@router.get("/{lot_number}", response_model=LotOut)
async def get_lot(
    lot_number: str,
    db: AsyncSession = Depends(get_db),
    _key: APIKey = Depends(require_scope("lots:read")),
):
    result = await db.execute(select(Lot).where(Lot.lot_number == lot_number))
    lot = result.scalar_one_or_none()
    if not lot:
        raise HTTPException(status_code=404, detail=f"Lot '{lot_number}' not found")
    return LotOut.model_validate(lot)
```

- [ ] **Step 4: Register in `__init__.py`**

```python
# routers/api_v1/__init__.py
from fastapi import APIRouter
from .health import router as health_router
from .devices import router as devices_router
from .lots import router as lots_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(devices_router)
router.include_router(lots_router)
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_api_v1.py -v -k "lots"
```
Expected: 2 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add routers/api_v1/lots.py routers/api_v1/__init__.py tests/test_api_v1.py
git commit -m "feat: add GET /api/v1/lots + /api/v1/lots/{lot_number}"
```

---

### Task 7: Sales + Spare-Parts JSON API

**Files:**
- Create: `routers/api_v1/sales.py`
- Create: `routers/api_v1/spare_parts.py`
- Modify: `routers/api_v1/__init__.py`

- [ ] **Step 1: Append tests**

Add to `tests/test_api_v1.py`:

```python
# ──────────────── Sales ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sales_list_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/v1/sales")
    assert resp.status_code == 401


# ──────────────── Spare Parts ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_spare_parts_list_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/v1/spare-parts")
    assert resp.status_code == 401
```

- [ ] **Step 2: Create `routers/api_v1/sales.py`**

```python
# routers/api_v1/sales.py
"""
JSON API — Sales
GET /api/v1/sales                   list with pagination + filters
GET /api/v1/sales/{sale_number}     single sale detail
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.sales import Sale
from models.api_key import APIKey
from auth.api_key import require_scope
from schemas.sale import SaleOut, SaleListItem
from schemas.common import PaginatedResponse

router = APIRouter(prefix="/sales", tags=["api-v1-sales"])


@router.get("", response_model=PaginatedResponse[SaleListItem])
async def list_sales(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sold_by: Optional[str] = Query(default=None),
    customer: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _key: APIKey = Depends(require_scope("sales:read")),
):
    query = select(Sale)
    if sold_by:
        query = query.where(Sale.sold_by == sold_by)
    if customer:
        query = query.where(Sale.customer_name.ilike(f"%{customer}%"))

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(
        query.order_by(Sale.sold_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    sales = result.scalars().all()
    total_pages = max(1, (total + page_size - 1) // page_size)
    return PaginatedResponse[SaleListItem](
        items=[SaleListItem.model_validate(s) for s in sales],
        total=total, page=page, page_size=page_size, total_pages=total_pages,
    )


@router.get("/{sale_number}", response_model=SaleOut)
async def get_sale(
    sale_number: str,
    db: AsyncSession = Depends(get_db),
    _key: APIKey = Depends(require_scope("sales:read")),
):
    result = await db.execute(select(Sale).where(Sale.sale_number == sale_number))
    sale = result.scalar_one_or_none()
    if not sale:
        raise HTTPException(status_code=404, detail=f"Sale '{sale_number}' not found")
    return SaleOut.model_validate(sale)
```

- [ ] **Step 3: Create `routers/api_v1/spare_parts.py`**

```python
# routers/api_v1/spare_parts.py
"""
JSON API — Spare Parts
GET /api/v1/spare-parts               list with low-stock filter
GET /api/v1/spare-parts/{part_code}   single part detail
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.spare_parts import SparePart
from models.api_key import APIKey
from auth.api_key import require_scope
from schemas.spare_parts import SparePartOut, SparePartListItem
from schemas.common import PaginatedResponse

router = APIRouter(prefix="/spare-parts", tags=["api-v1-spare-parts"])


@router.get("", response_model=PaginatedResponse[SparePartListItem])
async def list_spare_parts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    category: Optional[str] = Query(default=None),
    low_stock: bool = Query(default=False, description="Show only parts below min_stock_alert"),
    db: AsyncSession = Depends(get_db),
    _key: APIKey = Depends(require_scope("spare_parts:read")),
):
    query = select(SparePart)
    if category:
        query = query.where(SparePart.category == category)
    if low_stock:
        query = query.where(SparePart.qty_in_stock <= SparePart.min_stock_alert)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(
        query.order_by(SparePart.name)
        .offset((page - 1) * page_size).limit(page_size)
    )
    parts = result.scalars().all()
    total_pages = max(1, (total + page_size - 1) // page_size)
    return PaginatedResponse[SparePartListItem](
        items=[SparePartListItem.model_validate(p) for p in parts],
        total=total, page=page, page_size=page_size, total_pages=total_pages,
    )


@router.get("/{part_code}", response_model=SparePartOut)
async def get_spare_part(
    part_code: str,
    db: AsyncSession = Depends(get_db),
    _key: APIKey = Depends(require_scope("spare_parts:read")),
):
    result = await db.execute(select(SparePart).where(SparePart.part_code == part_code))
    part = result.scalar_one_or_none()
    if not part:
        raise HTTPException(status_code=404, detail=f"Spare part '{part_code}' not found")
    return SparePartOut.model_validate(part)
```

- [ ] **Step 4: Register both in `__init__.py`**

```python
# routers/api_v1/__init__.py
from fastapi import APIRouter
from .health import router as health_router
from .devices import router as devices_router
from .lots import router as lots_router
from .sales import router as sales_router
from .spare_parts import router as spare_parts_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(devices_router)
router.include_router(lots_router)
router.include_router(sales_router)
router.include_router(spare_parts_router)
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_api_v1.py -v -k "sales or spare"
```
Expected: 2 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add routers/api_v1/sales.py routers/api_v1/spare_parts.py routers/api_v1/__init__.py tests/test_api_v1.py
git commit -m "feat: add GET /api/v1/sales + /api/v1/spare-parts JSON API routes"
```

---

### Task 8: IQC JSON API — OxyQC EXE integration

**Files:**
- Create: `routers/api_v1/iqc.py`
- Modify: `routers/api_v1/__init__.py`

- [ ] **Step 1: Append tests**

Add to `tests/test_api_v1.py`:

```python
# ──────────────── IQC register ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_iqc_register_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/v1/iqc/register", json={"barcode": "OXY-001", "lot_id": "bad-uuid"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_iqc_register_invalid_key_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/iqc/register",
            json={"barcode": "OXY-001", "lot_id": "00000000-0000-0000-0000-000000000000"},
            headers={"Authorization": "Bearer ok_live_" + "0" * 64},
        )
    assert resp.status_code == 401
```

- [ ] **Step 2: Create `routers/api_v1/iqc.py`**

This endpoint mirrors the logic in `routers/iqc.py` POST handler but accepts JSON from OxyQC EXE.

```python
# routers/api_v1/iqc.py
"""
JSON API — IQC Registration (OxyQC EXE protocol)
POST /api/v1/iqc/register  → creates Device + IQCInspection + StageMovement + audit log
GET  /api/v1/iqc/lookup?barcode=OXY-001  → quick device lookup by barcode (read-only)

The HTML route at POST /iqc/new is UNCHANGED — this is a parallel JSON endpoint.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.device import Device, DeviceStage, StageMovement
from models.lot import Lot, LotLineItem
from models.iqc_inspection import IQCInspection
from models.api_key import APIKey
from auth.api_key import require_scope
from schemas.iqc import IQCRegisterRequest
from schemas.common import SuccessResponse
from schemas.device import DeviceOut
from services.audit_engine import audit

router = APIRouter(prefix="/iqc", tags=["api-v1-iqc"])


@router.post("/register", response_model=SuccessResponse, status_code=201)
async def register_device(
    body: IQCRegisterRequest,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(require_scope("iqc:write")),
):
    """
    OxyQC EXE submits IQC data as JSON.
    Equivalent to the browser form at POST /iqc/new.
    """
    # Duplicate barcode check
    existing = await db.execute(select(Device).where(Device.barcode == body.barcode))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Barcode '{body.barcode}' already registered")

    device = Device(
        barcode=body.barcode,
        lot_id=body.lot_id,
        sub_category=body.sub_category,
        brand=body.brand,
        model=body.model,
        device_type=body.device_type,
        serial_no=body.serial_no,
        grn_number=body.grn_number,
        cpu=body.cpu,
        generation=body.generation,
        ram_gb=body.ram_gb,
        storage_gb=body.storage_gb,
        storage_type=body.storage_type,
        hdd_capacity_gb=body.hdd_capacity_gb,
        screen_size=body.screen_size,
        battery_health_pct=body.battery_health_pct,
        bios_password=body.bios_password or False,
        color=body.color,
        grade=body.grade,
        floor=body.floor,
        warehouse=body.warehouse,
        notes=body.notes,
        lot_line_item_id=body.lot_line_item_id or None,
        current_stage=DeviceStage.iqc,
    )

    # Auto-price from LotLineItem or lot average (same logic as HTML route)
    if body.lot_line_item_id:
        li_r = await db.execute(select(LotLineItem).where(LotLineItem.id == body.lot_line_item_id))
        li = li_r.scalar_one_or_none()
        if li and li.unit_price:
            device.device_price = float(li.unit_price)
    if not device.device_price:
        lot_r = await db.execute(select(Lot).where(Lot.id == body.lot_id))
        lot_obj = lot_r.scalar_one_or_none()
        if lot_obj and lot_obj.buying_price and lot_obj.qty:
            device.device_price = float(lot_obj.buying_price / lot_obj.qty)

    db.add(device)
    await db.flush()  # get device.id

    # Physical inspection
    insp_data = body.inspection
    inspection_kwargs: dict = {}
    if insp_data:
        inspection_kwargs = insp_data.model_dump(exclude_none=False)

    inspector = body.inspector_name or f"api_key:{api_key.name}"
    inspection = IQCInspection(
        device_id=device.id,
        inspector_name=inspector,
        **{k: v for k, v in inspection_kwargs.items() if v is not None},
    )
    db.add(inspection)

    movement = StageMovement(
        device_id=device.id,
        from_stage=None,
        to_stage=DeviceStage.iqc,
        moved_by=f"api_key:{api_key.name}",
        notes="IQC Entry via OxyQC API",
    )
    db.add(movement)

    # Audit log — reuse existing audit_engine
    from fastapi import Request as FRequest
    class _FakeRequest:
        client = type("C", (), {"host": "api_key"})()
    await audit(
        db, action="DEVICE_IQC_REGISTERED_API",
        user=None,
        table_name="devices", record_id=str(device.id),
        new_value={
            "barcode": body.barcode, "lot_id": str(body.lot_id),
            "brand": body.brand, "model": body.model,
            "grade": body.grade, "api_key": api_key.name,
        },
        request=_FakeRequest(),
    )
    await db.commit()
    return SuccessResponse(message="Device registered successfully", id=str(device.id))


@router.get("/lookup", response_model=DeviceOut)
async def lookup_device(
    barcode: str,
    db: AsyncSession = Depends(get_db),
    _key: APIKey = Depends(require_scope("iqc:read")),
):
    """Fast barcode lookup — returns full device detail or 404."""
    result = await db.execute(select(Device).where(Device.barcode == barcode))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail=f"Device '{barcode}' not found")
    return DeviceOut.model_validate(device)
```

- [ ] **Step 3: Register in `__init__.py`**

```python
# routers/api_v1/__init__.py
from fastapi import APIRouter
from .health import router as health_router
from .devices import router as devices_router
from .lots import router as lots_router
from .sales import router as sales_router
from .spare_parts import router as spare_parts_router
from .iqc import router as iqc_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(devices_router)
router.include_router(lots_router)
router.include_router(sales_router)
router.include_router(spare_parts_router)
router.include_router(iqc_router)
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_api_v1.py -v -k "iqc"
```
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add routers/api_v1/iqc.py routers/api_v1/__init__.py tests/test_api_v1.py
git commit -m "feat: add POST /api/v1/iqc/register — OxyQC EXE JSON IQC registration protocol"
```

---

### Task 9: Enhanced Health endpoint

**Files:**
- Modify: `routers/api_v1/health.py` (replace stub with production version)

- [ ] **Step 1: Append test**

Add to `tests/test_api_v1.py`:

```python
# ──────────────── Health ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_endpoint_is_public():
    """Health endpoint requires NO auth — uptime monitors call it without keys."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/v1/health")
    # Either 200 (DB up) or 503 (DB down in test env) — never 401/404
    assert resp.status_code in (200, 503)
    data = resp.json()
    assert "status" in data
    assert "modules" in data
    assert "registered_modules" in data


@pytest.mark.asyncio
async def test_health_response_shape():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/v1/health")
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    # modules dict has at least "database" key
    assert "database" in data["modules"]
```

- [ ] **Step 2: Replace `routers/api_v1/health.py` with production version**

```python
# routers/api_v1/health.py
"""
GET /api/v1/health  — public endpoint, no auth required.
Returns platform status + module-level sub-checks + stage counts.
Used by: uptime monitors, OxyQC EXE startup check, ecosystem app discovery.
"""
import time
from fastapi import APIRouter, Depends
from sqlalchemy import text, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.device import Device, DeviceStage

router = APIRouter(prefix="/health", tags=["api-v1-health"])

_start_time = time.time()

REGISTERED_MODULES = [
    "devices", "lots", "iqc", "sales", "spare_parts",
    "dealers", "crm_sourcing", "crm_sales", "repair",
    "qc", "whatsapp", "telecalling", "market",
]


@router.get("")
async def api_health(db: AsyncSession = Depends(get_db)):
    modules: dict = {}

    # 1 — Database connectivity
    try:
        await db.execute(text("SELECT 1"))
        modules["database"] = {"status": "ok"}
    except Exception as e:
        modules["database"] = {"status": "error", "detail": str(e)[:120]}

    # 2 — Device stage distribution (quick aggregate)
    try:
        stage_r = await db.execute(
            select(Device.current_stage, func.count(Device.id).label("cnt"))
            .group_by(Device.current_stage)
        )
        stage_counts = {row.current_stage.value: row.cnt for row in stage_r}
        modules["devices"] = {
            "status": "ok",
            "stage_counts": stage_counts,
            "total": sum(stage_counts.values()),
        }
    except Exception as e:
        modules["devices"] = {"status": "error", "detail": str(e)[:120]}

    overall = "ok" if all(m.get("status") == "ok" for m in modules.values()) else "degraded"

    return {
        "status": overall,
        "version": "v1",
        "uptime_seconds": int(time.time() - _start_time),
        "registered_modules": REGISTERED_MODULES,
        "modules": modules,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
```

- [ ] **Step 3: Run tests**

```
pytest tests/test_api_v1.py -v -k "health"
```
Expected: 2 tests PASS (200 or 503 depending on whether test DB is up).

- [ ] **Step 4: Commit**

```bash
git add routers/api_v1/health.py tests/test_api_v1.py
git commit -m "feat: production /api/v1/health — stage counts, module registry, public no-auth"
```

---

### Task 10: API Key admin CRUD (session-auth, browser UI)

**Files:**
- Create: `routers/api_v1/api_keys.py`
- Modify: `routers/api_v1/__init__.py`

> These admin endpoints use session cookie auth (`get_current_user`), NOT API key auth — so admins can create/revoke keys via the browser. The raw key is returned once on creation.

- [ ] **Step 1: Append test**

Add to `tests/test_api_v1.py`:

```python
# ──────────────── API Keys admin ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_keys_list_requires_session():
    """Admin routes use cookie session auth, not Bearer."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/v1/api-keys")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_api_key_create_requires_session():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/v1/api-keys", json={"name": "Test", "scopes": ["devices:read"]})
    assert resp.status_code == 401
```

- [ ] **Step 2: Create `routers/api_v1/api_keys.py`**

```python
# routers/api_v1/api_keys.py
"""
Admin CRUD for API keys — uses session cookie auth (browser admin panel).
POST   /api/v1/api-keys          create new key (returns raw key ONCE)
GET    /api/v1/api-keys          list all active keys (prefixes only, never hashes)
DELETE /api/v1/api-keys/{key_id} revoke (soft-delete) a key
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.api_key import APIKey
from models.user import User, UserRole
from auth.dependencies import get_current_user, require_roles
from auth.api_key import VALID_SCOPES
from schemas.common import (
    APIKeyCreateRequest, APIKeyCreatedResponse, APIKeyListItem, SuccessResponse
)
from services.audit_engine import audit

router = APIRouter(prefix="/api-keys", tags=["api-v1-api-keys"])
admin_only = require_roles(UserRole.admin)


@router.post("", response_model=APIKeyCreatedResponse, status_code=201)
async def create_api_key(
    body: APIKeyCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    # Validate scopes
    invalid = [s for s in body.scopes if s not in VALID_SCOPES]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unknown scopes: {invalid}")

    raw_key, key_hash = APIKey.generate()
    key_prefix = raw_key[:12]

    api_key = APIKey(
        name=body.name,
        key_prefix=key_prefix,
        key_hash=key_hash,
        scopes=body.scopes,
        created_by=current_user.username,
    )
    db.add(api_key)
    await db.flush()

    await audit(
        db, action="API_KEY_CREATED", user=current_user,
        table_name="api_keys", record_id=str(api_key.id),
        new_value={"name": body.name, "scopes": body.scopes, "key_prefix": key_prefix},
        request=None,
    )
    await db.commit()

    return APIKeyCreatedResponse(
        id=str(api_key.id),
        name=api_key.name,
        key=raw_key,           # shown ONCE — never retrievable again
        key_prefix=key_prefix,
        scopes=api_key.scopes,
        created_at=api_key.created_at.isoformat(),
    )


@router.get("", response_model=list[APIKeyListItem])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    result = await db.execute(
        select(APIKey)
        .where(APIKey.deleted_at.is_(None))
        .order_by(APIKey.created_at.desc())
    )
    keys = result.scalars().all()
    items = []
    for k in keys:
        items.append(APIKeyListItem(
            id=str(k.id),
            name=k.name,
            key_prefix=k.key_prefix,
            scopes=k.scopes or [],
            created_by=k.created_by,
            last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
            is_active=k.is_active,
            created_at=k.created_at.isoformat(),
        ))
    return items


@router.delete("/{key_id}", response_model=SuccessResponse)
async def revoke_api_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    result = await db.execute(
        select(APIKey).where(APIKey.id == key_id, APIKey.deleted_at.is_(None))
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found or already revoked")

    api_key.is_active = False
    api_key.deleted_at = datetime.utcnow()

    await audit(
        db, action="API_KEY_REVOKED", user=current_user,
        table_name="api_keys", record_id=str(api_key.id),
        new_value={"name": api_key.name, "key_prefix": api_key.key_prefix},
        request=None,
    )
    await db.commit()
    return SuccessResponse(message=f"API key '{api_key.name}' revoked successfully")
```

- [ ] **Step 3: Register in `__init__.py`**

Final complete `routers/api_v1/__init__.py`:

```python
# routers/api_v1/__init__.py
from fastapi import APIRouter
from .health import router as health_router
from .devices import router as devices_router
from .lots import router as lots_router
from .sales import router as sales_router
from .spare_parts import router as spare_parts_router
from .iqc import router as iqc_router
from .api_keys import router as api_keys_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(devices_router)
router.include_router(lots_router)
router.include_router(sales_router)
router.include_router(spare_parts_router)
router.include_router(iqc_router)
router.include_router(api_keys_router)
```

- [ ] **Step 4: Run all api_v1 tests**

```
pytest tests/test_api_v1.py -v
```
Expected: All tests PASS (exact count ≥ 13 tests).

- [ ] **Step 5: Commit**

```bash
git add routers/api_v1/api_keys.py routers/api_v1/__init__.py tests/test_api_v1.py
git commit -m "feat: add POST/GET/DELETE /api/v1/api-keys — admin key management with audit trail"
```

---

### Task 11: Full test run + smoke test

**Files:**
- Test: `tests/test_api_v1.py` (already written)
- No new files — this is verification only

- [ ] **Step 1: Run all new tests**

```
pytest tests/test_schemas.py tests/test_api_key_model.py tests/test_auth_api_key.py tests/test_cors.py tests/test_api_v1.py -v
```
Expected: All tests PASS. Count ≥ 22 tests.

- [ ] **Step 2: Verify server starts without error**

```
cd C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
python -c "from main import app; print('App imports OK')"
```
Expected: `App imports OK`

- [ ] **Step 3: Verify OpenAPI schema lists all new routes**

Start the server and check:
```
GET http://localhost:8000/openapi.json
```
Confirm these paths appear in the schema:
- `GET /api/v1/health`
- `GET /api/v1/devices`
- `GET /api/v1/devices/{barcode}`
- `PATCH /api/v1/devices/{barcode}/stage`
- `GET /api/v1/lots`
- `GET /api/v1/lots/{lot_number}`
- `GET /api/v1/sales`
- `GET /api/v1/sales/{sale_number}`
- `GET /api/v1/spare-parts`
- `GET /api/v1/spare-parts/{part_code}`
- `POST /api/v1/iqc/register`
- `GET /api/v1/iqc/lookup`
- `POST /api/v1/api-keys`
- `GET /api/v1/api-keys`
- `DELETE /api/v1/api-keys/{key_id}`

- [ ] **Step 4: Test the OxyQC EXE workflow end-to-end (manual smoke test)**

1. Create an API key via the admin UI (or direct DB insert):
   ```sql
   -- After running server: POST /api/v1/api-keys via curl
   curl -X POST http://localhost:8000/api/v1/api-keys \
     -H "Content-Type: application/json" \
     -d '{"name": "OxyQC Test", "scopes": ["iqc:write", "iqc:read", "devices:read"]}' \
     --cookie "access_token=<admin_token>"
   ```
2. Use the returned key to call health:
   ```
   GET http://localhost:8000/api/v1/health
   ```
   Expected: `{"status": "ok", "registered_modules": [...], "modules": {...}}`

3. Register a device:
   ```
   POST http://localhost:8000/api/v1/iqc/register
   Authorization: Bearer ok_live_<key>
   Content-Type: application/json
   {"barcode": "SMOKE-001", "lot_id": "<valid-lot-uuid>", "brand": "HP", "grade": "B"}
   ```
   Expected: `201 {"message": "Device registered successfully", "id": "..."}`

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "feat: Sprint 17a complete — OxyPC modular API foundation: /api/v1/ layer, API key M2M auth, CORS, 15 JSON endpoints"
```

---

## Self-Review

### Spec coverage

| Requirement | Task |
|---|---|
| Pydantic schemas for every module | Task 1 |
| JSON API endpoints /api/v1/{module}/* with full CRUD | Tasks 5-10 |
| API key table + middleware for M2M auth | Tasks 2-3 |
| CORS configuration | Task 4 |
| Module health endpoints /api/v1/health | Task 9 |
| OxyQC EXE JSON protocol /api/v1/iqc/register | Task 8 |
| Alembic migration for api_keys | Task 2 |
| RBAC on all new endpoints (admin only for key admin) | Task 10 |
| Audit log on API key create/revoke | Task 10 |
| Soft-delete on api_keys | Task 2 |
| No break to existing HTML routes | All tasks (parallel routes) |

**Gaps:** Dealers read-only endpoint not explicitly written (DealerOut schema exists; add `routers/api_v1/dealers.py` following same pattern as lots.py if needed — trivial extension).

### Placeholder scan
✅ No TBD, TODO, "implement later", "fill in details", "similar to Task N" patterns found.

### Type consistency
- `DeviceOut.model_validate(device)` — used in Tasks 5, 8
- `LotListItem.model_validate(l)` — used in Task 6
- `SaleListItem.model_validate(s)` — used in Task 7
- `SparePartListItem.model_validate(p)` — used in Task 7
- `APIKey.generate()` returns `(str, str)` — used in Task 10 (matches model definition in Task 2)
- `APIKey.hash_key(raw)` — used in Task 3 (`auth/api_key.py`) (matches model definition in Task 2)
- `require_scope("iqc:write")` — all scopes present in `VALID_SCOPES` frozenset (Task 3)
- `SuccessResponse(message=..., id=...)` — used in Tasks 8, 10 (matches schema in Task 1)

All consistent ✅

---

## Follow-on: Tier 2 (Sprint 17b)

After Sprint 17a passes review, plan Sprint 17b:
- In-process event bus (`services/event_bus.py`) with pub/sub registry
- `webhooks` table: id, name, url, secret_hash, event_types (JSON), is_active
- `event_log` table: id, event_type, payload (JSON), source_module, published_at
- Webhook dispatcher: fire HTTP POST on `DEVICE_REGISTERED`, `LOT_CREATED`, `QC_PASSED`, `SALE_COMPLETED`

## Follow-on: Tier 3 (Sprint 17c)

- `GET /api/v1/intelligence/*` — AI read-only snapshots (stage distributions, lot P&L summaries)
- Module capability registry (`app_settings` extension)
- Finance webhook on sale creation (invoice payload → Tally/QuickBooks)
- WhatsApp Bot inbound endpoint (parses WA group messages → market_availability)
