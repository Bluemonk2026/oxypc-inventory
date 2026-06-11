"""
Add webhooks and event_log tables — Sprint 17b event system.

Revision ID: 20260430_0900
Revises: 20260429_1200
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260430_0900'
down_revision = '20260429_1200'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'webhooks',
        sa.Column('id',          postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name',        sa.String(100), nullable=False),
        sa.Column('url',         sa.String(500), nullable=False),
        sa.Column('secret_hash', sa.String(64),  nullable=False),
        sa.Column('event_types', sa.JSON(),       nullable=False,
                  server_default='[]'),
        sa.Column('is_active',   sa.Boolean(),    nullable=False,
                  server_default='true'),
        sa.Column('created_by',  sa.String(50),   nullable=False),
        sa.Column('created_at',  sa.DateTime(),   nullable=False,
                  server_default=sa.func.now()),
        sa.Column('deleted_at',  sa.DateTime(),   nullable=True),
    )
    op.create_index('ix_webhooks_is_active', 'webhooks', ['is_active'])

    op.create_table(
        'event_log',
        sa.Column('id',               postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('event_type',       sa.String(50),  nullable=False),
        sa.Column('payload',          sa.JSON(),       nullable=False),
        sa.Column('source_module',    sa.String(50),   nullable=True),
        sa.Column('published_at',     sa.DateTime(),   nullable=False,
                  server_default=sa.func.now()),
        sa.Column('webhook_attempts', sa.Integer(),    nullable=False,
                  server_default='0'),
        sa.Column('last_attempt_at',  sa.DateTime(),   nullable=True),
        sa.Column('last_status_code', sa.Integer(),    nullable=True),
    )
    op.create_index('ix_event_log_event_type',   'event_log', ['event_type'])
    op.create_index('ix_event_log_published_at', 'event_log', ['published_at'])


def downgrade() -> None:
    op.drop_index('ix_event_log_published_at', table_name='event_log')
    op.drop_index('ix_event_log_event_type',   table_name='event_log')
    op.drop_table('event_log')
    op.drop_index('ix_webhooks_is_active', table_name='webhooks')
    op.drop_table('webhooks')
