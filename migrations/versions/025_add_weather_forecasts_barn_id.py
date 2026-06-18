"""add barn_id column to weather_forecasts

Revision ID: 025_add_weather_forecasts_barn_id
Revises: 024_add_weather_forecasts_humidity
Create Date: 2026-03-19

"""
from alembic import op


revision = '025'
down_revision = '024'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('weather_forecasts') IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1
                   FROM information_schema.columns
                   WHERE table_name = 'weather_forecasts'
                     AND column_name = 'barn_id'
               ) THEN
                ALTER TABLE weather_forecasts
                ADD COLUMN barn_id UUID;
            END IF;
        END $$;
        """
    )

    # Backfill barn_id using batch_id linkage to weather_observations when available.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('weather_forecasts') IS NOT NULL
               AND to_regclass('weather_observations') IS NOT NULL
               AND EXISTS (
                   SELECT 1
                   FROM information_schema.columns
                   WHERE table_name = 'weather_forecasts'
                     AND column_name = 'barn_id'
               )
               AND EXISTS (
                   SELECT 1
                   FROM information_schema.columns
                   WHERE table_name = 'weather_forecasts'
                     AND column_name = 'batch_id'
               )
               AND EXISTS (
                   SELECT 1
                   FROM information_schema.columns
                   WHERE table_name = 'weather_observations'
                     AND column_name = 'batch_id'
               )
               AND EXISTS (
                   SELECT 1
                   FROM information_schema.columns
                   WHERE table_name = 'weather_observations'
                     AND column_name = 'barn_id'
               ) THEN
                UPDATE weather_forecasts wf
                SET barn_id = src.barn_id
                FROM (
                                        SELECT DISTINCT ON (batch_id) batch_id, barn_id
                    FROM weather_observations
                    WHERE batch_id IS NOT NULL
                      AND barn_id IS NOT NULL
                                        ORDER BY batch_id, barn_id::text
                ) src
                WHERE wf.batch_id = src.batch_id
                  AND wf.barn_id IS NULL;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('weather_forecasts') IS NOT NULL
               AND EXISTS (
                   SELECT 1
                   FROM information_schema.columns
                   WHERE table_name = 'weather_forecasts'
                     AND column_name = 'barn_id'
               ) THEN
                CREATE INDEX IF NOT EXISTS idx_weather_forecasts_barn_id
                    ON weather_forecasts (barn_id);
            END IF;
        END $$;
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_weather_forecasts_barn_id")

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('weather_forecasts') IS NOT NULL
               AND EXISTS (
                   SELECT 1
                   FROM information_schema.columns
                   WHERE table_name = 'weather_forecasts'
                     AND column_name = 'barn_id'
               ) THEN
                ALTER TABLE weather_forecasts
                DROP COLUMN barn_id;
            END IF;
        END $$;
        """
    )
