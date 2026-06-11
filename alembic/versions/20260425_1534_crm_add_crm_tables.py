"""add_crm_tables

Revision ID: crm_add_crm_tables
Revises: 0c716e3ade5c
Create Date: 2026-04-25 15:34:00

Adds 6 tables for the CRM module:
  crm_contacts, crm_sourcing_deals, crm_sales_opportunities,
  crm_quotes, crm_quote_items, crm_activities
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = 'crm_add_crm_tables'
down_revision: Union[str, None] = '0c716e3ade5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── crm_contacts ─────────────────────────────────────────────────────────
    op.create_table('crm_contacts',
        sa.Column('id',             UUID(as_uuid=True), primary_key=True),
        sa.Column('contact_code',   sa.String(20),  nullable=False),
        sa.Column('contact_type',   sa.String(20),  nullable=True,  server_default='supplier'),
        sa.Column('company_name',   sa.String(200), nullable=False),
        sa.Column('contact_person', sa.String(100), nullable=True),
        sa.Column('phone',          sa.String(20),  nullable=True),
        sa.Column('whatsapp',       sa.String(20),  nullable=True),
        sa.Column('email',          sa.String(100), nullable=True),
        sa.Column('gstin',          sa.String(20),  nullable=True),
        sa.Column('pan',            sa.String(20),  nullable=True),
        sa.Column('address',        sa.Text(),      nullable=True),
        sa.Column('city',           sa.String(100), nullable=True),
        sa.Column('state',          sa.String(100), nullable=True),
        sa.Column('pincode',        sa.String(10),  nullable=True),
        sa.Column('source_type',    sa.String(30),  nullable=True),
        sa.Column('buyer_type',     sa.String(30),  nullable=True),
        sa.Column('credit_limit',   sa.Numeric(14, 2), nullable=True, server_default='0'),
        sa.Column('outstanding',    sa.Numeric(14, 2), nullable=True, server_default='0'),
        sa.Column('tags',           sa.String(300), nullable=True),
        sa.Column('notes',          sa.Text(),      nullable=True),
        sa.Column('status',         sa.String(20),  nullable=True, server_default='active'),
        sa.Column('assigned_to',    sa.String(50),  nullable=True),
        sa.Column('created_by',     sa.String(50),  nullable=True),
        sa.Column('created_at',     sa.DateTime(),  nullable=True),
        sa.Column('updated_at',     sa.DateTime(),  nullable=True),
    )
    op.create_index('ix_crm_contacts_contact_code', 'crm_contacts', ['contact_code'], unique=True)
    op.create_index('ix_crm_contacts_company_name', 'crm_contacts', ['company_name'])
    op.create_index('ix_crm_contacts_phone',        'crm_contacts', ['phone'])

    # ── crm_quotes (before sourcing_deals so FK can reference it) ────────────
    op.create_table('crm_quotes',
        sa.Column('id',                 UUID(as_uuid=True), primary_key=True),
        sa.Column('quote_number',       sa.String(30),  nullable=False),
        sa.Column('contact_id',         UUID(as_uuid=True), sa.ForeignKey('crm_contacts.id'), nullable=True),
        sa.Column('quote_date',         sa.Date(),      nullable=True),
        sa.Column('valid_until',        sa.Date(),      nullable=True),
        sa.Column('payment_terms',      sa.String(200), nullable=True),
        sa.Column('special_conditions', sa.Text(),      nullable=True),
        sa.Column('total_amount',       sa.Numeric(14, 2), nullable=True, server_default='0'),
        sa.Column('status',             sa.String(20),  nullable=True, server_default='draft'),
        sa.Column('sent_at',            sa.DateTime(),  nullable=True),
        sa.Column('created_by',         sa.String(50),  nullable=True),
        sa.Column('created_at',         sa.DateTime(),  nullable=True),
        sa.Column('updated_at',         sa.DateTime(),  nullable=True),
    )
    op.create_index('ix_crm_quotes_quote_number', 'crm_quotes', ['quote_number'], unique=True)

    # ── crm_quote_items ───────────────────────────────────────────────────────
    op.create_table('crm_quote_items',
        sa.Column('id',            UUID(as_uuid=True), primary_key=True),
        sa.Column('quote_id',      UUID(as_uuid=True), sa.ForeignKey('crm_quotes.id'), nullable=False),
        sa.Column('line_number',   sa.Integer(),    nullable=True, server_default='1'),
        sa.Column('device_type',   sa.String(100),  nullable=False),
        sa.Column('material_type', sa.String(30),   nullable=True),
        sa.Column('grade',         sa.String(10),   nullable=True),
        sa.Column('quantity',      sa.Integer(),    nullable=False, server_default='1'),
        sa.Column('unit_price',    sa.Numeric(10, 2), nullable=False),
        sa.Column('total_price',   sa.Numeric(14, 2), nullable=False),
        sa.Column('specs_note',    sa.Text(),       nullable=True),
        sa.Column('sort_order',    sa.Integer(),    nullable=True, server_default='0'),
    )

    # ── crm_sourcing_deals ────────────────────────────────────────────────────
    op.create_table('crm_sourcing_deals',
        sa.Column('id',                   UUID(as_uuid=True), primary_key=True),
        sa.Column('deal_number',          sa.String(30),  nullable=False),
        sa.Column('contact_id',           UUID(as_uuid=True), sa.ForeignKey('crm_contacts.id'), nullable=True),
        sa.Column('title',                sa.String(300), nullable=False),
        sa.Column('source_type',          sa.String(30),  nullable=True),
        sa.Column('device_type',          sa.String(50),  nullable=True),
        sa.Column('est_quantity',         sa.Integer(),   nullable=True),
        sa.Column('material_type',        sa.String(30),  nullable=True),
        sa.Column('asking_price_unit',    sa.Numeric(10, 2), nullable=True),
        sa.Column('asking_price_total',   sa.Numeric(14, 2), nullable=True),
        sa.Column('our_offer_unit',       sa.Numeric(10, 2), nullable=True),
        sa.Column('our_offer_total',      sa.Numeric(14, 2), nullable=True),
        sa.Column('final_price_unit',     sa.Numeric(10, 2), nullable=True),
        sa.Column('final_price_total',    sa.Numeric(14, 2), nullable=True),
        sa.Column('stage',                sa.String(30),  nullable=True, server_default='lead'),
        sa.Column('inspection_date',      sa.Date(),      nullable=True),
        sa.Column('inspection_result',    sa.String(20),  nullable=True),
        sa.Column('inspection_notes',     sa.Text(),      nullable=True),
        sa.Column('expected_pickup_date', sa.Date(),      nullable=True),
        sa.Column('payment_advance_pct',  sa.Integer(),   nullable=True, server_default='0'),
        sa.Column('payment_terms',        sa.Text(),      nullable=True),
        sa.Column('linked_lot_id',        UUID(as_uuid=True), sa.ForeignKey('lots.id'), nullable=True),
        sa.Column('win_loss_reason',      sa.Text(),      nullable=True),
        sa.Column('assigned_to',          sa.String(50),  nullable=True),
        sa.Column('priority',             sa.String(10),  nullable=True, server_default='medium'),
        sa.Column('notes',                sa.Text(),      nullable=True),
        sa.Column('created_by',           sa.String(50),  nullable=True),
        sa.Column('created_at',           sa.DateTime(),  nullable=True),
        sa.Column('updated_at',           sa.DateTime(),  nullable=True),
    )
    op.create_index('ix_crm_sourcing_deals_deal_number', 'crm_sourcing_deals', ['deal_number'], unique=True)
    op.create_index('ix_crm_sourcing_deals_stage',       'crm_sourcing_deals', ['stage'])

    # ── crm_sales_opportunities ───────────────────────────────────────────────
    op.create_table('crm_sales_opportunities',
        sa.Column('id',                  UUID(as_uuid=True), primary_key=True),
        sa.Column('opp_number',          sa.String(30),  nullable=False),
        sa.Column('contact_id',          UUID(as_uuid=True), sa.ForeignKey('crm_contacts.id'), nullable=True),
        sa.Column('title',               sa.String(300), nullable=False),
        sa.Column('buyer_type',          sa.String(30),  nullable=True),
        sa.Column('device_type',         sa.String(50),  nullable=True),
        sa.Column('required_qty',        sa.Integer(),   nullable=True),
        sa.Column('material_type',       sa.String(30),  nullable=True),
        sa.Column('grade_required',      sa.String(10),  nullable=True),
        sa.Column('budget_per_unit',     sa.Numeric(10, 2), nullable=True),
        sa.Column('stage',               sa.String(30),  nullable=True, server_default='lead'),
        sa.Column('quote_id',            UUID(as_uuid=True), sa.ForeignKey('crm_quotes.id'), nullable=True),
        sa.Column('linked_sale_ids',     sa.Text(),      nullable=True),
        sa.Column('expected_close_date', sa.Date(),      nullable=True),
        sa.Column('estimated_value',     sa.Numeric(14, 2), nullable=True),
        sa.Column('win_loss_reason',     sa.Text(),      nullable=True),
        sa.Column('assigned_to',         sa.String(50),  nullable=True),
        sa.Column('priority',            sa.String(10),  nullable=True, server_default='medium'),
        sa.Column('notes',               sa.Text(),      nullable=True),
        sa.Column('created_by',          sa.String(50),  nullable=True),
        sa.Column('created_at',          sa.DateTime(),  nullable=True),
        sa.Column('updated_at',          sa.DateTime(),  nullable=True),
    )
    op.create_index('ix_crm_sales_opportunities_opp_number', 'crm_sales_opportunities', ['opp_number'], unique=True)
    op.create_index('ix_crm_sales_opportunities_stage',      'crm_sales_opportunities', ['stage'])

    # ── crm_activities ────────────────────────────────────────────────────────
    op.create_table('crm_activities',
        sa.Column('id',                   UUID(as_uuid=True), primary_key=True),
        sa.Column('contact_id',           UUID(as_uuid=True), sa.ForeignKey('crm_contacts.id'), nullable=True),
        sa.Column('deal_id',              UUID(as_uuid=True), nullable=True),
        sa.Column('deal_type',            sa.String(20),  nullable=True),
        sa.Column('activity_type',        sa.String(20),  nullable=True, server_default='call'),
        sa.Column('direction',            sa.String(10),  nullable=True),
        sa.Column('summary',              sa.Text(),      nullable=False),
        sa.Column('outcome',              sa.String(30),  nullable=True),
        sa.Column('performed_by',         sa.String(50),  nullable=False),
        sa.Column('activity_date',        sa.DateTime(),  nullable=True),
        sa.Column('next_followup',        sa.DateTime(),  nullable=True),
        sa.Column('followup_assigned_to', sa.String(50),  nullable=True),
        sa.Column('followup_done',        sa.Boolean(),   nullable=True, server_default='false'),
        sa.Column('created_at',           sa.DateTime(),  nullable=True),
    )
    op.create_index('ix_crm_activities_deal_id',    'crm_activities', ['deal_id'])
    op.create_index('ix_crm_activities_contact_id', 'crm_activities', ['contact_id'])


def downgrade() -> None:
    op.drop_table('crm_activities')
    op.drop_table('crm_sales_opportunities')
    op.drop_table('crm_sourcing_deals')
    op.drop_table('crm_quote_items')
    op.drop_table('crm_quotes')
    op.drop_table('crm_contacts')
