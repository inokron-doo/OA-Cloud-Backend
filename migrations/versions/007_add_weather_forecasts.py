"""add weather forecasts table

Revision ID: 007_add_weather_forecasts
Revises: 005_add_farms_table
Create Date: 2026-01-11

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '007_add_weather_forecasts'
down_revision = '005_add_farms_table'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('weather_forecasts') IS NULL THEN
                CREATE TABLE weather_forecasts (
                    forecast_id UUID DEFAULT gen_random_uuid() NOT NULL,
                    barn_id UUID NOT NULL,
                    forecast_time TIMESTAMPTZ NOT NULL,
                    forecast_for TIMESTAMPTZ NOT NULL,
                    temperature DOUBLE PRECISION,
                    humidity DOUBLE PRECISION,
                    thi DOUBLE PRECISION,
                    raw JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
                    PRIMARY KEY (forecast_id),
                    FOREIGN KEY (barn_id) REFERENCES barns (barn_id) ON DELETE CASCADE
                );
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
                   SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'weather_forecasts'
                     AND column_name = 'barn_id'
               ) THEN
                CREATE INDEX IF NOT EXISTS idx_forecasts_barn_id
                    ON weather_forecasts (barn_id);
            END IF;

            IF to_regclass('weather_forecasts') IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'weather_forecasts'
                     AND column_name = 'forecast_for'
               ) THEN
                CREATE INDEX IF NOT EXISTS idx_forecasts_forecast_for
                    ON weather_forecasts (forecast_for);
            END IF;

            IF to_regclass('weather_forecasts') IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'weather_forecasts'
                     AND column_name = 'barn_id'
               )
               AND EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'weather_forecasts'
                     AND column_name = 'forecast_for'
               ) THEN
                CREATE INDEX IF NOT EXISTS idx_forecasts_barn_time
                    ON weather_forecasts (barn_id, forecast_for);
            END IF;
        END $$;
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_forecasts_barn_time")
    op.execute("DROP INDEX IF EXISTS idx_forecasts_forecast_for")
    op.execute("DROP INDEX IF EXISTS idx_forecasts_barn_id")
    op.execute("DROP TABLE IF EXISTS weather_forecasts")
