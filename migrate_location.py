"""
OxyPC Inventory — Location Tracking Migration
Run ONCE to add the 4 new location-tracking tables.
Usage: python migrate_location.py
"""
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

from config import DATABASE_URL


async def create_enum_if_missing(conn, type_name: str, values: list[str]):
    """Create a PostgreSQL enum type only if it doesn't already exist."""
    result = await conn.execute(
        text("SELECT 1 FROM pg_type WHERE typname = :t"),
        {"t": type_name}
    )
    if result.fetchone():
        print(f"    enum '{type_name}' already exists — skipped")
        return
    vals = ", ".join(f"'{v}'" for v in values)
    await conn.execute(text(f"CREATE TYPE {type_name} AS ENUM ({vals})"))
    print(f"    enum '{type_name}' created")


async def run():
    print("=" * 55)
    print("  OxyPC — Location Tracking Migration")
    print("=" * 55)

    engine = create_async_engine(DATABASE_URL, echo=False)

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        print("  DB connection: OK\n")
    except Exception as e:
        print(f"\nERROR: Cannot connect to database.\n  {e}")
        sys.exit(1)

    async with engine.begin() as conn:

        # ── 1. Enum types ──────────────────────────────────────────────────
        print("[1/5] Creating enum types...")
        await create_enum_if_missing(conn, "zonetype", [
            "showroom", "ground_floor", "first_floor", "second_floor",
            "workshop", "dispatch", "warehouse", "holding"
        ])
        await create_enum_if_missing(conn, "unittype", [
            "rack", "crate", "shelf", "trolley", "cabinet", "floor"
        ])
        await create_enum_if_missing(conn, "locationaction", [
            "assigned", "picked_up", "placed_back", "moved"
        ])
        await create_enum_if_missing(conn, "auditstatus", [
            "pending", "in_progress", "completed"
        ])
        await create_enum_if_missing(conn, "scanstatus", [
            "found", "missing", "extra"
        ])

        # ── 2. storage_locations ───────────────────────────────────────────
        print("[2/5] Creating table: storage_locations...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS storage_locations (
                id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
                zone        zonetype    NOT NULL,
                unit_type   unittype    NOT NULL,
                unit_id     VARCHAR(50) NOT NULL UNIQUE,
                slot        VARCHAR(20),
                description VARCHAR(200),
                capacity    INTEGER,
                is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
                created_at  TIMESTAMP   NOT NULL DEFAULT NOW()
            )
        """))
        print("    table 'storage_locations' ready")

        # ── 3. device_location_logs ────────────────────────────────────────
        print("[3/5] Creating table: device_location_logs...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS device_location_logs (
                id          UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
                device_id   UUID           NOT NULL REFERENCES devices(id),
                location_id UUID           REFERENCES storage_locations(id),
                action      locationaction NOT NULL,
                actor_id    UUID           NOT NULL REFERENCES users(id),
                actor_name  VARCHAR(100),
                notes       TEXT,
                logged_at   TIMESTAMP      NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_dll_device_id "
            "ON device_location_logs(device_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_dll_location_id "
            "ON device_location_logs(location_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_dll_logged_at "
            "ON device_location_logs(logged_at)"
        ))
        print("    table 'device_location_logs' + indexes ready")

        # ── 4. inventory_audits ────────────────────────────────────────────
        print("[4/5] Creating table: inventory_audits...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS inventory_audits (
                id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
                audit_number      VARCHAR(30) NOT NULL UNIQUE,
                zone_filter       VARCHAR(50),
                status            auditstatus NOT NULL DEFAULT 'pending',
                initiated_by      UUID        NOT NULL REFERENCES users(id),
                initiated_by_name VARCHAR(100),
                initiated_at      TIMESTAMP   NOT NULL DEFAULT NOW(),
                completed_at      TIMESTAMP,
                notes             TEXT,
                expected_count    INTEGER     NOT NULL DEFAULT 0,
                found_count       INTEGER     NOT NULL DEFAULT 0,
                missing_count     INTEGER     NOT NULL DEFAULT 0,
                extra_count       INTEGER     NOT NULL DEFAULT 0
            )
        """))
        print("    table 'inventory_audits' ready")

        # ── 5. audit_scan_items ────────────────────────────────────────────
        print("[5/5] Creating table: audit_scan_items...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS audit_scan_items (
                id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
                audit_id        UUID        NOT NULL REFERENCES inventory_audits(id),
                device_id       UUID        REFERENCES devices(id),
                barcode_scanned VARCHAR(100) NOT NULL,
                location_id     UUID        REFERENCES storage_locations(id),
                scan_status     scanstatus  NOT NULL,
                scanned_by      UUID        REFERENCES users(id),
                scanned_by_name VARCHAR(100),
                scanned_at      TIMESTAMP   NOT NULL DEFAULT NOW(),
                notes           TEXT
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_asi_audit_id "
            "ON audit_scan_items(audit_id)"
        ))
        print("    table 'audit_scan_items' + index ready")

    await engine.dispose()

    print("\n" + "=" * 55)
    print("  Migration complete! 4 new tables created:")
    print("    storage_locations")
    print("    device_location_logs")
    print("    inventory_audits")
    print("    audit_scan_items")
    print("\n  Next steps:")
    print("  1. Restart the server: python main.py")
    print("  2. Go to: Inventory Locations -> Manage Locations")
    print("  3. Create your zones/racks/crates")
    print("  4. Start assigning devices to locations")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    asyncio.run(run())
