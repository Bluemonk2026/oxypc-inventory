"""
OxyPC Inventory — Production missing-object fix (telecalling KPI/queue)
alembic/versions/20260514_1000_telecalling_mobile_pwa.py was only partially
applied to production: its column/table/index changes (steps 1-4) landed,
but its VIEW, audit trigger function, and 3 stored procedures (steps 5-7)
never made it — alembic_version on production was somehow stamped past
this revision without those objects actually being created, so `alembic
upgrade` won't re-run it. This causes /api/v1/telecalling/session/today,
/assigned-leads, /followups/today, /kpi/dashboard, /kpi/team to 500 with
"function sp_telecalling_kpi(...) does not exist".

Verified before writing this: telecalling_records/telecalling_assignments
tables and users.manager_username already exist in production (steps 1-4
of the source migration are present) — only recreating the missing
view/trigger/procs below.

Usage: python migrate_fix_prod_telecalling_procs.py
Backup taken first: backups/pre_prod_sync_<timestamp>.dump
"""
import asyncio
from sqlalchemy import text
from database import engine

AUDITED_TABLES = ("telecalling_records", "telecalling_assignments")

STATEMENTS = [
    """
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
    """,
    """
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
    """,
    """
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
    """,
    """
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
    """,
    """
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
    """,
]


async def main():
    async with engine.begin() as conn:
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        for stmt in STATEMENTS:
            print(f"Running: {stmt.strip().splitlines()[0]} ...")
            await conn.execute(text(stmt))
        for tbl in AUDITED_TABLES:
            await conn.execute(text(f"DROP TRIGGER IF EXISTS trg_{tbl}_audit ON {tbl}"))
            await conn.execute(text(
                f"CREATE TRIGGER trg_{tbl}_audit "
                f"AFTER INSERT OR UPDATE OR DELETE ON {tbl} "
                f"FOR EACH ROW EXECUTE FUNCTION fn_audit_central()"
            ))
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
