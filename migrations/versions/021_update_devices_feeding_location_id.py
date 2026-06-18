from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '021'
down_revision = '020'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'devices',
        sa.Column('feeding_location_id', postgresql.UUID(), nullable=True)
    )
    op.create_foreign_key(
        'fk_devices_feeding_location_id',
        'devices',
        'feeding_locations',
        ['feeding_location_id'],
        ['feeding_location_id']
    )
    op.drop_constraint('devices_barn_id_fkey', 'devices', type_='foreignkey')
    op.drop_column('devices', 'barn_id')


def downgrade():
    op.add_column(
        'devices',
        sa.Column('barn_id', postgresql.UUID(), nullable=True)
    )
    op.create_foreign_key(
        'devices_barn_id_fkey',
        'devices',
        'barns',
        ['barn_id'],
        ['barn_id']
    )
    op.drop_constraint('fk_devices_feeding_location_id', 'devices', type_='foreignkey')
    op.drop_column('devices', 'feeding_location_id')
