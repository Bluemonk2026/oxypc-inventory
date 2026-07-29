"""One-shot migration: partner bid payments (Batch 2).

Creates partner_bid_payments — payment details a partner submits against a
won bid, verified by finance on the Partner Payments page.

Run: python migrate_partner_payments.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS partner_bid_payments (
        id UUID PRIMARY KEY,
        bid_id UUID NOT NULL REFERENCES partner_bids(id),
        payment_date TIMESTAMP,
        payment_mode VARCHAR(20),
        payment_utr VARCHAR(100),
        payment_amount NUMERIC(14,2),
        notes TEXT,
        submitted_by VARCHAR(100),
        submitted_at TIMESTAMP,
        verified BOOLEAN NOT NULL DEFAULT false,
        verified_by VARCHAR(50),
        verified_at TIMESTAMP,
        verify_notes TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_partner_bid_payments_bid_id ON partner_bid_payments (bid_id)",
]


async def main():
    for stmt in STATEMENTS:
        print(f"Running: {' '.join(stmt.split())[:90]}")
        async with engine.begin() as conn:
            await conn.execute(text(stmt))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
