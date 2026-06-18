"""add password reset tokens table

Revision ID: 008_password_reset
Revises: 007_add_weather_forecasts
Create Date: 2026-01-16 14:20:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '008_password_reset'
down_revision = '007_add_weather_forecasts'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'password_reset_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token'),
        sa.ForeignKeyConstraint(['user_id'], ['auth_user.id'], ondelete='CASCADE')
    )
    op.create_index('idx_password_reset_token', 'password_reset_tokens', ['token'])
    op.create_index('idx_password_reset_user_id', 'password_reset_tokens', ['user_id'])


def downgrade():
    op.drop_index('idx_password_reset_user_id', table_name='password_reset_tokens')
    op.drop_index('idx_password_reset_token', table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')
