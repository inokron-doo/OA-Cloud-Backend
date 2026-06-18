"""update telemetry_readings uniqueness

Revision ID: 022_update_telemetry_readings_unique
Revises: 021_update_devices_feeding_location_id
Create Date: 2026-03-08

"""
from alembic import op

revision = '022'
down_revision = '021'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('telemetry_readings_pkey', 'telemetry_readings', type_='primary')
    op.create_unique_constraint(
        'uq_telemetry_readings_time_device',
        'telemetry_readings',
        ['time', 'device_id']
    )


def downgrade():
    op.drop_constraint('uq_telemetry_readings_time_device', 'telemetry_readings', type_='unique')
    op.create_primary_key('telemetry_readings_pkey', 'telemetry_readings', ['time'])
