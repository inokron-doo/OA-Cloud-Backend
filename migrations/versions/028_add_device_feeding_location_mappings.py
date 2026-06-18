"""add device feeding location mappings table

Revision ID: 028_add_device_feeding_location_mappings
Revises: 027_update_telemetry_unique_for_multilocation
Create Date: 2026-03-26

"""
from alembic import op


revision = '028'
down_revision = '027'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS device_feeding_location_mappings (
            mapping_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            device_id UUID NOT NULL,
            barn_id UUID NOT NULL,
            source_location_key TEXT NOT NULL,
            feeding_location_id UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_device_flm_device FOREIGN KEY (device_id)
                REFERENCES devices (device_id) ON DELETE CASCADE,
            CONSTRAINT fk_device_flm_barn FOREIGN KEY (barn_id)
                REFERENCES farm_management_farmparcel (id) ON DELETE CASCADE,
            CONSTRAINT fk_device_flm_location FOREIGN KEY (feeding_location_id)
                REFERENCES feeding_locations (feeding_location_id) ON DELETE CASCADE,
            CONSTRAINT uq_device_flm_device_source UNIQUE (device_id, source_location_key)
        );
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_device_flm_device
            ON device_feeding_location_mappings (device_id);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_device_flm_barn
            ON device_feeding_location_mappings (barn_id);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_device_flm_location
            ON device_feeding_location_mappings (feeding_location_id);
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_device_flm_location")
    op.execute("DROP INDEX IF EXISTS idx_device_flm_barn")
    op.execute("DROP INDEX IF EXISTS idx_device_flm_device")
    op.execute("DROP TABLE IF EXISTS device_feeding_location_mappings")
