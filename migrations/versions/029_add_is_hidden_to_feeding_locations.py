"""add is_hidden to feeding_locations

Revision ID: 029
Revises: 028
Create Date: 2026-03-26
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = '029'
down_revision = '028'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('feeding_locations') IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'feeding_locations'
                      AND column_name = 'is_hidden'
                ) THEN
                    ALTER TABLE feeding_locations
                    ADD COLUMN is_hidden BOOLEAN NOT NULL DEFAULT FALSE;
                END IF;

                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND indexname = 'idx_feeding_locations_is_hidden'
                ) THEN
                    CREATE INDEX idx_feeding_locations_is_hidden
                    ON feeding_locations (is_hidden);
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
                  AND indexname = 'idx_feeding_locations_is_hidden'
            ) THEN
                DROP INDEX idx_feeding_locations_is_hidden;
            END IF;

            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'feeding_locations'
                  AND column_name = 'is_hidden'
            ) THEN
                ALTER TABLE feeding_locations
                DROP COLUMN is_hidden;
            END IF;
        END$$;
        """
    )
