"""Allocation of dealers.dealer_code.

dealer_code carries a UNIQUE index, and every generator in the app derived the
next one from `count(*) + 1`. That is only correct while the codes form an
unbroken run starting at 1 — which production is not.

Two formats have been drawing on the same counter: `DLR-0001` (bulk upload,
portal provisioning) and `DLR0001` (the Add Dealer form). Because both consume
numbers from one shared sequence but only some rows carry the hyphen, the
numbering drifts ahead of the row count. Production reached 915 dealers whose
codes already run to 0916, so `count(*) + 1` handed back a code that already
existed and the UNIQUE index turned it into a 500.

Deriving from MAX(numeric suffix) cannot collide: max + 1 is by definition
unused by any existing code, in either format. The prefix is a parameter so
each caller keeps emitting the format it always has — dealer_code is an
operator-visible identifier printed on paperwork, and quietly changing its
shape would be a data change dressed up as a bug fix.

This does not attempt to be safe against two concurrent writers; that needs a
real sequence. It closes the deterministic collision that is breaking things
today, and a duplicate under simultaneous submits would still surface as an
IntegrityError rather than silently mis-assigning a code.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Matches both formats so the two sequences can never hand out the same number.
_ANY_DEALER_CODE = r"^DLR-?[0-9]+$"


async def max_dealer_code_number(db: AsyncSession) -> int:
    """Highest numeric suffix across every DLR code, hyphenated or not."""
    n = (await db.execute(text(
        "select coalesce(max(substring(dealer_code from '[0-9]+$')::bigint), 0) "
        "from dealers where dealer_code ~ :pat"
    ), {"pat": _ANY_DEALER_CODE})).scalar()
    return int(n or 0)


async def next_dealer_code(db: AsyncSession, prefix: str = "DLR-",
                           width: int = 4) -> str:
    """The next free dealer code. Pass prefix='DLR' for the un-hyphenated form."""
    return f"{prefix}{await max_dealer_code_number(db) + 1:0{width}d}"


async def dealer_code_allocator(db: AsyncSession, prefix: str = "DLR-",
                                width: int = 4):
    """Return a callable handing out successive codes for a bulk import.

    One query up front, then local increments — a bulk upload of a few thousand
    rows must not issue a MAX() per row. Callers that flush between inserts stay
    correct either way, because this counter and the table advance together.
    """
    n = await max_dealer_code_number(db)

    def _next() -> str:
        nonlocal n
        n += 1
        return f"{prefix}{n:0{width}d}"

    return _next
