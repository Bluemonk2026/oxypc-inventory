"""Inventory Manager "Flag Items" (2026-10-12) — urgent-at-inventory flag on a tag.

One flag per tag, stored on the Device row (flag_active + flag_* columns). The
flag is removed every time the tag moves (back) into the Stock In stage; that is
enforced centrally by an ORM attribute listener on Device.current_stage
(registered at the bottom of models/device.py) so every stage-movement path —
GRN, IQC, repair-complete, sales return, buckets, customise, transfers, entity
movement, API — is covered without each caller having to remember to call it.
"""
from sqlalchemy.orm.base import NEVER_SET


def set_flag(device, authorized_by, request_date, target_date, reason):
    """Add or overwrite the flag on a device (caller commits)."""
    device.flag_active = True
    device.flag_authorized_by = authorized_by
    device.flag_request_date = request_date
    device.flag_target_date = target_date
    device.flag_reason = reason


def clear_flag(device):
    """Remove the flag from a device (caller commits). Safe to call when no flag is set."""
    device.flag_active = False
    device.flag_authorized_by = None
    device.flag_request_date = None
    device.flag_target_date = None
    device.flag_reason = None


def flag_dict(device):
    """JSON/tooltip-friendly view of a device's flag, or None when not flagged."""
    if not getattr(device, "flag_active", False):
        return None
    return {
        "authorized_by": device.flag_authorized_by or "",
        "request_date": device.flag_request_date.isoformat() if device.flag_request_date else "",
        "target_date": device.flag_target_date.isoformat() if device.flag_target_date else "",
        "reason": device.flag_reason or "",
    }


def on_stage_set(device, value, oldvalue):
    """Attribute-set hook body: clear the flag when a tag moves into Stock In.

    A brand-new Device being constructed (old value NEVER_SET) is left alone so a
    tag created straight at Stock In (GRN, IQC, partner flows) can still carry a
    flag passed to the constructor; moving an existing tag into Stock In — from
    any other stage — clears it. Setting stock_in on a tag already at stock_in is
    not a move and keeps the flag.
    """
    from models.device import DeviceStage  # local import: models.device imports this module
    if oldvalue is NEVER_SET:
        return
    if value == DeviceStage.stock_in and oldvalue != DeviceStage.stock_in:
        clear_flag(device)
