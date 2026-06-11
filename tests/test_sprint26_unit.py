# tests/test_sprint26_unit.py
"""Sprint 26 — pure logic unit tests (no DB required)."""
import pytest
from decimal import Decimal


def test_qty_defaults_to_1_when_blank():
    """Simulate IQC router: blank qty form field → 1."""
    qty_str = ""
    qty = int(qty_str) if qty_str else 1
    assert qty == 1


def test_qty_parsed_correctly():
    qty_str = "5"
    qty = int(qty_str) if qty_str else 1
    assert qty == 5


def test_device_price_manual_override():
    """Manual price wins over auto-calculated when provided."""
    auto_price = 4500.0
    manual_str = "5000"
    device_price = float(manual_str) if manual_str else auto_price
    assert device_price == 5000.0


def test_device_price_auto_when_blank():
    auto_price = 4500.0
    manual_str = ""
    device_price = float(manual_str) if manual_str else auto_price
    assert device_price == 4500.0


def test_device_price_bad_value_falls_back():
    """Non-numeric manual price silently falls back to auto."""
    auto_price = 4500.0
    manual_str = "abc"
    try:
        device_price = float(manual_str)
    except ValueError:
        device_price = auto_price
    assert device_price == 4500.0


def test_sale_filter_grade_matches():
    """Simulate SQL-side grade filter logic check."""
    grade = "A"
    # Simulate that a device with grade 'A' passes the filter
    device_grade = "A"
    assert (not grade or device_grade == grade)

    # Grade 'B' does NOT pass filter for 'A'
    device_grade_b = "B"
    assert not (not grade or device_grade_b == grade)
