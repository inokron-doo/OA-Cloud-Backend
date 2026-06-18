"""add humidity column to weather_forecasts

Revision ID: 024_add_weather_forecasts_humidity
Revises: 023_drop_legacy_tables
Create Date: 2026-03-18

"""
from alembic import op


revision = '024'
down_revision = '023'
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
                     AND column_name = 'humidity'
               ) THEN
                ALTER TABLE weather_forecasts
                ADD COLUMN humidity DOUBLE PRECISION;
            END IF;
        END $$;
        """
    )


def downgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('weather_forecasts') IS NOT NULL
               AND EXISTS (
                   SELECT 1
                   FROM information_schema.columns
                   WHERE table_name = 'weather_forecasts'
                     AND column_name = 'humidity'
               ) THEN
                ALTER TABLE weather_forecasts
                DROP COLUMN humidity;
            END IF;
        END $$;
        """
    )
