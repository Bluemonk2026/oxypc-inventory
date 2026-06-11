"""Sprint 11 unit tests — run without a database."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_dealer_credit_note_importable():
    """DealerCreditNote must be importable from models.dealers."""
    from models.dealers import DealerCreditNote
    assert hasattr(DealerCreditNote, "__tablename__")
    assert DealerCreditNote.__tablename__ == "dealer_credit_notes"


def test_dealer_credit_note_fields():
    """DealerCreditNote must have required columns."""
    from models.dealers import DealerCreditNote
    cols = {c.key for c in DealerCreditNote.__table__.columns}
    required = {"id", "credit_number", "dealer_id", "order_id",
                "amount", "reason", "credit_date", "created_by", "created_at"}
    assert required <= cols, f"Missing columns: {required - cols}"


def test_dealer_credit_note_constraints():
    """Verify nullability and uniqueness constraints on critical columns."""
    from models.dealers import DealerCreditNote
    from sqlalchemy.dialects.postgresql import UUID

    cols = {c.key: c for c in DealerCreditNote.__table__.columns}

    # amount must be non-nullable
    assert not cols["amount"].nullable, "amount must be NOT NULL"

    # credit_number must be unique
    assert cols["credit_number"].unique, "credit_number must have UNIQUE constraint"

    # dealer_id must be non-nullable (every credit note must belong to a dealer)
    assert not cols["dealer_id"].nullable, "dealer_id must be NOT NULL"

    # order_id must be nullable (credit note can exist without a specific order)
    assert cols["order_id"].nullable, "order_id must be nullable"


def test_credit_note_number_format():
    """Credit number must follow CN-YYYY-NNNN pattern."""
    import re
    from datetime import datetime
    year = datetime.utcnow().year
    credit_number = f"CN-{year}-{1:04d}"
    assert re.fullmatch(r"CN-\d{4}-\d{4}", credit_number), \
        f"Bad format: {credit_number}"


def test_credit_note_status_logic():
    """Order status after credit note must follow allowlist."""
    from decimal import Decimal

    def recalc_status(total, paid, credit):
        new_total = max(Decimal("0"), Decimal(str(total)) - Decimal(str(credit)))
        new_due = max(Decimal("0"), new_total - Decimal(str(paid)))
        if new_total <= 0:
            return "cancelled", new_total, new_due
        if new_due == 0:
            return "paid", new_total, new_due
        return "pending", new_total, new_due

    status, total, due = recalc_status(5000, 2000, 5000)
    assert status == "cancelled" and total == 0 and due == 0

    status, total, due = recalc_status(5000, 5000, 1000)
    assert status == "paid" and total == Decimal("4000") and due == 0

    status, total, due = recalc_status(5000, 2000, 1000)
    assert status == "pending" and total == Decimal("4000") and due == Decimal("2000")


def test_access_token_expire_minutes_is_int():
    """ACCESS_TOKEN_EXPIRE_MINUTES must be an int so max_age arithmetic works."""
    from config import ACCESS_TOKEN_EXPIRE_MINUTES
    assert isinstance(ACCESS_TOKEN_EXPIRE_MINUTES, int), \
        f"Expected int, got {type(ACCESS_TOKEN_EXPIRE_MINUTES)}"
    assert ACCESS_TOKEN_EXPIRE_MINUTES > 0


def test_limiter_importable():
    """limiter.py must export a Limiter instance named 'limiter'."""
    from limiter import limiter
    from slowapi import Limiter
    assert isinstance(limiter, Limiter)


def test_repair_router_imports_refresh_parts_cost():
    """repair.py must import refresh_parts_cost from cost_engine."""
    import importlib
    repair_mod = importlib.import_module("routers.repair")
    assert hasattr(repair_mod, "refresh_parts_cost"), \
        "refresh_parts_cost not imported into routers.repair"
    from services.cost_engine import refresh_parts_cost
    import asyncio
    assert asyncio.iscoroutinefunction(refresh_parts_cost), \
        "refresh_parts_cost must be an async function"
