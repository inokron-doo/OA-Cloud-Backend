"""Add animals table with MooHero integration

Revision ID: 015_add_animals_table
Revises: 014_add_moohero_farm_mapping
Create Date: 2026-02-03 16:59:00

"""
from alembic import op
import sqlalchemy as sa


revision = '015_add_animals_table'
down_revision = '014_add_moohero_farm_mapping'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'animals',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('moohero_collar_unique_id', sa.String(100), nullable=True),
        sa.Column('barn_id', sa.UUID(), nullable=True),
        sa.Column('feeding_location_id', sa.UUID(), nullable=True),
        sa.Column('animal_name', sa.String(255), nullable=True),
        sa.Column('animal_type', sa.String(100), nullable=True),
        sa.Column('health_score', sa.Float(), nullable=True),
        sa.Column('last_health_update', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('farm_calendar_animal_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('moohero_collar_unique_id'),
        sa.ForeignKeyConstraint(['barn_id'], ['farm_management_farmparcel.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['feeding_location_id'], ['feeding_locations.feeding_location_id'], ondelete='SET NULL')
    )
    
    op.create_index('idx_animals_barn', 'animals', ['barn_id'])
    op.create_index('idx_animals_collar', 'animals', ['moohero_collar_unique_id'])


def downgrade():
    op.drop_index('idx_animals_collar')
    op.drop_index('idx_animals_barn')
    op.drop_table('animals')
