import uuid
from datetime import datetime
from utils.timezone import app_now
from sqlalchemy import Column, String, Integer, Boolean, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from database import Base


class MasterData(Base):
    __tablename__ = "master_data"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category = Column(String(50), nullable=False, index=True)
    value = Column(String(200), nullable=False)
    description = Column(String(500), nullable=True)
    display_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=app_now)

    __table_args__ = (UniqueConstraint("category", "value", name="uq_master_category_value"),)


# Seed data for initial master data setup
MASTER_SEED = {
    "brand": [
        "HP", "Dell", "Lenovo", "Apple", "Asus", "Acer", "Toshiba", "Sony",
        "Samsung", "MSI", "Microsoft", "LG", "Huawei", "Razer", "Compaq",
    ],
    "device_type": [
        "Laptop", "Desktop", "All-in-One", "Workstation", "Mini PC",
        "Tablet", "Server", "Chromebook",
    ],
    "storage_type": [
        "HDD", "SSD", "NVMe SSD", "eMMC", "SSHD (Hybrid)",
    ],
    "ram_type": [
        "DDR3", "DDR3L", "DDR4", "DDR4L", "DDR5", "LPDDR4", "LPDDR5",
    ],
    "processor_brand": ["Intel", "AMD", "Apple Silicon"],
    "floor": ["Floor 1", "Floor 2", "Floor 3", "Warehouse", "Workshop", "Showroom"],
    "color": [
        "Black", "Silver", "White", "Grey", "Dark Grey", "Gold", "Rose Gold",
        "Blue", "Red", "Green",
    ],
    "repair_issue": [
        "Screen", "Battery", "Keyboard", "Touchpad", "Motherboard", "Hinge",
        "Port (USB/HDMI)", "RAM Slot", "Storage", "Fan / Cooling", "Power Jack",
        "Wi-Fi Card", "Camera", "Speaker", "Charging Issue", "No POST", "Other",
    ],
    "data_destruction_method": [
        "NIST 800-88 Clear", "NIST 800-88 Purge", "DoD 5220.22-M (3-pass)",
        "Gutmann (35-pass)", "Physical Shred", "Degauss", "Not Required",
    ],
    "cosmetic_grade": [
        "A — Like New (no visible marks)",
        "B — Good (minor scratches, no dents)",
        "C — Fair (visible scratches, minor dents)",
        "D — Poor (heavy marks, significant damage)",
        "Scrap — Parts only / non-cosmetic",
    ],
    "sub_category": [
        "Laptop", "Desktop", "All-in-One", "Workstation", "Mini PC",
        "Tablet", "Server", "Chromebook", "Thin Client",
    ],
    "processor_series": [
        "Intel Core i3", "Intel Core i5", "Intel Core i7", "Intel Core i9",
        "Intel Pentium", "Intel Celeron", "Intel Xeon",
        "AMD Ryzen 3", "AMD Ryzen 5", "AMD Ryzen 7", "AMD Ryzen 9",
        "AMD A-Series", "AMD EPYC",
        "Apple M1", "Apple M2", "Apple M3", "Qualcomm Snapdragon",
    ],
    "generation": [
        "4th Gen", "5th Gen", "6th Gen", "7th Gen", "8th Gen", "9th Gen",
        "10th Gen", "11th Gen", "12th Gen", "13th Gen", "14th Gen",
        "Ryzen 1st Gen", "Ryzen 2nd Gen", "Ryzen 3rd Gen",
        "Ryzen 4th Gen", "Ryzen 5th Gen", "Ryzen 6th Gen",
    ],
    "screen_size": [
        '11.6"', '12.5"', '13.3"', '13.5"', '14.0"', '14.1"',
        '15.0"', '15.6"', '17.3"', '19.5"', '21.5"', '23.8"', '24.0"', '27.0"',
    ],
    "grade": [
        "Grade A — Like New",
        "Grade B — Good Condition",
        "Grade C — Average Condition",
        "Grade D — Poor Condition",
        "Scrap / Parts Only",
    ],
    "payment_mode": [
        "Cash", "UPI / GPay / PhonePe", "Bank Transfer (NEFT/RTGS/IMPS)",
        "Cheque", "Credit Card", "Debit Card", "Online Portal", "COD",
    ],
    "warehouse": [
        "TRC 1st Floor", "TRC 2nd Floor", "TRC 3rd Floor",
        "Main Warehouse", "Workshop", "Showroom", "Dispatch Area", "Holding Zone",
    ],
    "location_zone": [
        "Showroom", "Ground Floor", "1st Floor", "2nd Floor",
        "Workshop", "Dispatch Area", "Warehouse", "Holding Zone",
    ],
    "location_unit_type": [
        "Rack", "Crate", "Shelf", "Trolley", "Cabinet", "Floor Space",
    ],
    "part_category": [
        "RAM", "SSD", "HDD", "Battery", "Display", "Keyboard", "Charger / Adapter",
        "Motherboard", "Fan / Cooling", "Hinge", "Casing / Chassis", "Touchpad",
        "Webcam", "Wi-Fi Card", "Speaker", "Power Jack", "Cable / Connector",
        "Heat Sink", "CMOS Battery", "DVD Drive",
    ],
    "supplier": [
        "ABC Traders", "XYZ Electronics", "Local Market", "Online Purchase",
        "Direct Brand", "Government Surplus", "Corporate Buyback",
    ],
    "repair_resolution": [
        "Replaced Component", "Repaired / Soldered", "Updated Firmware / Drivers",
        "OS Reinstalled", "Cleaned / Dusted", "Settings Changed",
        "No Fault Found", "Irreparable — Scrap", "Escalated to L2", "Escalated to L3",
    ],
    "l1_issue": [
        "Screen Damage", "Battery Not Charging", "Keyboard Not Working",
        "Trackpad Issue", "Hinge Broken", "USB Port Not Working", "HDMI Port Issue",
        "Wi-Fi Not Connecting", "Bluetooth Issue", "Speaker Issue", "Microphone Issue",
        "Webcam Not Working", "Power Button Issue", "Overheating", "Slow Performance",
        "OS Not Booting", "Physical Damage — Casing", "Dead on Arrival",
    ],
    "l2_issue": [
        "Motherboard Fault", "RAM Slot Issue", "Storage Failure",
        "Display Controller Issue", "Power Circuit Issue", "BIOS Corruption",
        "Liquid Damage", "Short Circuit", "Charging Circuit",
        "Battery Cell Replacement", "GPU Issue", "No POST",
    ],
    "l3_issue": [
        "Complex Motherboard Repair", "BGA Chip Replacement", "Data Recovery",
        "Component-Level Repair", "Custom Firmware", "Advanced BIOS Recovery",
    ],
    "qc_check_item": [
        "Screen Quality", "Battery Health %", "Keyboard All Keys",
        "Trackpad Sensitivity", "All Ports Functional", "Wi-Fi & Bluetooth",
        "Camera & Mic", "Speaker & Audio", "OS Clean Install",
        "Windows Activation", "Drivers Installed", "Performance Benchmark",
        "Cosmetic Grade", "Serial Number Match", "Bios Password Cleared", "Data Wiped",
    ],
    "return_reason": [
        "Dead on Arrival", "Wrong Specification", "Customer Changed Mind",
        "Performance Issue", "Cosmetic Damage Not Disclosed", "Overheating",
        "Battery Drain", "Warranty Claim", "Duplicate Order", "Other",
    ],
    "condition_on_return": [
        "Like New", "Good — Minor Wear", "Functional — Cosmetic Damage",
        "Partially Working", "Non-Functional", "Damaged Beyond Repair",
    ],
    "cosmetic_issue": [
        "Scratches on Lid", "Scratches on Base", "Dent on Corner",
        "Cracked Hinge", "Broken Bezel", "Chipped Key", "Screen Crack",
        "Screen Stain", "Faded Paint", "Missing Rubber Foot", "Broken Latch", "Body Flex",
    ],
    "battery_health": [
        "95-100% (Excellent)", "85-94% (Good)", "70-84% (Fair)",
        "50-69% (Weak)", "Below 50% (Replace)", "Not Tested", "No Battery",
    ],
    "os_version": [
        "Windows 11 Home", "Windows 11 Pro", "Windows 10 Home", "Windows 10 Pro",
        "Windows 7 Professional", "Ubuntu 22.04 LTS", "Ubuntu 20.04 LTS",
        "macOS Ventura", "macOS Sonoma", "Chrome OS", "No OS",
    ],
    "port_type": [
        "USB-A 2.0", "USB-A 3.0", "USB-A 3.1", "USB-C 3.1",
        "USB-C Thunderbolt 3", "USB-C Thunderbolt 4", "HDMI", "Mini HDMI",
        "DisplayPort", "VGA", "SD Card Reader", "3.5mm Audio",
        "RJ45 Ethernet", "DC Power Jack",
    ],
}
