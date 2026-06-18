"""add user_id to farm_management_farm

Revision ID: 010_add_user_id_farm
Revises: 009_update_barn_fks
Create Date: 2026-01-18 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '010_add_user_id_farm'
down_revision = '009_update_barn_fks'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('farm_management_farm',
        sa.Column('user_id', sa.Integer(), nullable=True)
    )


def downgrade():
    op.drop_column('farm_management_farm', 'user_id')
