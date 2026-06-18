from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
    
    # APP_USERS
    op.create_table('app_users',
        sa.Column('user_id', postgresql.UUID(), nullable=False),
        sa.Column('username', sa.Text(), nullable=True),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('display_name', sa.Text(), nullable=True),
        sa.Column('email', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('user_id')
    )
    
    # BARNS
    op.create_table('barns',
        sa.Column('barn_id', postgresql.UUID(), nullable=False),
        sa.Column('name', sa.Text(), nullable=True),
        sa.Column('latitude', sa.Double(), nullable=True),
        sa.Column('longitude', sa.Double(), nullable=True),
        sa.PrimaryKeyConstraint('barn_id')
    )
    
    # FEEDING_LOCATIONS
    op.create_table('feeding_locations',
        sa.Column('feeding_location_id', postgresql.UUID(), nullable=False),
        sa.Column('external_id', sa.Text(), nullable=True),
        sa.Column('barn_id', postgresql.UUID(), nullable=True),
        sa.Column('name', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['barn_id'], ['barns.barn_id']),
        sa.PrimaryKeyConstraint('feeding_location_id')
    )
    
    # DEVICES
    op.create_table('devices',
        sa.Column('device_id', postgresql.UUID(), nullable=False),
        sa.Column('device_eui', sa.Text(), nullable=True),
        sa.Column('barn_id', postgresql.UUID(), nullable=True),
        sa.Column('display_name', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['barn_id'], ['barns.barn_id']),
        sa.PrimaryKeyConstraint('device_id')
    )
    
    # DEVICE_FEEDING_LOCATION_MAP
    op.create_table('device_feeding_location_map',
        sa.Column('device_id', postgresql.UUID(), nullable=False),
        sa.Column('feeding_location_id', postgresql.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['device_id'], ['devices.device_id']),
        sa.ForeignKeyConstraint(['feeding_location_id'], ['feeding_locations.feeding_location_id']),
        sa.PrimaryKeyConstraint('device_id', 'feeding_location_id')
    )
    
    # IOT_RAW_MESSAGES
    op.create_table('iot_raw_messages',
        sa.Column('raw_id', sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column('device_eui', sa.Text(), nullable=True),
        sa.Column('enqueued_time', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('body', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('raw_id')
    )
    
    # TELEMETRY_READINGS
    op.create_table('telemetry_readings',
        sa.Column('time', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('device_eui', sa.Text(), nullable=True),
        sa.Column('device_id', sa.UUID(), nullable=True),
        sa.Column('barn_id', postgresql.UUID(), nullable=True),
        sa.Column('feeding_location_id', postgresql.UUID(), nullable=True),
        sa.Column('reading_kind', sa.Text(), nullable=True),
        sa.Column('numeric_value', sa.Double(), nullable=True),
        sa.Column('temperature', sa.Double(), nullable=True),
        sa.Column('humidity', sa.Double(), nullable=True),
        sa.Column('raw', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['barn_id'], ['barns.barn_id']),
        sa.ForeignKeyConstraint(['feeding_location_id'], ['feeding_locations.feeding_location_id']),
        sa.ForeignKeyConstraint(['device_id'], ['devices.device_id']),
        sa.PrimaryKeyConstraint('time')
    )
    
    # Try to create hypertable if TimescaleDB is available
    try:
        op.execute("""
            SELECT create_hypertable('telemetry_readings', 'time',
                if_not_exists => TRUE,
                chunk_time_interval => INTERVAL '1 day'
            );
        """)
    except:
        pass  # TimescaleDB not installed, skip
    
    # WEATHER_OBSERVATIONS
    op.create_table('weather_observations',
        sa.Column('obs_id', postgresql.UUID(), nullable=False),
        sa.Column('obs_time', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('lat', sa.Double(), nullable=True),
        sa.Column('lon', sa.Double(), nullable=True),
        sa.Column('temperature', sa.Double(), nullable=True),
        sa.Column('humidity', sa.Double(), nullable=True),
        sa.Column('thi', sa.Double(), nullable=True),
        sa.Column('raw', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('obs_id')
    )
    
    # SYSTEM_EVENTS
    op.create_table('system_events',
        sa.Column('event_id', postgresql.UUID(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('event_type', sa.Text(), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('event_id')
    )
    
    # CALENDAR_EVENT_LINKS
    op.create_table('calendar_event_links',
        sa.Column('link_id', postgresql.UUID(), nullable=False),
        sa.Column('farm_calendar_event_id', sa.Text(), nullable=True),
        sa.Column('local_event_id', postgresql.UUID(), nullable=True),
        sa.Column('barn_id', postgresql.UUID(), nullable=True),
        sa.Column('feeding_location_id', postgresql.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['barn_id'], ['barns.barn_id']),
        sa.ForeignKeyConstraint(['feeding_location_id'], ['feeding_locations.feeding_location_id']),
        sa.PrimaryKeyConstraint('link_id')
    )
    
    # FEEDING_LOCATION_SETTINGS
    op.create_table('feeding_location_settings',
        sa.Column('feeding_location_id', postgresql.UUID(), nullable=False),
        sa.Column('low_feed_threshold', sa.Double(), nullable=True),
        sa.ForeignKeyConstraint(['feeding_location_id'], ['feeding_locations.feeding_location_id']),
        sa.PrimaryKeyConstraint('feeding_location_id')
    )
    
    # AUDIT_LOGS
    op.create_table('audit_logs',
        sa.Column('audit_id', sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column('source', sa.Text(), nullable=True),
        sa.Column('actor', postgresql.UUID(), nullable=True),
        sa.Column('action', sa.Text(), nullable=True),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('audit_id')
    )
    
    # PROCESSING_JOBS
    op.create_table('processing_jobs',
        sa.Column('job_id', postgresql.UUID(), nullable=False),
        sa.Column('job_type', sa.Text(), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('job_id')
    )
    
    # Create indexes for better performance
    op.create_index('idx_devices_device_eui', 'devices', ['device_eui'])
    op.create_index('idx_iot_messages_device_eui', 'iot_raw_messages', ['device_eui'])


def downgrade():
    # Drop indexes
    op.drop_index('idx_iot_messages_device_eui')
    op.drop_index('idx_devices_device_eui')
    
    # Drop tables in reverse order (respecting foreign keys)
    op.drop_table('weather_observations')
    op.drop_table('processing_jobs')
    op.drop_table('audit_logs')
    op.drop_table('feeding_location_settings')
    op.drop_table('calendar_event_links')
    op.drop_table('system_events')
    op.drop_table('telemetry_readings')
    op.drop_table('iot_raw_messages')
    op.drop_table('device_feeding_location_map')
    op.drop_table('devices')
    op.drop_table('feeding_locations')
    op.drop_table('barns')
    op.drop_table('app_users')