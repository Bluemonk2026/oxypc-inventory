import uuid
from datetime import datetime
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, Integer, Float, Boolean, ForeignKey, Enum as SAEnum, Text, Numeric, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum
from database import Base


class DeviceStage(str, enum.Enum):
    grn      = "grn"
    iqc      = "iqc"
    stock_in = "stock_in"
    l1 = "l1"
    l2 = "l2"
    l3 = "l3"
    trc_production = "trc_production"
    qc_check = "qc_check"
    cleaning = "cleaning"
    dry_sanding = "dry_sanding"
    masking = "masking"
    painting = "painting"
    water_sanding = "water_sanding"
    final_qc = "final_qc"
    ready_to_sale = "ready_to_sale"
    sold = "sold"
    returned = "returned"
    scrapped = "scrapped"


class DeviceGrade(str, enum.Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    scrap = "scrap"


STAGE_LABELS = {
    DeviceStage.grn: "GRN Receipt",
    DeviceStage.iqc: "IQC",
    DeviceStage.stock_in: "Stock In",
    DeviceStage.l1: "L1 Repair",
    DeviceStage.l2: "L2 Repair",
    DeviceStage.l3: "L3 Repair",
    DeviceStage.trc_production: "TRC Production",
    DeviceStage.qc_check: "Stress Test",
    DeviceStage.cleaning: "Cleaning",
    DeviceStage.dry_sanding: "Dry Sanding",
    DeviceStage.masking: "Masking",
    DeviceStage.painting: "Painting",
    DeviceStage.water_sanding: "Water Sanding",
    DeviceStage.final_qc: "Final QC",
    DeviceStage.ready_to_sale: "Ready to Sale",
    DeviceStage.sold: "Sold",
    DeviceStage.returned: "Returned",
    DeviceStage.scrapped: "Scrapped",
}

STAGE_COLORS = {
    DeviceStage.grn: "warning",
    DeviceStage.iqc: "secondary",
    DeviceStage.stock_in: "info",
    DeviceStage.l1: "warning",
    DeviceStage.l2: "warning",
    DeviceStage.l3: "danger",
    DeviceStage.trc_production: "info",
    DeviceStage.qc_check: "primary",
    DeviceStage.cleaning: "teal",
    DeviceStage.dry_sanding: "teal",
    DeviceStage.masking: "teal",
    DeviceStage.painting: "teal",
    DeviceStage.water_sanding: "teal",
    DeviceStage.final_qc: "purple",
    DeviceStage.ready_to_sale: "success",
    DeviceStage.sold: "dark",
    DeviceStage.returned: "warning",
    DeviceStage.scrapped: "danger",
}


class Device(Base):
    __tablename__ = "devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    barcode = Column(String(100), unique=True, nullable=False, index=True)
    lot_id = Column(UUID(as_uuid=True), ForeignKey("lots.id"), nullable=False)
    brand = Column(String(50), nullable=True, index=True)
    model = Column(String(100), nullable=True)
    device_type = Column(String(30), nullable=True)
    serial_no = Column(String(100), nullable=True)
    sub_category = Column(String(20), nullable=True, index=True)   # Laptop / Desktop / TFT
    cpu = Column(String(100), nullable=True)
    generation = Column(String(50), nullable=True)
    ram_gb = Column(Integer, nullable=True)
    storage_gb = Column(Integer, nullable=True)
    storage_type = Column(String(20), nullable=True)
    hdd_capacity_gb = Column(Integer, nullable=True)   # separate HDD (if dual storage)
    battery_health_pct = Column(Integer, nullable=True)  # 0-100 for laptops
    screen_size = Column(String(20), nullable=True)    # e.g. "14.0 FHD"
    color = Column(String(30), nullable=True)
    bios_password = Column(Boolean, default=False, nullable=True)
    grade = Column(SAEnum(DeviceGrade), nullable=True)
    current_stage = Column(SAEnum(DeviceStage), nullable=False, default=DeviceStage.iqc, index=True)
    floor = Column(String(50), nullable=True)
    warehouse = Column(String(100), nullable=True)     # TRC 1st Floor, Showroom, etc.
    grn_number = Column(String(50), nullable=True)     # Goods Receipt Note ref
    return_status = Column(Boolean, nullable=False, default=False, server_default=text("false"))  # True once returned via Process Return
    replaced = Column(String(120), nullable=True)      # "Replaced by <tag>" / "Replaced from <tag>" (L3 device swap)
    device_price = Column(Numeric(12, 2), nullable=True)  # Individual device buying price
    qty           = Column(Integer, nullable=True, server_default="1")  # Units this record covers (default 1)
    lot_line_item_id = Column(UUID(as_uuid=True), ForeignKey("lot_line_items.id"), nullable=True)
    notes = Column(Text, nullable=True)
    scrap_verified = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_active  = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    deleted_at = Column(DateTime, nullable=True)
    is_trashed = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    trashed_at = Column(DateTime, nullable=True)
    bucket_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime, default=app_now)
    updated_at = Column(DateTime, default=app_now, onupdate=app_now, index=True)

    lot = relationship("Lot", back_populates="devices")
    stage_movements = relationship("StageMovement", back_populates="device", lazy="select")
    repair_jobs = relationship("RepairJob", back_populates="device", lazy="select")
    qc_checks = relationship("QCCheck", back_populates="device", lazy="select")
    sales = relationship("Sale", back_populates="device", lazy="select")
    spare_parts_consumption = relationship("SparePartConsumption", back_populates="device", lazy="select")
    ram_tracking = relationship("RAMTracking", back_populates="device", foreign_keys="RAMTracking.device_id", lazy="select")

    @property
    def stage_label(self):
        return STAGE_LABELS.get(self.current_stage, self.current_stage)

    @property
    def stage_color(self):
        return STAGE_COLORS.get(self.current_stage, "secondary")


class StageMovement(Base):
    __tablename__ = "stage_movements"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id  = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    from_stage = Column(SAEnum(DeviceStage), nullable=True)
    to_stage   = Column(SAEnum(DeviceStage), nullable=False)
    moved_by   = Column(String(50), nullable=True)
    moved_at   = Column(DateTime, default=app_now)
    exited_at  = Column(DateTime, nullable=True)   # set when device leaves this stage
    notes      = Column(Text, nullable=True)

    device = relationship("Device", back_populates="stage_movements")
