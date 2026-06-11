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
