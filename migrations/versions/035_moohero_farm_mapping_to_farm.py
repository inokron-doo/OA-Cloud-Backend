"""Repoint moohero_farm_mapping from barn to farm

The MooHero <-> local link is now established at the FARM level (Farm Calendar
is the system of record for farms). The table was never written to, so this is
a clean column swap: drop barn_id, add farm_id (FK farm_management_farm).

Revision ID: 035
Revises: 034
Create Date: 2026-06-17

"""
from alembic import op


revision = '035'
down_revision = '034'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DO $$
        BEGIN
            -- Drop the old barn-level link (column + its FK) if present.
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'moohero_farm_mapping' AND column_name = 'barn_id'
            ) THEN
                ALTER TABLE moohero_farm_mapping DROP COLUMN barn_id;
            END IF;

            -- Add the farm-level link.
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'moohero_farm_mapping' AND column_name = 'farm_id'
            ) THEN
                ALTER TABLE moohero_farm_mapping
                    ADD COLUMN farm_id uuid
                    REFERENCES farm_management_farm(id) ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )


def downgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'moohero_farm_mapping' AND column_name = 'farm_id'
            ) THEN
                ALTER TABLE moohero_farm_mapping DROP COLUMN farm_id;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'moohero_farm_mapping' AND column_name = 'barn_id'
            ) THEN
                ALTER TABLE moohero_farm_mapping
                    ADD COLUMN barn_id uuid
                    REFERENCES farm_management_farmparcel(id) ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )
