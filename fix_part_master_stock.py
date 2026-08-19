"""Part Master correction: min_stock_alert -> 0, and In Stock / 5.

The bulk upload previously accumulated stock (+= qty) on every upload and
stamped min_stock_alert=5 on new rows. Both are fixed in routers/spare_parts.py;
this repairs the data those runs left behind.

DRY RUN by default. Pass --apply to write.

Divides qty_in_stock by 5 using integer division and reports every row where
that is not exact, so a value that was NOT the product of five uploads is
visible before anything is written.
"""
import asyncio
import sys

sys.path.insert(0, "/opt/oxypc" if sys.platform != "win32" else ".")

from sqlalchemy import select  # noqa: E402
from database import AsyncSessionLocal  # noqa: E402
from models.spare_parts import SparePart  # noqa: E402

APPLY = "--apply" in sys.argv


async def main():
    async with AsyncSessionLocal() as db:
        parts = (await db.execute(select(SparePart))).scalars().all()

        alert_rows = [p for p in parts if int(p.min_stock_alert or 0) != 0]
        stock_rows = [p for p in parts if int(p.qty_in_stock or 0) > 0]
        not_divisible = [p for p in stock_rows if int(p.qty_in_stock or 0) % 5 != 0]

        print(f"Part Master rows                : {len(parts)}")
        print(f"min_stock_alert != 0            : {len(alert_rows)}")
        print(f"qty_in_stock > 0                : {len(stock_rows)}")
        print(f"  of which NOT divisible by 5   : {len(not_divisible)}")
        print()

        if not_divisible:
            print("Rows whose stock is not an exact multiple of 5 — these were")
            print("probably NOT inflated by five uploads. Review before applying:")
            for p in not_divisible[:25]:
                print(f"  {p.part_code:>12}  {(p.name or '')[:38]:<38} "
                      f"{int(p.qty_in_stock or 0):>6} -> {int(p.qty_in_stock or 0)//5}")
            if len(not_divisible) > 25:
                print(f"  … and {len(not_divisible) - 25} more")
            print()

        total_before = sum(int(p.qty_in_stock or 0) for p in parts)
        total_after = sum(int(p.qty_in_stock or 0) // 5 for p in parts)
        print(f"Total units before : {total_before:,}")
        print(f"Total units after  : {total_after:,}")
        print()

        print("Sample of the change (first 15 rows with stock):")
        for p in stock_rows[:15]:
            q = int(p.qty_in_stock or 0)
            print(f"  {p.part_code:>12}  {(p.name or '')[:38]:<38} "
                  f"stock {q:>6} -> {q//5:<6}  alert {int(p.min_stock_alert or 0)} -> 0")

        if not APPLY:
            print("\nDRY RUN — nothing written. Re-run with --apply to commit.")
            return

        for p in parts:
            p.qty_in_stock = int(p.qty_in_stock or 0) // 5
            p.min_stock_alert = 0
        await db.commit()
        print(f"\nAPPLIED — {len(parts)} rows updated.")


if __name__ == "__main__":
    asyncio.run(main())
