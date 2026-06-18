"""update telemetry uniqueness for multi-location device payloads

Revision ID: 027_update_telemetry_unique_for_multilocation
Revises: 026_add_barn_id_to_devices
Create Date: 2026-03-25

"""
from alembic import op


revision = '027'
down_revision = '026'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('telemetry_readings') IS NOT NULL THEN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.table_constraints
                    WHERE table_name = 'telemetry_readings'
                      AND constraint_name = 'uq_telemetry_readings_time_device'
                ) THEN
                    ALTER TABLE telemetry_readings
                    DROP CONSTRAINT uq_telemetry_readings_time_device;
                END IF;

                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.table_constraints
                    WHERE table_name = 'telemetry_readings'
                      AND constraint_name = 'uq_telemetry_readings_time_device_location_kind'
                ) THEN
                    ALTER TABLE telemetry_readings
                    ADD CONSTRAINT uq_telemetry_readings_time_device_location_kind
                    UNIQUE (time, device_id, feeding_location_id, reading_kind);
                END IF;
            END IF;
        END $$;
        """
    )


def downgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('telemetry_readings') IS NOT NULL THEN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.table_constraints
                    WHERE table_name = 'telemetry_readings'
                      AND constraint_name = 'uq_telemetry_readings_time_device_location_kind'
                ) THEN
                    ALTER TABLE telemetry_readings
                    DROP CONSTRAINT uq_telemetry_readings_time_device_location_kind;
                END IF;

                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.table_constraints
                    WHERE table_name = 'telemetry_readings'
                      AND constraint_name = 'uq_telemetry_readings_time_device'
                ) THEN
                    ALTER TABLE telemetry_readings
                    ADD CONSTRAINT uq_telemetry_readings_time_device
                    UNIQUE (time, device_id);
                END IF;
            END IF;
        END $$;
        """
    )
