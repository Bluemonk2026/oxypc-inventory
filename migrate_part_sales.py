"""One-shot migration: spare-part sales chain.

Creates:
  - part_sale_requests  (Ready to Sale Parts -> Parts Sale Request approvals)
  - part_sales          (completed spare-part sales, Spare Part Sales page)
  - spare_parts.sold_qty column
  - part_sale_number_seq sequence (PS-0001 numbering, race-safe like sales)

Run: python migrate_part_sales.py
"""
import asyncio
from sqlalchemy import text
from database import engine

STATEMENTS = [
    "ALTER TABLE spare_parts ADD COLUMN IF NOT EXISTS sold_qty INTEGER NOT NULL DEFAULT 0",
    "CREATE SEQUENCE IF NOT EXISTS part_sale_number_seq START WITH 1",
    """
    CREATE TABLE IF NOT EXISTS part_sale_requests (
        id UUID PRIMARY KEY,
        part_id UUID NOT NULL REFERENCES spare_parts(id),
        part_code VARCHAR(20),
        part_name VARCHAR(150),
        make VARCHAR(100),
        model VARCHAR(100),
        qty_requested INTEGER NOT NULL DEFAULT 1,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        is_consumed BOOLEAN NOT NULL DEFAULT false,
        requested_by VARCHAR(50),
        created_at TIMESTAMP,
        actioned_at TIMESTAMP,
        actioned_by VARCHAR(50),
        reject_reason VARCHAR(300)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_part_sale_requests_part_id ON part_sale_requests (part_id)",
    "CREATE INDEX IF NOT EXISTS ix_part_sale_requests_status ON part_sale_requests (status)",
    """
    CREATE TABLE IF NOT EXISTS part_sales (
        id UUID PRIMARY KEY,
        sale_number VARCHAR(20) NOT NULL UNIQUE,
        part_id UUID NOT NULL REFERENCES spare_parts(id),
        request_id UUID REFERENCES part_sale_requests(id),
        part_code VARCHAR(20),
        part_name VARCHAR(150),
        make VARCHAR(100),
        model VARCHAR(100),
        qty INTEGER NOT NULL DEFAULT 1,
        stock_unit_price NUMERIC(10,2),
        sale_unit_price NUMERIC(10,2) NOT NULL DEFAULT 0,
        total_sale_price NUMERIC(12,2) NOT NULL DEFAULT 0,
        margin NUMERIC(12,2),
        customer_name VARCHAR(100),
        customer_phone VARCHAR(20),
        customer_state VARCHAR(100),
        invoice_no VARCHAR(50),
        payment_mode VARCHAR(20),
        payment_reference VARCHAR(100),
        sold_by VARCHAR(50),
        sold_at TIMESTAMP,
        notes TEXT,
        transport_mode VARCHAR(30),
        transport_via VARCHAR(100),
        tracking_number VARCHAR(100),
        dispatch_date TIMESTAMP,
        delivery_status VARCHAR(30),
        invoice_file_path VARCHAR(500),
        sale_channel VARCHAR(20)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_part_sales_part_id ON part_sales (part_id)",
    "CREATE INDEX IF NOT EXISTS ix_part_sales_sold_by ON part_sales (sold_by)",
]


async def main():
    for stmt in STATEMENTS:
        label = " ".join(stmt.split())[:90]
        print(f"Running: {label}")
        async with engine.begin() as conn:
            await conn.execute(text(stmt))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
