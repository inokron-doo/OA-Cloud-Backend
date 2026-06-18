"""drop legacy tables and update telemetry barn FK

Revision ID: 023_drop_legacy_tables
Revises: 022_update_telemetry_readings_unique
Create Date: 2026-03-08

"""
from alembic import op

revision = '023'
down_revision = '022'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'telemetry_readings_barn_id_fkey'
            ) THEN
                ALTER TABLE telemetry_readings
                DROP CONSTRAINT telemetry_readings_barn_id_fkey;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        UPDATE telemetry_readings tr
        SET barn_id = NULL
        WHERE barn_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM farm_management_farmparcel fmp
              WHERE fmp.id = CASE
                  WHEN tr.barn_id::text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                      THEN tr.barn_id::uuid
                  ELSE NULL
              END
          );
        """
    )

    op.execute(
        """
        ALTER TABLE telemetry_readings
        ALTER COLUMN barn_id TYPE uuid
        USING CASE
            WHEN barn_id::text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                THEN barn_id::uuid
            ELSE NULL
        END;
        """
    )
    op.create_foreign_key(
        'telemetry_readings_barn_id_fkey',
        'telemetry_readings',
        'farm_management_farmparcel',
        ['barn_id'],
        ['id'],
        ondelete='CASCADE'
    )

    op.execute('DROP TABLE IF EXISTS app_users CASCADE')
    op.execute('DROP TABLE IF EXISTS farms CASCADE')
    op.execute('DROP TABLE IF EXISTS barns CASCADE')


def downgrade():
    op.execute('CREATE TABLE IF NOT EXISTS app_users (user_id uuid PRIMARY KEY, username text, password_hash text NOT NULL, display_name text, email text)')
    op.execute('CREATE TABLE IF NOT EXISTS barns (barn_id uuid PRIMARY KEY, name text, latitude double precision, longitude double precision)')
    op.execute('CREATE TABLE IF NOT EXISTS farms (id uuid PRIMARY KEY, name text NOT NULL, user_id integer NOT NULL, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL)')

    op.drop_constraint('telemetry_readings_barn_id_fkey', 'telemetry_readings', type_='foreignkey')
    op.create_foreign_key(
        'telemetry_readings_barn_id_fkey',
        'telemetry_readings',
        'barns',
        ['barn_id'],
        ['barn_id'],
        ondelete='CASCADE'
    )
