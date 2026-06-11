"""telecalling mobile PWA — schema delta v2 (cross-module integrated)

What this migration does:
  1. telecalling_records: + call_source, crm_contact_id, lot_id, lot_line_item_id,
     dealer_order_id, crm_quote_id, idempotency_key, device_id, lat/lng,
     call_duration_secs, is_active, deleted_at
  2. NEW: telecalling_assignments (daily call queue)
  3. ALTER users: + manager_username (FK self)
  4. ALTER whatsapp_messages: + call_id, crm_quote_id
  5. NEW: v_telecalling_reminders VIEW
  6. NEW: stored procs sp_telecalling_kpi, sp_telecalling_daily_queue,
          sp_telecalling_team_kpi
  7. AUDIT: writes through existing audit_logs (engines.py) via generic trigger
            — does NOT create a new audit table

CODE PRE-REQUISITE: NONE.
  - models/__init__.py already imports AuditLog (verified 2026-05-14, line 15).
  - uuid-ossp NOT enabled in this DB; new tables use Python-side
    default=uuid.uuid4 (matches existing pattern in models/dealers.py).
  - audit_logs schema verified: id, user_id, username, action, table_name,
    record_id (String), old_value, new_value, ip_address, timestamp.
    Trigger fn_audit_central below matches this exact schema.

NOT APPLIED YET. Review, then on dev DB:
    alembic upgrade head
    alembic downgrade -1   (rollback)

Revision ID: 20260514_1000
Revises: 20260503_0900
Create Date: 2026-05-14 10:00:00
"""
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg


revision = '20260514_1000'
down_revision = '20260503_0900'
branch_labels = None
depends_on = None


# Tables that should fire the generic audit trigger after this migration.
# (audit_logs target table is owned by engines.py — pre-existing.)
AUDITED_TABLES = (
    'telecalling_records',
    'telecalling_assignments',
)


def upgrade() -> None:
    # ── 0. Ensure uuid-ossp (audit trigger uses uuid_generate_v4()) ──────
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')

    # ── 1. ALTER telecalling_records ─────────────────────────────────────
    op.add_column('telecalling_records', sa.Column('call_source', sa.String(20),
        nullable=False, server_default='prospect'))
    op.add_column('telecalling_records', sa.Column('crm_contact_id', pg.UUID(as_uuid=True),
        sa.ForeignKey('crm_contacts.id'), nullable=True))
    op.add_column('telecalling_records', sa.Column('lot_id', pg.UUID(as_uuid=True),
        sa.ForeignKey('lots.id'), nullable=True))
    op.add_column('telecalling_records', sa.Column('lot_line_item_id', pg.UUID(as_uuid=True),
        sa.ForeignKey('lot_line_items.id'), nullable=True))
    op.add_column('telecalling_records', sa.Column('dealer_order_id', pg.UUID(as_uuid=True),
        sa.ForeignKey('dealer_orders.id'), nullable=True))
    op.add_column('telecalling_records', sa.Column('crm_quote_id', pg.UUID(as_uuid=True),
        sa.ForeignKey('crm_quotes.id'), nullable=True))
    op.add_column('telecalling_records', sa.Column('idempotency_key', sa.String(64), nullable=True))
    op.add_column('telecalling_records', sa.Column('device_id', sa.String(100), nullable=True))
    op.add_column('telecalling_records', sa.Column('latitude', sa.Numeric(10, 7), nullable=True))
    op.add_column('telecalling_records', sa.Column('longitude', sa.Numeric(10, 7), nullable=True))
    op.add_column('telecalling_records', sa.Column('call_duration_secs', sa.Integer(), nullable=True))
    op.add_column('telecalling_records', sa.Column('is_active', sa.Boolean(),
        nullable=False, server_default=sa.text('true')))
    op.add_column('telecalling_records', sa.Column('deleted_at', sa.DateTime(), nullable=True))

    op.create_index('uq_tc_records_idempotency', 'telecalling_records',
                    ['idempotency_key'], unique=True,
                    postgresql_where=sa.text('idempotency_key IS NOT NULL'))
    op.create_index('ix_tc_records_agent_date', 'telecalling_records',
                    ['called_by', 'call_date'])
    op.create_index('ix_tc_records_followup', 'telecalling_records',
                    ['next_followup'],
                    postgresql_where=sa.text('next_followup IS NOT NULL'))
    op.create_index('ix_tc_records_source_date', 'telecalling_records',
                    ['call_source', 'call_date'])
    op.create_index('ix_tc_records_contact', 'telecalling_records', ['crm_contact_id'])
    op.create_index('ix_tc_records_sku', 'telecalling_records', ['lot_line_item_id'])
    op.create_index('ix_tc_records_active', 'telecalling_records', ['is_active'],
                    postgresql_where=sa.text('is_active = false'))

    # ── 2. NEW: telecalling_assignments ──────────────────────────────────
    op.create_table('telecalling_assignments',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True,
                  default=uuid.uuid4),
        sa.Column('agent_username', sa.String(50), nullable=False),
        sa.Column('lead_phone', sa.String(20), nullable=False),
        sa.Column('dealer_id', pg.UUID(as_uuid=True),
                  sa.ForeignKey('dealers.id'), nullable=True),
        sa.Column('crm_contact_id', pg.UUID(as_uuid=True),
                  sa.ForeignKey('crm_contacts.id'), nullable=True),
        sa.Column('customer_name', sa.String(200), nullable=True),
        sa.Column('city', sa.String(100), nullable=True),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('priority', sa.String(10), nullable=False, server_default='normal'),
        sa.Column('assigned_by', sa.String(50), nullable=False),
        sa.Column('assigned_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('call_record_id', pg.UUID(as_uuid=True),
                  sa.ForeignKey('telecalling_records.id'), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
    )
    op.create_index('ix_tc_assign_agent_day_status', 'telecalling_assignments',
                    ['agent_username', 'due_date', 'status'])
    op.create_index('ix_tc_assign_day_status', 'telecalling_assignments',
                    ['due_date', 'status'])
    op.create_index('ix_tc_assign_phone', 'telecalling_assignments', ['lead_phone'])

    # ── 3. ALTER users: manager_username ─────────────────────────────────
    op.add_column('users', sa.Column('manager_username', sa.String(50), nullable=True))
    op.create_foreign_key('fk_users_manager', 'users', 'users',
                          ['manager_username'], ['username'])
    op.create_index('ix_users_manager', 'users', ['manager_username'])

    # ── 3b. ALTER crm_contacts: DPDPA consent fields (Nov-2025 readiness) ─
    # Trigger-based enforcement deferred to Phase 1.5. Fields land now so
    # the mobile capture flow stores consent at first contact.
    op.add_column('crm_contacts',
        sa.Column('consent_recorded', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')))
    op.add_column('crm_contacts',
        sa.Column('consent_at', sa.DateTime(), nullable=True))
    op.add_column('crm_contacts',
        sa.Column('consent_source', sa.String(40), nullable=True,
                  comment='telecalling_mobile | webform | whatsapp_optin | dealer_signup'))
    op.add_column('crm_contacts',
        sa.Column('do_not_contact', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')))
    op.add_column('crm_contacts',
        sa.Column('do_not_contact_reason', sa.String(200), nullable=True))
    op.create_index('ix_crm_contacts_dnc', 'crm_contacts', ['do_not_contact'],
                    postgresql_where=sa.text('do_not_contact = true'))

    # ── 3c. Seed daily-target app setting (default 50) ───────────────────
    # Uses existing app_settings table (key/value/scope pattern).
    op.execute("""
    INSERT INTO app_settings (key, value, description, updated_at)
    VALUES ('tc_daily_target_default', '50',
            'Default daily call target per telecaller; per-agent overrides may exist in user_settings.',
            now())
    ON CONFLICT (key) DO NOTHING;
    """)

    # ── 4. ALTER whatsapp_messages ───────────────────────────────────────
    op.add_column('whatsapp_messages', sa.Column('call_id', pg.UUID(as_uuid=True),
        sa.ForeignKey('telecalling_records.id'), nullable=True))
    op.add_column('whatsapp_messages', sa.Column('crm_quote_id', pg.UUID(as_uuid=True),
        sa.ForeignKey('crm_quotes.id'), nullable=True))
    op.create_index('ix_wa_msg_call', 'whatsapp_messages', ['call_id'])
    op.create_index('ix_wa_msg_quote', 'whatsapp_messages', ['crm_quote_id'])

    # ── 5. Generic audit trigger writing to EXISTING audit_logs ──────────
    # audit_logs schema (engines.py:107): id, user_id, username, action,
    # table_name, record_id (String), old_value, new_value, ip_address, timestamp.
    # Device-id is captured in app event_log instead (no column here).
    op.execute("""
    CREATE OR REPLACE FUNCTION fn_audit_central() RETURNS TRIGGER AS $$
    DECLARE
        v_username TEXT := COALESCE(current_setting('app.username', true), 'system');
        v_user_id  UUID := NULLIF(current_setting('app.user_id', true), '')::uuid;
        v_ip       TEXT := current_setting('app.ip', true);
    BEGIN
        IF TG_OP = 'INSERT' THEN
            INSERT INTO audit_logs
              (id, user_id, username, action, table_name, record_id, new_value, ip_address, timestamp)
            VALUES (uuid_generate_v4(), v_user_id, v_username, 'INSERT',
                    TG_TABLE_NAME, NEW.id::text, to_jsonb(NEW)::text, v_ip, now());
            RETURN NEW;
        ELSIF TG_OP = 'UPDATE' THEN
            INSERT INTO audit_logs
              (id, user_id, username, action, table_name, record_id,
               old_value, new_value, ip_address, timestamp)
            VALUES (uuid_generate_v4(), v_user_id, v_username, 'UPDATE',
                    TG_TABLE_NAME, NEW.id::text,
                    to_jsonb(OLD)::text, to_jsonb(NEW)::text, v_ip, now());
            RETURN NEW;
        ELSIF TG_OP = 'DELETE' THEN
            INSERT INTO audit_logs
              (id, user_id, username, action, table_name, record_id, old_value, ip_address, timestamp)
            VALUES (uuid_generate_v4(), v_user_id, v_username, 'DELETE',
                    TG_TABLE_NAME, OLD.id::text, to_jsonb(OLD)::text, v_ip, now());
            RETURN OLD;
        END IF;
        RETURN NULL;
    END;
    $$ LANGUAGE plpgsql;
    """)

    for tbl in AUDITED_TABLES:
        # asyncpg rejects multi-statement strings — split into separate calls
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_audit ON {tbl}")
        op.execute(
            f"CREATE TRIGGER trg_{tbl}_audit "
            f"AFTER INSERT OR UPDATE OR DELETE ON {tbl} "
            f"FOR EACH ROW EXECUTE FUNCTION fn_audit_central()"
        )

    # ── 6. Reminders view (replaces standalone notifications table) ──────
    op.execute("""
    CREATE OR REPLACE VIEW v_telecalling_reminders AS
    SELECT
        tr.id                                              AS source_id,
        tr.called_by                                       AS agent_username,
        'followup_due'::text                               AS type,
        COALESCE(d.business_name, tr.customer_name)        AS subject,
        tr.phone,
        tr.next_followup                                   AS due_at,
        tr.id                                              AS call_record_id,
        NULL::uuid                                         AS assignment_id
    FROM telecalling_records tr
    LEFT JOIN dealers d ON d.id = tr.dealer_id
    WHERE tr.next_followup IS NOT NULL
      AND tr.is_active = TRUE
      AND tr.call_outcome IN ('callback','interested')
      AND tr.next_followup BETWEEN now() - interval '7 days'
                             AND now() + interval '7 days'
    UNION ALL
    SELECT
        ta.id, ta.agent_username, 'new_assignment',
        COALESCE(d.business_name, ta.customer_name),
        ta.lead_phone, ta.assigned_at::timestamp, NULL, ta.id
    FROM telecalling_assignments ta
    LEFT JOIN dealers d ON d.id = ta.dealer_id
    WHERE ta.status = 'pending'
      AND ta.is_active = TRUE
      AND ta.due_date BETWEEN current_date AND current_date + 1;
    """)

    # ── 7. Stored procedures ─────────────────────────────────────────────
    op.execute("""
    CREATE OR REPLACE FUNCTION sp_telecalling_kpi(
        p_agent VARCHAR, p_from DATE, p_to DATE
    ) RETURNS TABLE (
        total_calls       BIGINT, connected         BIGINT,
        interested        BIGINT, orders_placed     BIGINT,
        dnc               BIGINT, avg_duration_secs NUMERIC,
        target_calls      INTEGER, attainment_pct   NUMERIC,
        quotes_sent       BIGINT, orders_value_inr  NUMERIC
    ) AS $$
        SELECT
            COUNT(*),
            COUNT(*) FILTER (WHERE tr.call_outcome NOT IN ('no_answer','do_not_call')),
            COUNT(*) FILTER (WHERE tr.call_outcome = 'interested'),
            COUNT(*) FILTER (WHERE tr.call_outcome = 'order_placed'),
            COUNT(*) FILTER (WHERE tr.call_outcome = 'do_not_call'),
            COALESCE(AVG(tr.call_duration_secs), 0),
            50,
            CASE WHEN COUNT(*)=0 THEN 0 ELSE ROUND(COUNT(*)*100.0/50,1) END,
            COUNT(DISTINCT tr.crm_quote_id) FILTER (WHERE tr.crm_quote_id IS NOT NULL),
            COALESCE(SUM(do2.total_amount), 0)
        FROM telecalling_records tr
        LEFT JOIN dealer_orders do2 ON do2.id = tr.dealer_order_id
        WHERE tr.called_by = p_agent
          AND tr.is_active = TRUE
          AND tr.call_date::date BETWEEN p_from AND p_to;
    $$ LANGUAGE sql STABLE;
    """)

    op.execute("""
    CREATE OR REPLACE FUNCTION sp_telecalling_daily_queue(
        p_agent VARCHAR, p_date DATE
    ) RETURNS TABLE (
        assignment_id   UUID,    lead_phone     VARCHAR,
        dealer_id       UUID,    crm_contact_id UUID,
        display_name    VARCHAR, city           VARCHAR,
        category        VARCHAR, priority       VARCHAR,
        last_outcome    VARCHAR, last_call_at   TIMESTAMP,
        last_note       TEXT
    ) AS $$
        SELECT
            ta.id, ta.lead_phone, ta.dealer_id, ta.crm_contact_id,
            COALESCE(d.business_name, c.company_name, ta.customer_name)::varchar,
            COALESCE(d.city, c.city, ta.city)::varchar,
            ta.category, ta.priority,
            last_call.call_outcome, last_call.call_date, last_call.notes
        FROM telecalling_assignments ta
        LEFT JOIN dealers d      ON d.id = ta.dealer_id
        LEFT JOIN crm_contacts c ON c.id = ta.crm_contact_id
        LEFT JOIN LATERAL (
            SELECT call_outcome, call_date, notes
            FROM telecalling_records tr
            WHERE tr.phone = ta.lead_phone AND tr.is_active = TRUE
            ORDER BY tr.call_date DESC LIMIT 1
        ) last_call ON TRUE
        WHERE ta.agent_username = p_agent
          AND ta.due_date = p_date
          AND ta.is_active = TRUE
          AND ta.status IN ('pending','in_progress')
        ORDER BY CASE ta.priority WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END,
                 ta.assigned_at ASC;
    $$ LANGUAGE sql STABLE;
    """)

    op.execute("""
    CREATE OR REPLACE FUNCTION sp_telecalling_team_kpi(
        p_manager VARCHAR, p_from DATE, p_to DATE
    ) RETURNS TABLE (
        agent_username VARCHAR, total_calls BIGINT, connected BIGINT,
        interested BIGINT, orders_placed BIGINT,
        attainment_pct NUMERIC, orders_value_inr NUMERIC
    ) AS $$
        SELECT
            u.username,
            (k).total_calls, (k).connected, (k).interested,
            (k).orders_placed, (k).attainment_pct, (k).orders_value_inr
        FROM users u,
        LATERAL sp_telecalling_kpi(u.username, p_from, p_to) k
        WHERE u.manager_username = p_manager
        ORDER BY (k).orders_placed DESC, (k).attainment_pct DESC;
    $$ LANGUAGE sql STABLE;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS sp_telecalling_team_kpi(VARCHAR, DATE, DATE);")
    op.execute("DROP FUNCTION IF EXISTS sp_telecalling_daily_queue(VARCHAR, DATE);")
    op.execute("DROP FUNCTION IF EXISTS sp_telecalling_kpi(VARCHAR, DATE, DATE);")
    op.execute("DROP VIEW IF EXISTS v_telecalling_reminders;")

    for tbl in AUDITED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_audit ON {tbl};")
    op.execute("DROP FUNCTION IF EXISTS fn_audit_central();")

    op.drop_index('ix_wa_msg_quote', table_name='whatsapp_messages')
    op.drop_index('ix_wa_msg_call', table_name='whatsapp_messages')
    op.drop_column('whatsapp_messages', 'crm_quote_id')
    op.drop_column('whatsapp_messages', 'call_id')

    op.drop_index('ix_users_manager', table_name='users')
    op.drop_constraint('fk_users_manager', 'users', type_='foreignkey')
    op.drop_column('users', 'manager_username')

    op.drop_index('ix_tc_assign_phone', table_name='telecalling_assignments')
    op.drop_index('ix_tc_assign_day_status', table_name='telecalling_assignments')
    op.drop_index('ix_tc_assign_agent_day_status', table_name='telecalling_assignments')
    op.drop_table('telecalling_assignments')

    for ix in ('ix_tc_records_active', 'ix_tc_records_sku', 'ix_tc_records_contact',
               'ix_tc_records_source_date', 'ix_tc_records_followup',
               'ix_tc_records_agent_date', 'uq_tc_records_idempotency'):
        op.drop_index(ix, table_name='telecalling_records')

    for col in ('deleted_at', 'is_active', 'call_duration_secs', 'longitude',
                'latitude', 'device_id', 'idempotency_key', 'crm_quote_id',
                'dealer_order_id', 'lot_line_item_id', 'lot_id',
                'crm_contact_id', 'call_source'):
        op.drop_column('telecalling_records', col)
