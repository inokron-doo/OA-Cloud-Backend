"""Add MooHero sync log table

Revision ID: 017_add_moohero_sync_log
Revises: 016_add_moohero_events
Create Date: 2026-02-03 17:01:00

"""
from alembic import op
import sqlalchemy as sa


revision = '017_add_moohero_sync_log'
down_revision = '016_add_moohero_events'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'moohero_sync_log',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('sync_type', sa.String(50), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('records_synced', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('idx_sync_log_type', 'moohero_sync_log', ['sync_type'])
    op.create_index('idx_sync_log_started', 'moohero_sync_log', ['started_at'])


def downgrade():
    op.drop_index('idx_sync_log_started')
    op.drop_index('idx_sync_log_type')
    op.drop_table('moohero_sync_log')
