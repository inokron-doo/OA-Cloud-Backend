"""Add MooHero farm mapping table

Revision ID: 014_add_moohero_farm_mapping
Revises: 013_add_feeding_activity_type
Create Date: 2026-02-03 16:58:00

"""
from alembic import op
import sqlalchemy as sa


revision = '014_add_moohero_farm_mapping'
down_revision = '013_add_feeding_activity_type'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'moohero_farm_mapping',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('moohero_farm_id', sa.Integer(), nullable=False),
        sa.Column('moohero_farm_name', sa.String(255), nullable=True),
        sa.Column('barn_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('moohero_farm_id'),
        sa.ForeignKeyConstraint(['barn_id'], ['farm_management_farmparcel.id'], ondelete='CASCADE')
    )


def downgrade():
    op.drop_table('moohero_farm_mapping')
