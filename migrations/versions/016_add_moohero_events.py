"""Add MooHero events table

Revision ID: 016_add_moohero_events
Revises: 015_add_animals_table
Create Date: 2026-02-03 17:00:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = '016_add_moohero_events'
down_revision = '015_add_animals_table'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'moohero_events',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('event_id', sa.String(255), nullable=True),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('moohero_collar_unique_id', sa.String(100), nullable=True),
        sa.Column('animal_id', sa.UUID(), nullable=True),
        sa.Column('event_time', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('severity', sa.String(50), nullable=True),
        sa.Column('details', JSONB, nullable=True),
        sa.Column('processed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id'),
        sa.ForeignKeyConstraint(['animal_id'], ['animals.id'], ondelete='SET NULL')
    )
    
    op.create_index('idx_events_animal', 'moohero_events', ['animal_id'])
    op.create_index('idx_events_time', 'moohero_events', ['event_time'])
    op.create_index('idx_events_processed', 'moohero_events', ['processed'])
    op.create_index('idx_events_type', 'moohero_events', ['event_type'])


def downgrade():
    op.drop_index('idx_events_type')
    op.drop_index('idx_events_processed')
    op.drop_index('idx_events_time')
    op.drop_index('idx_events_animal')
    op.drop_table('moohero_events')
