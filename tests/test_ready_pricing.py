"""Ready to Sale Min Selling Price formulas (services/ready_pricing.py).

Pure functions — no DB. The formulas are the user's spec:
  Tag:    unit price + Other Rates + margin for each item
  As-Is:  lot price  + margin for As-Is lot
  margin: Amount used as-is, or Percentage applied to the base it is added to.
"""
from decimal import Decimal as D
from types import SimpleNamespace

from services.ready_pricing import (
    ReadyRates, as_is_min_price, lot_price, margin_value, tag_min_price, unit_price,
)


def dev(device_price=None):
    return SimpleNamespace(device_price=device_price)


# ── unit_price ──────────────────────────────────────────────────────────────
def test_unit_price_prefers_device_price():
    assert unit_price(dev(D("1500.00")), D("90000"), 100) == D("1500.00")


def test_unit_price_falls_back_to_lot_average():
    assert unit_price(dev(None), D("90000"), 100) == D("900")


def test_unit_price_none_without_device_price_or_lot_qty():
    assert unit_price(dev(None), D("90000"), 0) is None
    assert unit_price(dev(None), D("90000"), None) is None


# ── margin_value ────────────────────────────────────────────────────────────
def test_margin_amount_is_used_as_is():
    assert margin_value(D("1000"), D("200"), D("0")) == D("200")


def test_margin_percent_is_applied_to_base():
    assert margin_value(D("1000"), D("0"), D("10")) == D("100")


def test_margin_amount_wins_if_both_somehow_set():
    assert margin_value(D("1000"), D("200"), D("10")) == D("200")


def test_margin_zero_when_neither_set():
    assert margin_value(D("1000"), D("0"), D("0")) == D("0")


# ── tag_min_price: unit + other rates + margin ──────────────────────────────
def test_tag_min_price_with_amount_margin():
    r = ReadyRates(other_rate=D("50"), margin_item_amount=D("200"))
    assert tag_min_price(D("1000"), r) == D("1250.00")


def test_tag_min_price_with_percent_margin_uses_unit_price_as_base():
    r = ReadyRates(other_rate=D("50"), margin_item_percent=D("10"))
    # 1000 + 50 + (10% of 1000 = 100) — the percentage is NOT taken on 1050
    assert tag_min_price(D("1000"), r) == D("1150.00")


def test_tag_min_price_no_margin_is_unit_plus_other_rates():
    assert tag_min_price(D("1000"), ReadyRates(other_rate=D("50"))) == D("1050.00")


def test_tag_min_price_none_when_no_unit_price():
    assert tag_min_price(None, ReadyRates(other_rate=D("50"))) is None


# ── lot price + as-is min price ─────────────────────────────────────────────
def test_lot_price_is_sum_of_unit_prices_ignoring_unpriced():
    assert lot_price([D("1000"), D("1000"), D("1000"), None]) == D("3000.00")


def test_lot_price_equals_count_times_price_when_uniform():
    assert lot_price([D("750")] * 8) == D("750") * 8


def test_as_is_min_price_amount_margin():
    r = ReadyRates(margin_asis_amount=D("300"))
    assert as_is_min_price(D("10000"), r) == D("10300.00")


def test_as_is_min_price_percent_margin_on_lot_price():
    r = ReadyRates(margin_asis_percent=D("5"))
    assert as_is_min_price(D("10000"), r) == D("10500.00")


def test_as_is_formula_excludes_other_rates():
    # Other Rates apply per tag only; the As-Is spec is Lot Price + As-Is margin.
    r = ReadyRates(other_rate=D("50"), margin_asis_amount=D("300"))
    assert as_is_min_price(D("10000"), r) == D("10300.00")


def test_results_round_to_paise():
    r = ReadyRates(margin_item_percent=D("12.5"))
    assert tag_min_price(D("99.99"), r) == D("112.49")  # 99.99 + 12.49875
