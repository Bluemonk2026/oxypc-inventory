"""add stress_test_results table

Revision ID: 20260626_1100
Revises: 20260626_0002
Create Date: 2026-06-26

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '20260626_1100'
down_revision: Union[str, None] = '20260626_0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'stress_test_results',
        sa.Column('id',             sa.Integer(),                     nullable=False),
        sa.Column('barcode',        sa.String(100),                   nullable=False),
        sa.Column('brand',          sa.String(100),                   nullable=True),
        sa.Column('model_name',     sa.String(200),                   nullable=True),
        sa.Column('run_at',         sa.DateTime(timezone=True),       nullable=False,
                  server_default=sa.func.now()),
        sa.Column('duration',       sa.String(20),                    nullable=True),
        sa.Column('overall_status', sa.String(30),                    nullable=True),
        sa.Column('results_json',   sa.JSON(),                        nullable=True),
        sa.Column('pdf_path',       sa.Text(),                        nullable=True),
        sa.Column('run_by',         sa.String(100),                   nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_stress_test_results_barcode', 'stress_test_results', ['barcode'])
    op.create_index('ix_stress_test_results_run_at',  'stress_test_results', ['run_at'])


def downgrade() -> None:
    op.drop_index('ix_stress_test_results_run_at',  table_name='stress_test_results')
    op.drop_index('ix_stress_test_results_barcode', table_name='stress_test_results')
    op.drop_table('stress_test_results')
