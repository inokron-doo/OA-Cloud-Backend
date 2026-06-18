"""update barn_id foreign keys to farm_management_farmparcel

Revision ID: 009_update_barn_fks
Revises: 008_password_reset
Create Date: 2026-01-18 20:14:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '009_update_barn_fks'
down_revision = '008_password_reset'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE feeding_locations fl
        SET barn_id = NULL
        WHERE barn_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM farm_management_farmparcel fmp
              WHERE fmp.id = fl.barn_id
          );
        """
    )

    op.execute("ALTER TABLE feeding_locations DROP CONSTRAINT IF EXISTS feeding_locations_barn_id_fkey")
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('feeding_locations') IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'feeding_locations'
                     AND column_name = 'barn_id'
               ) THEN
                ALTER TABLE feeding_locations
                    ADD CONSTRAINT feeding_locations_barn_id_fkey
                    FOREIGN KEY (barn_id) REFERENCES farm_management_farmparcel (id)
                    ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )

    op.execute("ALTER TABLE weather_observations DROP CONSTRAINT IF EXISTS weather_observations_barn_id_fkey")
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('weather_observations') IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'weather_observations'
                     AND column_name = 'barn_id'
               ) THEN
                ALTER TABLE weather_observations
                    ADD CONSTRAINT weather_observations_barn_id_fkey
                    FOREIGN KEY (barn_id) REFERENCES farm_management_farmparcel (id)
                    ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )

    op.execute("ALTER TABLE weather_forecasts DROP CONSTRAINT IF EXISTS weather_forecasts_barn_id_fkey")
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
                ALTER TABLE weather_forecasts
                    ADD CONSTRAINT weather_forecasts_barn_id_fkey
                    FOREIGN KEY (barn_id) REFERENCES farm_management_farmparcel (id)
                    ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )

    op.execute("ALTER TABLE alerts DROP CONSTRAINT IF EXISTS alerts_barn_id_fkey")
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('alerts') IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'alerts'
                     AND column_name = 'barn_id'
               ) THEN
                ALTER TABLE alerts
                    ADD CONSTRAINT alerts_barn_id_fkey
                    FOREIGN KEY (barn_id) REFERENCES farm_management_farmparcel (id)
                    ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )


def downgrade():
    op.drop_constraint('feeding_locations_barn_id_fkey', 'feeding_locations', type_='foreignkey')
    op.create_foreign_key(
        'feeding_locations_barn_id_fkey',
        'feeding_locations',
        'barns',
        ['barn_id'],
        ['barn_id'],
        ondelete='CASCADE'
    )
    
    op.drop_constraint('weather_observations_barn_id_fkey', 'weather_observations', type_='foreignkey')
    op.create_foreign_key(
        'weather_observations_barn_id_fkey',
        'weather_observations',
        'barns',
        ['barn_id'],
        ['barn_id'],
        ondelete='CASCADE'
    )
    
    op.drop_constraint('weather_forecasts_barn_id_fkey', 'weather_forecasts', type_='foreignkey')
    op.create_foreign_key(
        'weather_forecasts_barn_id_fkey',
        'weather_forecasts',
        'barns',
        ['barn_id'],
        ['barn_id'],
        ondelete='CASCADE'
    )
    
    op.drop_constraint('alerts_barn_id_fkey', 'alerts', type_='foreignkey')
    op.create_foreign_key(
        'alerts_barn_id_fkey',
        'alerts',
        'barns',
        ['barn_id'],
        ['barn_id'],
        ondelete='CASCADE'
    )
