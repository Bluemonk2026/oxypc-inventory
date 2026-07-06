"""One-shot migration: create dealer_quotations + dealer_quotation_items tables.

Run: python migrate_dealer_quotations.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS dealer_quotations (
        id UUID PRIMARY KEY,
        quote_number VARCHAR(30) UNIQUE NOT NULL,
        dealer_id UUID NOT NULL REFERENCES dealers(id),
        customer_name VARCHAR(200) NOT NULL,
        customer_type VARCHAR(30) NULL,
        dealer_phone VARCHAR(20) NULL,
        dealer_email VARCHAR(100) NULL,
        dealer_address TEXT NULL,
        dealer_gstin VARCHAR(20) NULL,
        company_name VARCHAR(200) NULL,
        company_address TEXT NULL,
        company_gstin VARCHAR(20) NULL,
        company_phone VARCHAR(20) NULL,
        company_email VARCHAR(100) NULL,
        payment_terms TEXT NULL,
        additional_notes TEXT NULL,
        total_quantity INTEGER NOT NULL DEFAULT 0,
        total_price NUMERIC(14,2) NOT NULL DEFAULT 0,
        status VARCHAR(20) NOT NULL DEFAULT 'shared',
        created_by VARCHAR(50) NULL,
        created_at TIMESTAMP NULL,
        confirmed_by VARCHAR(50) NULL,
        confirmed_at TIMESTAMP NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_dealer_quotations_dealer_id ON dealer_quotations(dealer_id)",
    """
    CREATE TABLE IF NOT EXISTS dealer_quotation_items (
        id UUID PRIMARY KEY,
        quotation_id UUID NOT NULL REFERENCES dealer_quotations(id),
        product_name VARCHAR(200) NOT NULL,
        model_name VARCHAR(200) NULL,
        quantity INTEGER NOT NULL DEFAULT 1,
        unit_price NUMERIC(12,2) NOT NULL DEFAULT 0,
        total_price NUMERIC(14,2) NOT NULL DEFAULT 0,
        sort_order INTEGER DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_dealer_quotation_items_quotation_id ON dealer_quotation_items(quotation_id)",
]


async def main():
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt.strip().splitlines()[0]}...")
            await conn.execute(text(stmt))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
