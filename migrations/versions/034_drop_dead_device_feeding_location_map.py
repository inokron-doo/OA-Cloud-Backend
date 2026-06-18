"""Drop the dead device_feeding_location_map table.

This table (note: NO trailing 's'/'pings') was created in the initial migration
but is never referenced by any code. The live device->feeding-location mapping
uses device_feeding_location_mappings (created in migration 028) instead. Having
both is a long-standing source of confusion during onboarding/ingest debugging.

Idempotent so it is safe on databases where the table was already removed.
"""
from alembic import op

revision = '034'
down_revision = '033'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP TABLE IF EXISTS device_feeding_location_map")


def downgrade():
    # Recreate the (empty) table as defined in the initial migration.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS device_feeding_location_map (
            device_id           uuid NOT NULL REFERENCES devices(device_id),
            feeding_location_id uuid NOT NULL REFERENCES feeding_locations(feeding_location_id),
            PRIMARY KEY (device_id, feeding_location_id)
        )
        """
    )
