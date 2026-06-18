from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '012_add_weather_batch_id'
down_revision = '011_add_feeding_schedules'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('weather_forecasts') IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'weather_forecasts'
                     AND column_name = 'batch_id'
               ) THEN
                ALTER TABLE weather_forecasts
                    ADD COLUMN batch_id UUID;
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
                     AND column_name = 'batch_id'
               ) THEN
                CREATE INDEX IF NOT EXISTS idx_weather_forecasts_batch_id
                    ON weather_forecasts (batch_id);
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
                     AND column_name = 'batch_id'
               ) THEN
                CREATE INDEX IF NOT EXISTS idx_weather_forecasts_barn_batch
                    ON weather_forecasts (barn_id, batch_id);
            END IF;
        END $$;
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_weather_forecasts_barn_batch")
    op.execute("DROP INDEX IF EXISTS idx_weather_forecasts_batch_id")
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('weather_forecasts') IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'weather_forecasts'
                     AND column_name = 'batch_id'
               ) THEN
                ALTER TABLE weather_forecasts
                    DROP COLUMN batch_id;
            END IF;
        END $$;
        """
    )
