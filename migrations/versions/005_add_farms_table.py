"""add farms table

Revision ID: 005_add_farms_table
Revises: 004_add_weather_batch_id
Create Date: 2026-01-08

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '005_add_farms_table'
down_revision = '004_add_weather_batch_id'
branch_labels = None
depends_on = None


def upgrade():
    # Create farms table
    op.create_table('farms',
        sa.Column('id', postgresql.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        # auth_user is the live user table (app_users was dropped in migration 003)
        sa.ForeignKeyConstraint(['user_id'], ['auth_user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Add farm_id column to barns table
    op.add_column('barns', 
        sa.Column('farm_id', postgresql.UUID(), nullable=True)
    )
    
    # Add foreign key constraint
    op.create_foreign_key(
        'barns_farm_id_fkey',
        'barns', 'farms',
        ['farm_id'], ['id'],
        ondelete='CASCADE'
    )
    
    # Create indexes for better query performance
    op.create_index('idx_farms_user_id', 'farms', ['user_id'])
    op.create_index('idx_barns_farm_id', 'barns', ['farm_id'])


def downgrade():
    # Drop indexes
    op.drop_index('idx_barns_farm_id', table_name='barns')
    op.drop_index('idx_farms_user_id', table_name='farms')
    
    # Drop foreign key constraint
    op.drop_constraint('barns_farm_id_fkey', 'barns', type_='foreignkey')
    
    # Drop farm_id column from barns
    op.drop_column('barns', 'farm_id')
    
    # Drop farms table
    op.drop_table('farms')
