"""
delete_lots_bulk.py  — One-off script to permanently delete specific lots
                       and ALL their associated devices + child records.

Usage (from the oxypc-inventory directory):
    python delete_lots_bulk.py            # dry-run: shows what would be deleted
    python delete_lots_bulk.py --delete   # actually deletes (asks for confirmation)

Cascade order mirrors the route in routers/stock.py:
  spare_parts_consumption → ram_tracking → spare_parts_ledger
  → audit_scan_items → device_location_logs → qc_checks
  → iqc_inspections → repair_attempts → repair_jobs
  → device_costing → device_aging → stage_movements
  → returns → sales → stock_transfers → devices → lots
"""

import asyncio
import sys
import os

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Lot numbers to delete ────────────────────────────────────────────────────
LOT_NUMBERS = [
    "00-outdated-20",  # only failed lot remaining
]
# ─────────────────────────────────────────────────────────────────────────────

DRY_RUN   = "--delete" not in sys.argv
SKIP_CONFIRM = "--yes" in sys.argv

# Read DB URL from .env (same directory)
_env_path = os.path.join(os.path.dirname(__file__), ".env")
DB_URL = None
if os.path.exists(_env_path):
    for line in open(_env_path):
        line = line.strip()
        if line.startswith("OXYPC_DATABASE_URL="):
            raw = line.split("=", 1)[1]
            # strip postgresql+asyncpg:// → postgresql://
            DB_URL = raw.replace("postgresql+asyncpg://", "postgresql://")
            break
if not DB_URL:
    print("ERROR: Could not read OXYPC_DATABASE_URL from .env")
    sys.exit(1)


async def run():
    try:
        import asyncpg
    except ImportError:
        print("ERROR: asyncpg not installed. Run: pip install asyncpg")
        sys.exit(1)

    # asyncpg wants postgresql:// (not postgresql+asyncpg://)
    conn = await asyncpg.connect(DB_URL)
    print(f"\n{'DRY RUN — nothing will be deleted' if DRY_RUN else '⚠️  LIVE DELETE MODE'}")
    print(f"Checking {len(LOT_NUMBERS)} lot numbers...\n")

    found = []
    not_found = []

    for lot_number in LOT_NUMBERS:
        row = await conn.fetchrow(
            "SELECT id, lot_number, supplier_name, qty FROM lots WHERE lot_number = $1",
            lot_number
        )
        if row:
            device_count = await conn.fetchval(
                "SELECT COUNT(*) FROM devices WHERE lot_id = $1", row["id"]
            )
            found.append({
                "id": row["id"],
                "lot_number": row["lot_number"],
                "supplier": row["supplier_name"],
                "qty": row["qty"],
                "devices": device_count,
            })
            print(f"  ✓ FOUND   {row['lot_number']:<25}  supplier={row['supplier_name']:<30}  qty={row['qty']}  devices={device_count}")
        else:
            not_found.append(lot_number)
            print(f"  ✗ MISSING {lot_number}")

    print(f"\nSummary: {len(found)} found / {len(not_found)} not found")
    print(f"Devices that will be deleted: {sum(r['devices'] for r in found)}")

    if not found:
        print("\nNothing to delete. Exiting.")
        await conn.close()
        return

    if DRY_RUN:
        print("\nThis was a DRY RUN. Re-run with --delete to actually delete.")
        await conn.close()
        return

    # ── Confirm before deleting ──────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"You are about to PERMANENTLY delete {len(found)} lot(s) and all their data.")
    print("This CANNOT be undone.")
    print(f"{'─'*60}")
    if not SKIP_CONFIRM:
        answer = input("Type YES to confirm deletion: ").strip().upper()
        if answer != "YES":
            print("Aborted.")
            await conn.close()
            return
    else:
        print("Auto-confirmed via --yes flag. Proceeding...")

    # ── Cascade delete ───────────────────────────────────────────────────────
    deleted = []
    errors  = []

    for lot in found:
        lot_id     = str(lot["id"])
        lot_number = lot["lot_number"]
        try:
            async with conn.transaction():
                tables = [
                    "spare_parts_consumption",
                    "spare_parts_ledger",
                    "audit_scan_items",
                    "device_location_logs",
                    "qc_checks",
                    "iqc_inspections",
                    "repair_attempts",
                    "repair_jobs",
                    "device_costing",
                    "device_aging",
                    "stage_movements",
                    "returns",
                    "stock_transfers",
                ]
                for table in tables:
                    await conn.execute(
                        f"DELETE FROM {table} "
                        f"WHERE device_id IN (SELECT id FROM devices WHERE lot_id = $1::uuid)",
                        lot_id,
                    )
                # customer_receipts links via sale_id → sales.id, not device_id
                await conn.execute(
                    "DELETE FROM customer_receipts "
                    "WHERE sale_id IN ("
                    "  SELECT id FROM sales "
                    "  WHERE device_id IN (SELECT id FROM devices WHERE lot_id = $1::uuid)"
                    ")",
                    lot_id,
                )
                await conn.execute(
                    "DELETE FROM sales "
                    "WHERE device_id IN (SELECT id FROM devices WHERE lot_id = $1::uuid)",
                    lot_id,
                )
                # ram_tracking has two device FK columns
                await conn.execute(
                    "DELETE FROM ram_tracking "
                    "WHERE device_id IN (SELECT id FROM devices WHERE lot_id = $1::uuid) "
                    "OR destination_device_id IN (SELECT id FROM devices WHERE lot_id = $1::uuid)",
                    lot_id,
                )
                # nullify CRM sourcing deal links
                await conn.execute(
                    "UPDATE crm_sourcing_deals SET linked_lot_id = NULL WHERE linked_lot_id = $1::uuid",
                    lot_id,
                )
                # delete devices
                dev_del = await conn.execute(
                    "DELETE FROM devices WHERE lot_id = $1::uuid", lot_id
                )
                # delete lot line items + lot
                await conn.execute(
                    "DELETE FROM lot_line_items WHERE lot_id = $1::uuid", lot_id
                )
                await conn.execute(
                    "DELETE FROM lots WHERE id = $1::uuid", lot_id
                )
            deleted.append(lot_number)
            print(f"  ✓ DELETED {lot_number}  ({dev_del.split()[-1]} devices removed)")
        except Exception as exc:
            errors.append((lot_number, str(exc)))
            print(f"  ✗ ERROR   {lot_number}: {exc}")

    await conn.close()

    print(f"\n{'─'*60}")
    print(f"Done. {len(deleted)} deleted / {len(errors)} errors / {len(not_found)} not found.")
    if errors:
        print("\nErrors:")
        for lot_number, msg in errors:
            print(f"  {lot_number}: {msg}")
    if not_found:
        print("\nNot found (skipped):")
        for n in not_found:
            print(f"  {n}")


asyncio.run(run())
