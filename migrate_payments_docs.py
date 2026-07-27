"""One-shot migration: add document upload + deal-link + payment-completion
columns for the Supplier Payments / Customer Payments features.

Run: python migrate_payments_docs.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    # supplier_payments
    "ALTER TABLE supplier_payments ADD COLUMN IF NOT EXISTS sourcing_deal_id UUID REFERENCES crm_sourcing_deals(id)",
    "ALTER TABLE supplier_payments ADD COLUMN IF NOT EXISTS invoice_path VARCHAR(255)",
    "ALTER TABLE supplier_payments ADD COLUMN IF NOT EXISTS payment_photo_path VARCHAR(255)",
    # customer_receipts
    "ALTER TABLE customer_receipts ADD COLUMN IF NOT EXISTS opportunity_id UUID REFERENCES crm_sales_opportunities(id)",
    "ALTER TABLE customer_receipts ADD COLUMN IF NOT EXISTS invoice_path VARCHAR(255)",
    "ALTER TABLE customer_receipts ADD COLUMN IF NOT EXISTS payment_photo_path VARCHAR(255)",
    # crm_purchase_orders
    "ALTER TABLE crm_purchase_orders ADD COLUMN IF NOT EXISTS payment_status VARCHAR(20) NOT NULL DEFAULT 'pending'",
    "ALTER TABLE crm_purchase_orders ADD COLUMN IF NOT EXISTS utr_number VARCHAR(100)",
    "ALTER TABLE crm_purchase_orders ADD COLUMN IF NOT EXISTS payment_snapshot_path VARCHAR(255)",
    "ALTER TABLE crm_purchase_orders ADD COLUMN IF NOT EXISTS invoice_path VARCHAR(255)",
    # crm_quotes
    "ALTER TABLE crm_quotes ADD COLUMN IF NOT EXISTS payment_status VARCHAR(20) NOT NULL DEFAULT 'pending'",
    "ALTER TABLE crm_quotes ADD COLUMN IF NOT EXISTS utr_number VARCHAR(100)",
    "ALTER TABLE crm_quotes ADD COLUMN IF NOT EXISTS payment_snapshot_path VARCHAR(255)",
    "ALTER TABLE crm_quotes ADD COLUMN IF NOT EXISTS invoice_path VARCHAR(255)",
]


async def main():
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt}")
            await conn.execute(text(stmt))
    print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(main())
