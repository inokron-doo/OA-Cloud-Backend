"""Add app_settings table

Revision ID: b17fa9de7ab9
Revises: 031
Create Date: 2026-06-03 17:36:40.343036

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b17fa9de7ab9'
down_revision: Union[str, Sequence[str], None] = '031'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'app_settings',
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('key')
    )

def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('app_settings')
