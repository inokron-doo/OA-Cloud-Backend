"""Add telemetry indexes for history and climate lookup queries

Revision ID: 031
Revises: 030
Create Date: 2026-04-01
"""

from alembic import op


revision = '031'
down_revision = '030'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('telemetry_readings') IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND indexname = 'idx_telemetry_feeding_location_time'
                ) THEN
                    CREATE INDEX idx_telemetry_feeding_location_time
                    ON telemetry_readings (feeding_location_id, time DESC);
                END IF;

                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND indexname = 'idx_telemetry_barn_kind_time'
                ) THEN
                    CREATE INDEX idx_telemetry_barn_kind_time
                    ON telemetry_readings (barn_id, reading_kind, time DESC);
                END IF;
            END IF;
        END$$;
        """
    )


def downgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND indexname = 'idx_telemetry_barn_kind_time'
            ) THEN
                DROP INDEX idx_telemetry_barn_kind_time;
            END IF;

            IF EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND indexname = 'idx_telemetry_feeding_location_time'
            ) THEN
                DROP INDEX idx_telemetry_feeding_location_time;
            END IF;
        END$$;
        """
    )
