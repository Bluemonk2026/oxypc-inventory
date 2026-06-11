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
