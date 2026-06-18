"""add barn_id to devices

Revision ID: 026_add_barn_id_to_devices
Revises: 025_add_weather_forecasts_barn_id
Create Date: 2026-03-25

"""
from alembic import op


revision = '026'
down_revision = '025'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('devices') IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1
                   FROM information_schema.columns
                   WHERE table_name = 'devices'
                     AND column_name = 'barn_id'
               ) THEN
                ALTER TABLE devices
                ADD COLUMN barn_id UUID;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('devices') IS NOT NULL
               AND to_regclass('farm_management_farmparcel') IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1
                   FROM information_schema.table_constraints
                   WHERE table_name = 'devices'
                     AND constraint_name = 'devices_barn_id_fkey'
               ) THEN
                ALTER TABLE devices
                ADD CONSTRAINT devices_barn_id_fkey
                FOREIGN KEY (barn_id) REFERENCES farm_management_farmparcel (id)
                ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_devices_barn_id
            ON devices (barn_id);
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_devices_barn_id")
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('devices') IS NOT NULL
               AND EXISTS (
                   SELECT 1
                   FROM information_schema.table_constraints
                   WHERE table_name = 'devices'
                     AND constraint_name = 'devices_barn_id_fkey'
               ) THEN
                ALTER TABLE devices DROP CONSTRAINT devices_barn_id_fkey;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('devices') IS NOT NULL
               AND EXISTS (
                   SELECT 1
                   FROM information_schema.columns
                   WHERE table_name = 'devices'
                     AND column_name = 'barn_id'
               ) THEN
                ALTER TABLE devices DROP COLUMN barn_id;
            END IF;
        END $$;
        """
    )
