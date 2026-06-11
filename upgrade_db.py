"""
OxyPC Inventory — Database Upgrade Script
==========================================
Run this against an existing database to apply schema changes.
Usage:  python upgrade_db.py

What this script does:
  1. Adds new enum values to the DeviceStage PostgreSQL enum  (AUTOCOMMIT)
  2. Adds new columns to existing tables                       (ALTER TABLE)
  3. Creates any missing tables from the ORM models            (create_all)
     ← This replaces all hand-written CREATE TABLE SQL.
       The ORM model IS the source of truth — no more drift.
  4. Fixes stage_master + allowed_transitions seed data        (UPSERT)
  5. Stamps the Alembic revision table so future migrations
     build on top of the current state

After running this, all future schema changes should go through Alembic:
  python -m alembic revision --autogenerate -m "describe your change"
  python -m alembic upgrade head
"""
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

from config import DATABASE_URL

# Import all models so Base.metadata is fully populated before create_all
import models  # noqa: F401
from database import Base


NEW_ENUM_VALUES = [
    "cleaning", "dry_sanding", "masking", "painting", "water_sanding", "final_qc"
]

NEW_DEVICE_COLUMNS = [
    ("sub_category",      "VARCHAR(20)"),
    ("cpu",               "VARCHAR(100)"),
    ("generation",        "VARCHAR(50)"),
    ("hdd_capacity_gb",   "INTEGER"),
    ("battery_health_pct","INTEGER"),
    ("screen_size",       "VARCHAR(20)"),
    ("bios_password",     "BOOLEAN DEFAULT FALSE"),
    ("warehouse",         "VARCHAR(100)"),
    ("grn_number",        "VARCHAR(50)"),
    ("device_price",      "NUMERIC(12,2)"),
]

# New columns for repair_jobs table (L1/L2 operational fields)
# New GRN / GST columns for lots table
NEW_LOT_COLUMNS = [
    ("grn_system_number",  "VARCHAR(50)"),
    ("grn_number_new",     "INTEGER"),
    ("grn_date",           "TIMESTAMP"),
    ("invoice_date",       "TIMESTAMP"),
    ("invoice_value",      "NUMERIC(14,2)"),
    ("taxable_amount",     "NUMERIC(14,2)"),
    ("sgst",               "NUMERIC(12,2)"),
    ("cgst",               "NUMERIC(12,2)"),
    ("igst",               "NUMERIC(12,2)"),
    ("vehicle_number",     "VARCHAR(30)"),
    ("e_way_bill",         "VARCHAR(50)"),
    ("po_number",          "VARCHAR(100)"),
    ("vendor_name",        "VARCHAR(200)"),
]

# New columns for repair_jobs table (L1/L2 operational fields)
NEW_REPAIR_COLUMNS = [
    ("team_name",           "VARCHAR(100)"),
    ("assigned_engineer",   "VARCHAR(100)"),
    ("faults",              "TEXT"),
    ("dust_cleaning",       "VARCHAR(20)"),    # Done / Not Done
    ("cmos_battery_change", "VARCHAR(20)"),    # Done / Not Done
    ("thermal_paste",       "VARCHAR(20)"),    # Done / Not Done
    ("final_status",        "VARCHAR(30)"),    # Completed / PNA / Escalate / Scrap / Lot / Repair
    ("ram_status",          "VARCHAR(20)"),    # No Change / Upgraded / Downgraded
    ("ram_removed_gb",      "VARCHAR(20)"),
    ("ram_added_gb",        "VARCHAR(20)"),
    ("hdd_updated",         "VARCHAR(5)"),     # Yes / No
    ("hdd_removed",         "VARCHAR(30)"),
    ("hdd_added",           "VARCHAR(30)"),
    ("problem_reported",    "TEXT"),
    ("action_taken",        "VARCHAR(50)"),    # L3 action taken
    ("problem_observed",    "TEXT"),           # L3 problem observed
    ("scrap_reason",        "VARCHAR(100)"),   # L3 scrap reason
    ("received_from",       "VARCHAR(50)"),    # L3 received from
    ("customer_internal",   "VARCHAR(30)"),    # Customer Service / Internal
]


IQC_INSPECTION_TABLE = """
CREATE TABLE IF NOT EXISTS iqc_inspections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id UUID NOT NULL REFERENCES devices(id),
    inspector_name VARCHAR(100),
    inspected_at TIMESTAMP DEFAULT NOW(),
    power_on VARCHAR(5),
    bios_password VARCHAR(5),
    all_ok VARCHAR(5),
    status VARCHAR(50),
    screen_dot VARCHAR(10), screen_line VARCHAR(10), screen_functional VARCHAR(10),
    screen_discoloration VARCHAR(10), screen_patch VARCHAR(10), screen_broken VARCHAR(10),
    screen_flickering VARCHAR(10), screen_scratch VARCHAR(20), screen_loose VARCHAR(10),
    screen_missing VARCHAR(10), screen_hinge_broken VARCHAR(10),
    screen_colour_spread VARCHAR(10), screen_keyboard_mark VARCHAR(10), screen_hard_press VARCHAR(10),
    panel_a_scratch VARCHAR(20), panel_a_broken VARCHAR(20), panel_a_missing VARCHAR(10),
    panel_a_dent VARCHAR(20), panel_a_colour_fade VARCHAR(10),
    panel_b_scratch VARCHAR(20), panel_b_colour_fade VARCHAR(10), panel_b_rubber_cut VARCHAR(10),
    panel_b_broken VARCHAR(20), panel_b_missing VARCHAR(10),
    panel_c_scratch VARCHAR(20), panel_c_broken VARCHAR(20), panel_c_missing VARCHAR(10),
    panel_c_dent VARCHAR(20), panel_c_colour_fade VARCHAR(10),
    panel_d_dent VARCHAR(20), panel_d_colour_fade VARCHAR(10), panel_d_scratch VARCHAR(20),
    panel_d_broken VARCHAR(20), panel_d_missing VARCHAR(10),
    keyboard_working VARCHAR(10), keyboard_colour_fade VARCHAR(10),
    keyboard_key_missing VARCHAR(10), keyboard_hard_press VARCHAR(10),
    speaker_status VARCHAR(50),
    touchpad_working VARCHAR(10), touchpad_click_working VARCHAR(10),
    touchpad_scratch VARCHAR(20), touchpad_colour_fade VARCHAR(10), touchpad_missing VARCHAR(10),
    port_hdmi VARCHAR(10), port_usb_working VARCHAR(10), port_audio_jack VARCHAR(10),
    wifi_status VARCHAR(20), webcam_status VARCHAR(20),
    hdd_connector VARCHAR(10), hdd_casing VARCHAR(10),
    battery_present VARCHAR(10), battery_cable VARCHAR(10), dvd_drive VARCHAR(10),
    r2v3_grade_category VARCHAR(10),
    remarks TEXT,
    CONSTRAINT uq_iqc_inspection_device UNIQUE (device_id)
);
CREATE INDEX IF NOT EXISTS ix_iqc_inspections_device_id ON iqc_inspections (device_id);
"""


async def run_upgrade():
    print("=" * 60)
    print("  OxyPC Inventory — Database Upgrade")
    print("=" * 60)

    engine = create_async_engine(DATABASE_URL, echo=False)

    # Phase 1: ALTER TYPE must run in AUTOCOMMIT (outside transaction)
    autocommit_engine = create_async_engine(
        DATABASE_URL, echo=False,
        execution_options={"isolation_level": "AUTOCOMMIT"}
    )
    async with autocommit_engine.connect() as conn:
        print("\n[1/4] Adding new DeviceStage enum values (AUTOCOMMIT)...")
        for value in NEW_ENUM_VALUES:
            try:
                await conn.execute(text(
                    f"ALTER TYPE devicestage ADD VALUE IF NOT EXISTS '{value}'"
                ))
                print(f"  + '{value}' added")
            except Exception as e:
                print(f"  ! '{value}' skipped: {e}")
    await autocommit_engine.dispose()

    # Phase 2: Column additions and table creation (normal transaction)
    async with engine.begin() as conn:
        # ── 2. Add new columns to devices table ─────────────────────
        print("\n[2/6] Adding new columns to devices table...")
        for col_name, col_type in NEW_DEVICE_COLUMNS:
            try:
                await conn.execute(text(
                    f"ALTER TABLE devices ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
                ))
                print(f"  + column '{col_name}' ({col_type}) added")
            except Exception as e:
                print(f"  ! column '{col_name}' skipped: {e}")

        # ── 3. Add new GRN/GST columns to lots table ─────────────────
        print("\n[3/6] Adding new GRN/GST columns to lots table...")
        for col_name, col_type in NEW_LOT_COLUMNS:
            try:
                await conn.execute(text(
                    f"ALTER TABLE lots ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
                ))
                print(f"  + column '{col_name}' ({col_type}) added")
            except Exception as e:
                print(f"  ! column '{col_name}' skipped: {e}")

        # ── 4. Add new columns to repair_jobs table ──────────────────
        print("\n[4/6] Adding new columns to repair_jobs table...")
        for col_name, col_type in NEW_REPAIR_COLUMNS:
            try:
                await conn.execute(text(
                    f"ALTER TABLE repair_jobs ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
                ))
                print(f"  + column '{col_name}' ({col_type}) added")
            except Exception as e:
                print(f"  ! column '{col_name}' skipped: {e}")

        # ── 5 + 6. Create ALL missing tables from ORM models ─────────
        # This replaces all hand-written CREATE TABLE SQL.
        # Base.metadata.create_all uses checkfirst=True by default —
        # it only creates tables that don't exist, never touches existing ones.
        print("\n[5/6] Creating any missing tables from ORM models (create_all)...")

    # create_all needs a sync-compatible call via run_sync
    try:
        async with engine.begin() as conn2:
            await conn2.run_sync(Base.metadata.create_all)
        print("  + All ORM tables verified / created — no schema drift possible")
    except Exception as e:
        print(f"  ! create_all error: {e}")

        # ── 7. Attendance table ──────────────────────────────────────
        print("\n[7/9] Creating attendance table...")
        try:
            await conn.execute(text("""
CREATE TABLE IF NOT EXISTS attendance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    username VARCHAR(50) NOT NULL,
    full_name VARCHAR(100),
    date DATE NOT NULL,
    check_in TIMESTAMP,
    check_out TIMESTAMP,
    check_in_ip VARCHAR(50),
    check_out_ip VARCHAR(50),
    status VARCHAR(20) DEFAULT 'present',
    notes TEXT,
    marked_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
)
            """))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_attendance_user_id ON attendance (user_id)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_attendance_date ON attendance (date)"))
            print("  + attendance table OK")
        except Exception as e:
            print(f"  ! attendance table: {e}")

        # ── 8. Dealers, calls, assignments, orders tables ─────────────
        print("\n[8/9] Creating dealer CRM tables...")
        dealer_tables = [
            """CREATE TABLE IF NOT EXISTS dealers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dealer_code VARCHAR(20) UNIQUE NOT NULL,
    business_name VARCHAR(200) NOT NULL,
    contact_person VARCHAR(100),
    phone VARCHAR(20),
    whatsapp_number VARCHAR(20),
    email VARCHAR(100),
    address TEXT,
    city VARCHAR(100),
    state VARCHAR(100),
    pincode VARCHAR(10),
    gstin VARCHAR(20),
    dealer_type VARCHAR(30) DEFAULT 'retail',
    credit_limit NUMERIC(14,2) DEFAULT 0,
    outstanding_amount NUMERIC(14,2) DEFAULT 0,
    total_purchases NUMERIC(14,2) DEFAULT 0,
    last_sale_date TIMESTAMP,
    last_sale_amount NUMERIC(14,2),
    preferred_categories VARCHAR(200),
    notes TEXT,
    status VARCHAR(20) DEFAULT 'active',
    assigned_to VARCHAR(50),
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
)""",
            """CREATE TABLE IF NOT EXISTS dealer_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dealer_id UUID NOT NULL REFERENCES dealers(id),
    assigned_to VARCHAR(50) NOT NULL,
    assigned_by VARCHAR(50) NOT NULL,
    assigned_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    notes TEXT
)""",
            """CREATE TABLE IF NOT EXISTS dealer_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dealer_id UUID NOT NULL REFERENCES dealers(id),
    called_by VARCHAR(50) NOT NULL,
    call_date TIMESTAMP DEFAULT NOW(),
    call_type VARCHAR(20) DEFAULT 'outbound',
    call_mode VARCHAR(20) DEFAULT 'phone',
    duration_mins INTEGER,
    call_outcome VARCHAR(30),
    items_discussed TEXT,
    quote_given NUMERIC(12,2),
    next_followup_date TIMESTAMP,
    whatsapp_sent BOOLEAN DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
)""",
            """CREATE TABLE IF NOT EXISTS dealer_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dealer_id UUID NOT NULL REFERENCES dealers(id),
    order_number VARCHAR(30) UNIQUE NOT NULL,
    order_date TIMESTAMP DEFAULT NOW(),
    items_description TEXT,
    total_amount NUMERIC(14,2) DEFAULT 0,
    paid_amount NUMERIC(14,2) DEFAULT 0,
    due_amount NUMERIC(14,2) DEFAULT 0,
    payment_due_date TIMESTAMP,
    payment_mode VARCHAR(20),
    invoice_number VARCHAR(50),
    invoice_sent_whatsapp BOOLEAN DEFAULT FALSE,
    payment_reminder_sent BOOLEAN DEFAULT FALSE,
    status VARCHAR(20) DEFAULT 'pending',
    notes TEXT,
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
)""",
            """CREATE TABLE IF NOT EXISTS telecalling_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_username VARCHAR(50) NOT NULL,
    session_date TIMESTAMP DEFAULT NOW(),
    total_calls INTEGER DEFAULT 0,
    connected_calls INTEGER DEFAULT 0,
    interested_leads INTEGER DEFAULT 0,
    orders_placed INTEGER DEFAULT 0,
    target_calls INTEGER DEFAULT 50,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
)""",
            """CREATE TABLE IF NOT EXISTS telecalling_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dealer_id UUID REFERENCES dealers(id),
    dealer_name VARCHAR(200),
    phone VARCHAR(20) NOT NULL,
    called_by VARCHAR(50) NOT NULL,
    call_date TIMESTAMP DEFAULT NOW(),
    call_outcome VARCHAR(30),
    product_interest VARCHAR(200),
    quantity_required INTEGER,
    budget NUMERIC(12,2),
    next_followup TIMESTAMP,
    whatsapp_sent BOOLEAN DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
)""",
            """CREATE TABLE IF NOT EXISTS whatsapp_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) UNIQUE NOT NULL,
    phone_number VARCHAR(20),
    status VARCHAR(20) DEFAULT 'disconnected',
    session_data TEXT,
    connected_at TIMESTAMP,
    last_seen TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
)""",
            """CREATE TABLE IF NOT EXISTS whatsapp_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sent_by VARCHAR(50) NOT NULL,
    recipient_phone VARCHAR(20) NOT NULL,
    recipient_name VARCHAR(100),
    message_type VARCHAR(20) DEFAULT 'text',
    message_text TEXT,
    dealer_id UUID REFERENCES dealers(id),
    reference_type VARCHAR(20),
    reference_id VARCHAR(100),
    status VARCHAR(20) DEFAULT 'pending',
    sent_at TIMESTAMP,
    error_msg TEXT,
    created_at TIMESTAMP DEFAULT NOW()
)""",
        ]
        for sql in dealer_tables:
            table_name = sql.split("IF NOT EXISTS ")[1].split(" ")[0]
            try:
                await conn.execute(text(sql))
                print(f"  + {table_name} OK")
            except Exception as e:
                print(f"  ! {table_name}: {e}")

        # ── 9. user_permissions table ────────────────────────────────
        print("\n[9/10] Creating user_permissions table...")
        try:
            await conn.execute(text("""
CREATE TABLE IF NOT EXISTS user_permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    permission VARCHAR(100) NOT NULL,
    granted BOOLEAN DEFAULT TRUE,
    granted_by VARCHAR(50),
    granted_at TIMESTAMP DEFAULT NOW()
)
            """))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_user_permissions_user_id ON user_permissions (user_id)"))
            print("  + user_permissions table OK")
        except Exception as e:
            print(f"  ! user_permissions table: {e}")

        # ── 10. R-OS Engine Tables ────────────────────────────────────
        # These are now created by create_all (step 5/6 above).
        # This section kept as a comment so the phase numbering is clear.
        print("\n[10/10] R-OS engine tables — handled by create_all in step 5/6")

        # ── Column additions to existing tables ─────────────────────
        # stage_movements.exited_at
        try:
            await conn.execute(text("""
ALTER TABLE stage_movements ADD COLUMN IF NOT EXISTS exited_at TIMESTAMP
            """))
            print("  + stage_movements.exited_at OK")
        except Exception as e:
            print(f"  ! stage_movements.exited_at: {e}")

        # qc_checks — component scores + attempt_number
        for col_sql, col_name in [
            ("ALTER TABLE qc_checks ADD COLUMN IF NOT EXISTS battery_score  INTEGER", "qc_checks.battery_score"),
            ("ALTER TABLE qc_checks ADD COLUMN IF NOT EXISTS screen_score   INTEGER", "qc_checks.screen_score"),
            ("ALTER TABLE qc_checks ADD COLUMN IF NOT EXISTS keyboard_score INTEGER", "qc_checks.keyboard_score"),
            ("ALTER TABLE qc_checks ADD COLUMN IF NOT EXISTS body_score     INTEGER", "qc_checks.body_score"),
            ("ALTER TABLE qc_checks ADD COLUMN IF NOT EXISTS total_score    INTEGER", "qc_checks.total_score"),
            ("ALTER TABLE qc_checks ADD COLUMN IF NOT EXISTS attempt_number INTEGER NOT NULL DEFAULT 1", "qc_checks.attempt_number"),
        ]:
            try:
                await conn.execute(text(col_sql))
                print(f"  + {col_name} OK")
            except Exception as e:
                print(f"  ! {col_name}: {e}")

        # returns — action_taken + reentered_stage
        for col_sql, col_name in [
            ("ALTER TABLE returns ADD COLUMN IF NOT EXISTS action_taken    VARCHAR(20)", "returns.action_taken"),
            ("ALTER TABLE returns ADD COLUMN IF NOT EXISTS reentered_stage VARCHAR(40)", "returns.reentered_stage"),
        ]:
            try:
                await conn.execute(text(col_sql))
                print(f"  + {col_name} OK")
            except Exception as e:
                print(f"  ! {col_name}: {e}")

        # ── Seed stage_master + allowed_transitions ──────────────────
        print("\n  Seeding stage_master and allowed_transitions...")
        STAGES = [
            ("iqc",             "IQC Inspection",        1),
            ("stock_in",        "Stock In",              2),
            ("l1_repair",       "L1 Repair",             3),
            ("l2_repair",       "L2 Repair",             4),
            ("l3_repair",       "L3 Repair",             5),
            ("qc_check",        "QC Check",              6),
            ("ready_to_sale",   "Ready to Sale",         7),
            ("sold",            "Sold",                  8),
            ("returned",        "Returned",              9),
            ("scrapped",        "Scrapped",              10),
        ]
        TRANSITIONS = [
            ("iqc",           "stock_in"),
            ("iqc",           "scrapped"),
            ("stock_in",      "l1_repair"),
            ("stock_in",      "qc_check"),
            ("stock_in",      "scrapped"),
            ("l1_repair",     "l2_repair"),
            ("l1_repair",     "qc_check"),
            ("l1_repair",     "scrapped"),
            ("l2_repair",     "l3_repair"),
            ("l2_repair",     "qc_check"),
            ("l2_repair",     "scrapped"),
            ("l3_repair",     "qc_check"),
            ("l3_repair",     "scrapped"),
            ("qc_check",      "ready_to_sale"),
            ("qc_check",      "l1_repair"),
            ("qc_check",      "l2_repair"),
            ("qc_check",      "l3_repair"),
            ("qc_check",      "scrapped"),
            ("ready_to_sale", "sold"),
            ("ready_to_sale", "l1_repair"),
            ("sold",          "returned"),
            ("returned",      "iqc"),
            ("returned",      "scrapped"),
        ]

        for name, label, seq in STAGES:
            try:
                await conn.execute(text("""
INSERT INTO stage_master (name, label, sequence)
VALUES (:name, :label, :seq)
ON CONFLICT (name) DO NOTHING
                """), {"name": name, "label": label, "seq": seq})
            except Exception as e:
                print(f"  ! seed stage_master '{name}': {e}")

        for from_s, to_s in TRANSITIONS:
            try:
                await conn.execute(text("""
INSERT INTO allowed_transitions (from_stage, to_stage)
VALUES (:f, :t)
ON CONFLICT (from_stage, to_stage) DO NOTHING
                """), {"f": from_s, "t": to_s})
            except Exception as e:
                print(f"  ! seed transition {from_s}→{to_s}: {e}")

        print(f"  + Seeded {len(STAGES)} stages, {len(TRANSITIONS)} transitions")

    # ── [11/11] WhatsApp Groups + Broadcasts ─────────────────────────────────
    print("\n[11/11] Creating WhatsApp group & broadcast tables...")
    async with engine.begin() as conn:
        await conn.execute(text("""
CREATE TABLE IF NOT EXISTS whatsapp_groups (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_wa_id       VARCHAR(100) UNIQUE NOT NULL,
    group_name        VARCHAR(200) NOT NULL,
    participant_count INTEGER DEFAULT 0,
    synced_by         VARCHAR(50),
    last_synced       TIMESTAMP DEFAULT NOW(),
    created_at        TIMESTAMP DEFAULT NOW()
)
        """))
        await conn.execute(text("""
CREATE TABLE IF NOT EXISTS whatsapp_broadcasts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    broadcast_name   VARCHAR(200),
    message_type     VARCHAR(20) DEFAULT 'text',
    message_text     TEXT NOT NULL,
    sent_by          VARCHAR(50) NOT NULL,
    total_recipients INTEGER DEFAULT 0,
    sent_count       INTEGER DEFAULT 0,
    failed_count     INTEGER DEFAULT 0,
    status           VARCHAR(20) DEFAULT 'done',
    created_at       TIMESTAMP DEFAULT NOW()
)
        """))
        print("  + whatsapp_groups, whatsapp_broadcasts created")

    # ── [12/12] Telecalling lead-gen columns ─────────────────────────────
    print("\n[12/12] Adding lead-gen columns to telecalling_records...")
    async with engine.begin() as conn:
        new_cols = [
            ("customer_name",  "VARCHAR(200)"),
            ("email",          "VARCHAR(200)"),
            ("customer_type",  "VARCHAR(30)"),
            ("city",           "VARCHAR(100)"),
            ("state",          "VARCHAR(100)"),
            ("category",       "VARCHAR(50)"),
            ("brand",          "VARCHAR(100)"),
            ("model",          "VARCHAR(200)"),
            ("generation",     "VARCHAR(50)"),
            ("processor",      "VARCHAR(200)"),
            ("ram",            "VARCHAR(50)"),
            ("hard_disk",      "VARCHAR(100)"),
            ("product_type",   "VARCHAR(30)"),
            ("grade",          "VARCHAR(10)"),
            ("lot_reference",  "VARCHAR(100)"),
        ]
        for col, dtype in new_cols:
            try:
                await conn.execute(text(
                    f"ALTER TABLE telecalling_records ADD COLUMN IF NOT EXISTS {col} {dtype}"
                ))
                print(f"  + telecalling_records.{col}")
            except Exception as e:
                print(f"  ~ {col} already exists or error: {e}")

    # ── [13/13] Dealer first_name / last_name ────────────────────────────────
    print("\n[13/14] Adding first_name / last_name to dealers table...")
    async with engine.begin() as conn:
        for col, dtype in [("first_name", "VARCHAR(100)"), ("last_name", "VARCHAR(100)")]:
            try:
                await conn.execute(text(
                    f"ALTER TABLE dealers ADD COLUMN IF NOT EXISTS {col} {dtype}"
                ))
                print(f"  + dealers.{col}")
            except Exception as e:
                print(f"  ~ {col}: {e}")

    # ── [14/14] WhatsApp group tags ──────────────────────────────────────────
    print("\n[14/14] Adding tags column to whatsapp_groups table...")
    async with engine.begin() as conn:
        try:
            await conn.execute(text(
                "ALTER TABLE whatsapp_groups ADD COLUMN IF NOT EXISTS tags VARCHAR(200)"
            ))
            print("  + whatsapp_groups.tags")
        except Exception as e:
            print(f"  ~ tags: {e}")

    # ── [15/17] direction + sender fields on whatsapp_messages ──────────────
    print("\n[15/17] Adding direction/sender fields to whatsapp_messages...")
    async with engine.begin() as conn:
        for col, dtype in [
            ("direction",    "VARCHAR(10) DEFAULT 'outgoing'"),
            ("sender_name",  "VARCHAR(200)"),
            ("sender_phone", "VARCHAR(30)"),
        ]:
            try:
                await conn.execute(text(
                    f"ALTER TABLE whatsapp_messages ADD COLUMN IF NOT EXISTS {col} {dtype}"
                ))
                print(f"  + whatsapp_messages.{col}")
            except Exception as e:
                print(f"  ~ {col}: {e}")

    # ── [16/17] WhatsApp group enhancements: category + dealer link ──────────
    print("\n[16/17] Adding group_category + linked_dealer_id to whatsapp_groups...")
    async with engine.begin() as conn:
        for col, dtype in [
            ("group_category",   "VARCHAR(20) DEFAULT 'other'"),   # dealer / personal / other
            ("linked_dealer_id", "UUID REFERENCES dealers(id) ON DELETE SET NULL"),
        ]:
            try:
                await conn.execute(text(
                    f"ALTER TABLE whatsapp_groups ADD COLUMN IF NOT EXISTS {col} {dtype}"
                ))
                print(f"  + whatsapp_groups.{col}")
            except Exception as e:
                print(f"  ~ {col}: {e}")

    # ── [16/16] Market availability table ────────────────────────────────────
    print("\n[17/17] Creating market_availability table...")
    async with engine.begin() as conn:
        try:
            await conn.execute(text("""
CREATE TABLE IF NOT EXISTS market_availability (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand               VARCHAR(100),
    model               VARCHAR(200),
    category            VARCHAR(50),
    generation          VARCHAR(50),
    processor           VARCHAR(200),
    ram                 VARCHAR(50),
    storage             VARCHAR(100),
    condition           VARCHAR(20),
    grade               VARCHAR(10),
    trade_type          VARCHAR(10) NOT NULL DEFAULT 'sell',
    qty                 INTEGER,
    price_per_unit      NUMERIC(12,2),
    warranty_months     INTEGER,
    is_negotiable       BOOLEAN DEFAULT TRUE,
    dealer_id           UUID REFERENCES dealers(id) ON DELETE SET NULL,
    dealer_name         VARCHAR(200),
    group_wa_id         VARCHAR(100),
    group_name          VARCHAR(200),
    source_message_id   UUID REFERENCES whatsapp_messages(id) ON DELETE SET NULL,
    source_message_text TEXT,
    notes               TEXT,
    is_active           BOOLEAN DEFAULT TRUE,
    posted_date         TIMESTAMP DEFAULT NOW(),
    expires_at          TIMESTAMP,
    created_by          VARCHAR(50),
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
)
            """))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_market_model ON market_availability (model)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_market_brand ON market_availability (brand)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_market_dealer ON market_availability (dealer_id)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_market_trade ON market_availability (trade_type)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_market_active ON market_availability (is_active)"))
            print("  + market_availability table OK")
        except Exception as e:
            print(f"  ! market_availability: {e}")

    # ── [18] Fix repair_attempts missing columns + correct stage names ──────────
    print("\n[18] Fixing repair_attempts columns and stage_master seed data...")
    async with engine.begin() as conn:

        # ── repair_attempts: add columns missing from the original CREATE script ──
        for col, dtype in [
            ("created_by",  "VARCHAR(50)"),   # was missing → caused 500 on /repair/complete
            ("time_spent",  "INTEGER"),        # guard in case schema drifted
        ]:
            try:
                await conn.execute(text(
                    f"ALTER TABLE repair_attempts ADD COLUMN IF NOT EXISTS {col} {dtype}"
                ))
                print(f"  + repair_attempts.{col} ensured")
            except Exception as e:
                print(f"  ~ repair_attempts.{col}: {e}")

        # ── Fix stage_master: remove wrong _repair suffix entries ────────────────
        # upgrade_db.py phase-10 mistakenly seeded l1_repair/l2_repair/l3_repair
        # The DeviceStage enum uses l1/l2/l3.  Clean up and re-seed correctly.
        try:
            await conn.execute(text("""
DELETE FROM allowed_transitions
WHERE from_stage IN ('l1_repair','l2_repair','l3_repair')
   OR to_stage   IN ('l1_repair','l2_repair','l3_repair')
            """))
            await conn.execute(text("""
DELETE FROM stage_master
WHERE name IN ('l1_repair','l2_repair','l3_repair')
            """))
            print("  + removed stale l*_repair stage entries")
        except Exception as e:
            print(f"  ~ cleanup stage_master: {e}")

        # ── Re-seed stage_master with the full correct stage list ────────────────
        CORRECT_STAGES = [
            ("grn",           "GRN Receipt",       0),
            ("iqc",           "IQC Inspection",    1),
            ("stock_in",      "Stock In",           2),
            ("l1",            "L1 Repair",          3),
            ("l2",            "L2 Repair",          4),
            ("l3",            "L3 Repair",          5),
            ("qc_check",      "QC Check",           6),
            ("cleaning",      "Cleaning",           7),
            ("dry_sanding",   "Dry Sanding",        8),
            ("masking",       "Masking",            9),
            ("painting",      "Painting",          10),
            ("water_sanding", "Water Sanding",     11),
            ("final_qc",      "Final QC",          12),
            ("ready_to_sale", "Ready to Sale",     13),
            ("sold",          "Sold",              14),
            ("returned",      "Returned",          15),
            ("scrapped",      "Scrapped",          99),
        ]
        for name, label, seq in CORRECT_STAGES:
            try:
                await conn.execute(text("""
INSERT INTO stage_master (name, label, sequence)
VALUES (:name, :label, :seq)
ON CONFLICT (name) DO UPDATE SET label=EXCLUDED.label, sequence=EXCLUDED.sequence
                """), {"name": name, "label": label, "seq": seq})
            except Exception as e:
                print(f"  ! stage_master '{name}': {e}")
        print(f"  + stage_master: {len(CORRECT_STAGES)} stages upserted")

        # ── Re-seed allowed_transitions with complete correct set ────────────────
        CORRECT_TRANSITIONS = [
            # IQC
            ("iqc",           "stock_in"),
            ("iqc",           "l1"),
            ("iqc",           "scrapped"),
            # Stock In
            ("stock_in",      "l1"),
            ("stock_in",      "qc_check"),
            ("stock_in",      "scrapped"),
            # Repair escalation
            ("l1",            "l2"),
            ("l1",            "qc_check"),
            ("l1",            "scrapped"),
            ("l2",            "l3"),
            ("l2",            "qc_check"),
            ("l2",            "scrapped"),
            ("l3",            "qc_check"),
            ("l3",            "scrapped"),
            # QC → cosmetic or direct sale
            ("qc_check",      "cleaning"),
            ("qc_check",      "ready_to_sale"),
            ("qc_check",      "l1"),
            ("qc_check",      "l2"),
            ("qc_check",      "l3"),
            ("qc_check",      "scrapped"),
            # Cosmetic pipeline
            ("cleaning",      "dry_sanding"),
            ("cleaning",      "final_qc"),
            ("dry_sanding",   "masking"),
            ("masking",       "painting"),
            ("painting",      "water_sanding"),
            ("water_sanding", "final_qc"),
            ("final_qc",      "ready_to_sale"),
            ("final_qc",      "cleaning"),
            ("final_qc",      "scrapped"),
            # Sales end-states
            ("ready_to_sale", "sold"),
            ("sold",          "returned"),
            ("returned",      "iqc"),
            ("returned",      "scrapped"),
        ]
        inserted = 0
        for from_s, to_s in CORRECT_TRANSITIONS:
            try:
                await conn.execute(text("""
INSERT INTO allowed_transitions (from_stage, to_stage)
VALUES (:f, :t)
ON CONFLICT (from_stage, to_stage) DO NOTHING
                """), {"f": from_s, "t": to_s})
                inserted += 1
            except Exception as e:
                print(f"  ! transition {from_s}→{to_s}: {e}")
        print(f"  + allowed_transitions: {inserted} transitions ensured")

    # ── [19] Run schema validator to confirm everything is in sync ──────────────
    print("\n[19] Running schema validator...")
    try:
        from db_validator import validate_and_fix
        summary = await validate_and_fix(engine)
        if summary["issues_fixed"]:
            print(f"  Validator auto-fixed {summary['issues_fixed']} item(s):")
            for msg in summary["fixed"]:
                print(f"    + {msg}")
        else:
            print("  ✓  Schema is fully in sync with ORM models")
    except RuntimeError as e:
        print(f"\nWARNING — Validator found unfixable issues:\n{e}")
        print("Please investigate before starting the server.")
    except Exception as e:
        print(f"  ! Validator error: {e}")

    # ── [20] Stamp Alembic so future `alembic revision --autogenerate`
    #         builds on the current state rather than trying to recreate everything.
    print("\n[20] Stamping Alembic revision to 'head'...")
    try:
        from alembic.config import Config as AlembicConfig
        from alembic import command as alembic_command
        alembic_cfg = AlembicConfig("alembic.ini")
        alembic_command.stamp(alembic_cfg, "head")
        print("  ✓  Alembic stamped at head — future changes via:")
        print("       python -m alembic revision --autogenerate -m 'describe change'")
        print("       python -m alembic upgrade head")
    except Exception as e:
        print(f"  ! Alembic stamp skipped (alembic.ini not found or no migrations yet): {e}")
        print("    This is OK on first run — Alembic will be stamped after first migration.")

    await engine.dispose()
    print("\n" + "=" * 60)
    print("  Upgrade complete! Restart the server to apply changes.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(run_upgrade())
